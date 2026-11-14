from hashlib import sha256
from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import pytest
import clamd
from fastapi.testclient import TestClient
from PIL import Image

from habitat_api.inference import QwenInferenceClient
from habitat_api.main import app
from habitat_api.models import AnalysisJob, AnalysisRequest, MediaAsset, ReviewCandidate
from habitat_api.settings import Settings
from habitat_api.supabase_adapters import SupabaseRepository, SupabaseRequestError
from habitat_api.worker import process_analysis, validate_evidence


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 60), "green").save(output, format="JPEG")
    return output.getvalue()


def test_worker_uses_verified_sanitized_image_and_requires_review() -> None:
    content = image_bytes()
    repository = Mock()
    asset = MediaAsset(tenant_id="tenant", inspection_id=uuid4(), created_by="inspector", object_key="original/photo.jpg",
                       file_name="photo.jpg", content_type="image/jpeg", content_length=len(content),
                       checksum_sha256=sha256(content).hexdigest(), capture_timestamp="2026-11-14T00:00:00Z", requested_category=None)
    repository.get_media_by_id.return_value = asset
    store = Mock()
    store.read_object.return_value = content
    store.create_analysis_url.return_value = "https://private.example/sanitized.jpg"
    inference = Mock(spec=QwenInferenceClient)
    inference.configured = True
    candidate = ReviewCandidate(media_asset_id=asset.id, model_id="test", model_version="test", draft_caption="Photo",
                                confidence=0.5, uncertainty_reason="Inspector must verify.")
    inference.analyze.return_value = candidate
    job = AnalysisJob(tenant_id=asset.tenant_id, media_asset_id=asset.id, model_id="test", model_version="test")
    process_analysis(repository, store, inference, job, AnalysisRequest(), Settings(_env_file=None))
    assert store.write_object.call_args.args[0].endswith(f"sanitized/{asset.id}.jpg")
    assert inference.analyze.call_args.args[2] == "https://private.example/sanitized.jpg"
    repository.complete_analysis.assert_called_once_with(job, candidate)
    store.read_object.return_value = b"tampered"
    inference.reset_mock()
    process_analysis(repository, store, inference, job, AnalysisRequest(), Settings(_env_file=None))
    inference.analyze.assert_not_called()
    assert repository.block_analysis.called


def test_invalid_evidence_does_not_decode_as_an_image() -> None:
    with pytest.raises(OSError):
        validate_evidence(b"not an image", "image/jpeg")
    with pytest.raises(ValueError):
        validate_evidence(image_bytes(), "image/png")


def test_deployed_configuration_refuses_memory_and_missing_scanner() -> None:
    common = {"app_env": "production", "oidc_issuer_url": "https://issuer.example", "oidc_audience": "api",
              "oidc_jwks_url": "https://issuer.example/keys", "_env_file": None}
    with pytest.raises(RuntimeError, match="PERSISTENCE_BACKEND"):
        Settings(**common).validate_security_configuration()
    with pytest.raises(RuntimeError, match="CLAMAV_HOST"):
        Settings(**common, persistence_backend="supabase", inference_execution_mode="worker", supabase_url="https://db.example", supabase_service_role_key="test").validate_security_configuration()


def test_expired_worker_result_is_fenced() -> None:
    repository = SupabaseRepository(Settings(_env_file=None, supabase_url="https://db.example", supabase_service_role_key="test"))
    repository._client = Mock()
    repository._client.request.return_value = (False, {})
    job = AnalysisJob(tenant_id=str(uuid4()), media_asset_id=uuid4(), model_id="test", model_version="test", lease_token=uuid4())
    with pytest.raises(SupabaseRequestError, match="stale worker"):
        repository.block_analysis(job, "Service unavailable")
    assert repository._client.request.call_args.kwargs["payload"]["p_lease_token"] == str(job.lease_token)


def test_scanner_outage_blocks_inference(monkeypatch) -> None:
    content = image_bytes()
    asset = MediaAsset(tenant_id=str(uuid4()), inspection_id=uuid4(), created_by=str(uuid4()), object_key="original/photo.jpg",
                       file_name="photo.jpg", content_type="image/jpeg", content_length=len(content), requested_category=None,
                       checksum_sha256=sha256(content).hexdigest(), capture_timestamp="2026-11-14T00:00:00Z")
    repository = Mock()
    repository.get_media_by_id.return_value = asset
    store = Mock()
    store.read_object.return_value = content
    scanner = Mock()
    scanner.instream.side_effect = clamd.ConnectionError("scanner unavailable")
    monkeypatch.setattr("habitat_api.worker.clamd.ClamdNetworkSocket", Mock(return_value=scanner))
    inference = Mock()
    job = AnalysisJob(tenant_id=asset.tenant_id, media_asset_id=asset.id, model_id="test", model_version="test")
    process_analysis(repository, store, inference, job, AnalysisRequest(), Settings(_env_file=None, app_env="production", clamav_host="private-scanner"))
    inference.analyze.assert_not_called()
    repository.block_analysis.assert_called_once()


def test_successful_analysis_is_visible_but_not_an_approved_finding() -> None:
    headers = {"X-Dev-Tenant-Id": "demo-tenant", "X-Dev-User-Id": "demo-inspector", "Idempotency-Key": "analysis-workflow-test"}
    with TestClient(app) as client:
        inspection_id = client.get("/development/demo-inspection", headers=headers).json()["inspection_id"]
        content = image_bytes()
        checksum = sha256(content).hexdigest()
        intent = client.post(f"/v1/inspections/{inspection_id}/media/upload-intents", headers=headers, json={
            "file_name": "test.jpg", "content_type": "image/jpeg", "content_length": len(content), "checksum_sha256": checksum,
            "capture_timestamp": "2026-11-14T00:00:00Z", "requested_category": "roofing",
        }).json()
        media_id = intent["media_asset_id"]
        assert client.put(intent["upload_url"].split("localhost:8000")[1], content=content, headers={"Content-Type": "application/octet-stream", "X-Checksum-Sha256": checksum}).status_code == 204
        assert client.post(f"/v1/media/{media_id}/complete", headers=headers, json={"checksum_sha256": checksum, "storage_etag": "development-etag"}).status_code == 200
        fake_inference = Mock(spec=QwenInferenceClient)
        fake_inference.configured = True
        fake_inference.model_id = "test-model"
        fake_inference.model_version = "test-version"
        fake_inference.analyze.return_value = ReviewCandidate(media_asset_id=media_id, model_id="test-model", model_version="test-version",
            category_candidate="roofing", draft_caption="Test model caption", confidence=0.5, uncertainty_reason="Test only; inspector verification required.")
        app.state.inference_client = fake_inference
        analysis = client.post(f"/v1/media/{media_id}/analyses", headers=headers, json={"requested_category": "roofing"}).json()
        result = client.get(f"/v1/analyses/{analysis['id']}", headers=headers).json()
        assert result["status"] == "succeeded"
        assert result["review_candidate"]["requires_human_review"] is True
        assert client.get(f"/v1/inspections/{inspection_id}/analyses", headers=headers).json()[0]["review_candidate"]["draft_caption"] == "Test model caption"
        assert client.get(f"/v1/inspections/{inspection_id}/findings", headers=headers).json() == []
        assert client.get(f"/v1/inspections/{inspection_id}/reports", headers=headers).json() == []