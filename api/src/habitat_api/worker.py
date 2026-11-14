import logging
from hashlib import sha256
from io import BytesIO
from threading import Event

import clamd
from PIL import Image, ImageOps

from .inference import QwenInferenceClient
from .models import AnalysisJob, AnalysisRequest
from .repositories import ObjectStore, Repository
from .settings import Settings, get_settings
from .supabase_adapters import SupabaseObjectStore, SupabaseRepository


logger = logging.getLogger(__name__)


def validate_evidence(content: bytes, content_type: str) -> bytes:
    with Image.open(BytesIO(content)) as image:
        expected_format = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}.get(content_type)
        if image.format != expected_format or image.width * image.height > 30_000_000:
            raise ValueError("Evidence image type or dimensions are invalid.")
        image.verify()
    with Image.open(BytesIO(content)) as image:
        sanitized = ImageOps.exif_transpose(image).convert("RGB")
        sanitized.thumbnail((2048, 2048))
        result = BytesIO()
        sanitized.save(result, format="JPEG", quality=90)
        return result.getvalue()


def process_analysis(repository: Repository, object_store: ObjectStore, inference_client: QwenInferenceClient,
                     job: AnalysisJob, request: AnalysisRequest, settings: Settings) -> None:
    asset = repository.get_media_by_id(job.media_asset_id)
    if settings.development_identity_enabled and not inference_client.configured:
        repository.block_analysis(job, inference_client.unavailable_reason)
        return
    repository.set_analysis_running(job)
    try:
        content = object_store.read_object(asset.object_key)
        if len(content) != asset.content_length or sha256(content).hexdigest() != asset.checksum_sha256:
            raise ValueError("Evidence integrity validation failed.")
        if not settings.development_identity_enabled:
            scanner = clamd.ClamdNetworkSocket(host=settings.clamav_host, port=settings.clamav_port, timeout=60)
            scan = scanner.instream(BytesIO(content))
            if scan != {"stream": ("OK", None)}:
                raise ValueError("Evidence security scan did not pass.")
        sanitized = validate_evidence(content, asset.content_type)
        sanitized_key = f"{asset.tenant_id}/sanitized/{asset.id}.jpg"
        object_store.write_object(sanitized_key, sanitized, "image/jpeg")
        repository.mark_media_validated(asset, sanitized_key)
        if not inference_client.configured:
            repository.block_analysis(job, inference_client.unavailable_reason)
            return
        candidate = inference_client.analyze(asset, request, object_store.create_analysis_url(sanitized_key))
    except (RuntimeError, ValueError, OSError, clamd.ClamdError):
        repository.block_analysis(job, "Evidence validation or inference did not complete. Inspect the original and retry after correcting the service.")
        return
    repository.complete_analysis(job, candidate)


def main() -> None:
    settings = get_settings()
    if settings.persistence_backend != "supabase" or settings.inference_execution_mode != "worker":
        raise RuntimeError("The worker requires Supabase persistence and worker execution mode.")
    logging.basicConfig(level=logging.INFO)
    repository = SupabaseRepository(settings)
    object_store = SupabaseObjectStore(settings)
    inference_client = QwenInferenceClient(settings)
    stopping = Event()
    try:
        while not stopping.is_set():
            try:
                claimed = repository.claim_analysis_job()
                if claimed:
                    job, request = claimed
                    process_analysis(repository, object_store, inference_client, job, request, settings)
                else:
                    stopping.wait(2)
            except RuntimeError:
                logger.error("Worker operation failed; durable jobs remain recoverable by their lease.")
                stopping.wait(2)
    except KeyboardInterrupt:
        stopping.set()


if __name__ == "__main__":
    main()