from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import NAMESPACE_URL, UUID, uuid5

from hashlib import sha256

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from .dependencies import (
    correlation_id,
    get_authenticated_identity,
    get_object_store,
    get_principal,
    get_repository,
    require_idempotency_key,
)
from .models import (
    AnalysisJobResponse,
    AnalysisJobStatus,
    AnalysisRequest,
    AuthenticatedIdentity,
    AuditEvent,
    CompletedUpload,
    ClientCreate,
    DevelopmentDemoInspectionResponse,
    MediaResponse,
    Principal,
    ProfileResponse,
    InspectionResponse,
    InspectionCreate,
    OnboardingRequest,
    PropertyCreate,
    UploadCompletionRequest,
    UploadIntentRequest,
    UploadIntentResponse,
)
from .inference import QwenInferenceClient
from .repositories import InMemoryObjectStore, InMemoryRepository, ObjectStore, Repository
from .settings import (
    DEVELOPMENT_DEMO_INSPECTION_ID,
    DEVELOPMENT_DEMO_TENANT_ID,
    DEVELOPMENT_DEMO_USER_ID,
    get_settings,
)
from .supabase_adapters import SupabaseObjectStore, SupabaseRepository
from .directory import router as directory_router
from .reporting import router as reporting_router
from .worker import process_analysis


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.persistence_backend == "supabase":
        app.state.repository = SupabaseRepository(settings)
        app.state.object_store = SupabaseObjectStore(settings)
    else:
        app.state.repository = InMemoryRepository()
        app.state.object_store = InMemoryObjectStore(settings.development_upload_directory)
    app.state.inference_client = QwenInferenceClient(settings)
    if settings.development_identity_enabled and isinstance(
        app.state.repository, InMemoryRepository
    ):
        principal = Principal(
            tenant_id=DEVELOPMENT_DEMO_TENANT_ID, user_id=DEVELOPMENT_DEMO_USER_ID,
        )
        customer = app.state.repository.create_client(
            principal, ClientCreate(full_name="Development demo client"),
            uuid5(NAMESPACE_URL, "habitat:development:client"),
        )
        property_record = app.state.repository.create_property(
            principal, PropertyCreate(
                address_line1="Development test property", city="Demo City",
                region="ON", postal_code="A1A 1A1", country="CA",
            ), uuid5(NAMESPACE_URL, "habitat:development:property"),
        )
        app.state.repository.create_inspection(
            principal, InspectionCreate(client_id=customer.id, property_id=property_record.id),
            UUID(DEVELOPMENT_DEMO_INSPECTION_ID),
        )
    yield


app = FastAPI(
    title="Habitat Image Analysis API",
    version="0.1.0",
    description="Secure, human-reviewed home inspection image evidence ingestion.",
    lifespan=lifespan,
)
app.include_router(directory_router)
app.include_router(reporting_router)
cors_settings = get_settings()
cors_origins = cors_settings.development_cors_origins if cors_settings.development_identity_enabled else cors_settings.deployed_cors_origins
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=[
            "Content-Type",
            "Idempotency-Key",
            "X-Checksum-Sha256",
            "X-Dev-Roles",
            "X-Dev-Tenant-Id",
            "X-Dev-User-Id",
            "Authorization",
            "X-Storage-ETag",
        ],
        expose_headers=["ETag", "Content-Disposition"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/onboarding", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
def onboard_identity(
    payload: OnboardingRequest,
    identity: AuthenticatedIdentity = Depends(get_authenticated_identity),
    repository: Repository = Depends(get_repository),
) -> ProfileResponse:
    return repository.onboard_identity(identity, payload)


@app.get("/v1/inspections", response_model=list[InspectionResponse])
def list_inspections(
    limit: int = Query(50, ge=1, le=100),
    after: UUID | None = None,
    client_id: UUID | None = None,
    property_id: UUID | None = None,
    principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> list[InspectionResponse]:
    return repository.list_inspections(principal, limit, after, client_id, property_id)


@app.get(
    "/development/demo-inspection", response_model=DevelopmentDemoInspectionResponse
)
def development_demo_inspection(
    principal: Principal = Depends(get_principal),
) -> DevelopmentDemoInspectionResponse:
    if get_settings().app_env != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if (
        principal.tenant_id != DEVELOPMENT_DEMO_TENANT_ID
        or principal.user_id != DEVELOPMENT_DEMO_USER_ID
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This development fixture is only available to the demo inspector.",
        )
    return DevelopmentDemoInspectionResponse(
        inspection_id=UUID(DEVELOPMENT_DEMO_INSPECTION_ID),
        tenant_id=DEVELOPMENT_DEMO_TENANT_ID,
        user_id=DEVELOPMENT_DEMO_USER_ID,
        address="Development test property",
        environment="development",
    )


@app.post(
    "/v1/inspections/{inspection_id}/media/upload-intents",
    response_model=UploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_upload_intent(
    inspection_id: UUID,
    payload: UploadIntentRequest,
    principal: Principal = Depends(get_principal),
    idempotency_key: str = Depends(require_idempotency_key),
    request_id: str = Depends(correlation_id),
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
) -> UploadIntentResponse:
    repository.assert_inspection_access(principal, inspection_id)
    asset, created = repository.create_or_get_upload_intent(
        principal, inspection_id, payload, idempotency_key
    )
    upload_url, headers = object_store.create_upload_url(asset.object_key)
    existing_object = object_store.head_object(asset.object_key) if not created else None

    if created:
        repository.append_audit(
            AuditEvent(
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                correlation_id=request_id,
                aggregate_type="media_asset",
                aggregate_id=str(asset.id),
                event_type="media.upload_intent_created",
                metadata={"inspection_id": str(inspection_id)},
            )
        )
    return UploadIntentResponse(
        media_asset_id=asset.id,
        upload_url=upload_url,
        required_headers=headers,
        expires_at=repository.upload_expiry(),
        storage_etag=existing_object.etag if existing_object else None,
    )


@app.post("/v1/media/{media_asset_id}/complete", response_model=MediaResponse)
def complete_upload(
    media_asset_id: UUID,
    payload: UploadCompletionRequest,
    principal: Principal = Depends(get_principal),
    idempotency_key: str = Depends(require_idempotency_key),
    request_id: str = Depends(correlation_id),
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
) -> MediaResponse:
    asset = repository.get_media_for_principal(principal, media_asset_id)
    if payload.checksum_sha256.lower() != asset.checksum_sha256:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The completion checksum does not match the upload intent.",
        )

    object_head = object_store.head_object(asset.object_key)
    if object_head is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The storage provider does not yet confirm this upload.",
        )
    if object_head.etag != payload.storage_etag or (
        object_head.checksum_sha256
        and object_head.checksum_sha256 != asset.checksum_sha256
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Storage metadata does not match the approved upload intent.",
        )

    job, created = repository.complete_upload(
        asset,
        CompletedUpload(
            media_asset_id=asset.id,
            storage_etag=payload.storage_etag,
            checksum_sha256=payload.checksum_sha256,
        ),
        idempotency_key,
    )
    if created:
        repository.append_audit(
            AuditEvent(
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                correlation_id=request_id,
                aggregate_type="media_asset",
                aggregate_id=str(asset.id),
                event_type="media.upload_completed",
                metadata={"validation_job_id": str(job.id)},
            )
        )
    return MediaResponse(
        media_asset_id=asset.id,
        processing_state=asset.processing_state,
        validation_job_id=job.id,
    )


def run_analysis(
    repository: Repository,
    object_store: ObjectStore,
    inference_client: QwenInferenceClient,
    analysis_id: UUID,
    request: AnalysisRequest,
) -> None:
    job = repository.get_analysis_by_id(analysis_id)
    process_analysis(repository, object_store, inference_client, job, request, get_settings())


@app.post(
    "/v1/media/{media_asset_id}/analyses",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis(
    media_asset_id: UUID,
    payload: AnalysisRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    principal: Principal = Depends(get_principal),
    idempotency_key: str = Depends(require_idempotency_key),
    request_id: str = Depends(correlation_id),
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
) -> AnalysisJobResponse:
    asset = repository.get_media_for_principal(principal, media_asset_id)
    if asset.processing_state not in {"validation_queued", "ready_for_analysis"}:
        raise HTTPException(409, "Complete and validate the upload before requesting analysis.")
    if object_store.head_object(asset.object_key) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The storage provider does not yet confirm this upload.",
        )
    inference_client: QwenInferenceClient = request.app.state.inference_client
    job, created = repository.create_analysis_job(
        asset, payload, idempotency_key, inference_client.model_id, inference_client.model_version
    )
    if created:
        repository.append_audit(
            AuditEvent(
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                correlation_id=request_id,
                aggregate_type="analysis_job",
                aggregate_id=str(job.id),
                event_type="analysis.queued",
                metadata={"media_asset_id": str(asset.id)},
            )
        )
        if get_settings().inference_execution_mode == "background":
            background_tasks.add_task(run_analysis, repository, object_store, inference_client, job.id, payload)
    return AnalysisJobResponse(
        id=job.id,
        media_asset_id=job.media_asset_id,
        status=job.status,
        model_id=job.model_id,
        model_version=job.model_version,
        review_candidate=job.review_candidate,
        error_message=job.error_message,
        created_at=job.created_at,
    )


@app.get("/v1/analyses/{analysis_id}", response_model=AnalysisJobResponse)
def get_analysis(
    analysis_id: UUID,
    principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> AnalysisJobResponse:
    job = repository.get_analysis_for_principal(principal, analysis_id)
    return AnalysisJobResponse(
        id=job.id,
        media_asset_id=job.media_asset_id,
        status=job.status,
        model_id=job.model_id,
        model_version=job.model_version,
        review_candidate=job.review_candidate,
        error_message=job.error_message,
        created_at=job.created_at,
    )


@app.put("/development/uploads/{object_key:path}", status_code=status.HTTP_204_NO_CONTENT)
def development_upload(
    object_key: str,
    request: Request,
    content: bytes = Body(...),
    x_checksum_sha256: str = Header(..., alias="X-Checksum-Sha256"),
    object_store: ObjectStore = Depends(get_object_store),
) -> Response:
    """Development-only signed-upload emulator; production has no API byte-upload route."""
    if get_settings().app_env != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if not isinstance(object_store, InMemoryObjectStore):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if sha256(content).hexdigest() != x_checksum_sha256.lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Upload content checksum does not match X-Checksum-Sha256.",
        )
    object_store.record_development_upload(
        object_key=object_key,
        storage_etag=request.headers.get("X-Storage-ETag", "development-etag"),
        checksum_sha256=x_checksum_sha256,
        content=content,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
