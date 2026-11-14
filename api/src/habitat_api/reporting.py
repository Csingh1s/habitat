from hashlib import sha256
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .dependencies import get_principal, get_repository, get_object_store, require_idempotency_key
from .directory import creation_id
from .models import ApprovedReport, AnalysisJobResponse, AnalysisJobStatus, FindingReview, FindingReviewRequest, MediaProcessingState, Principal, ReportApprovalRequest
from .repositories import Repository, ObjectStore
from .pdf_report import render_report
from .settings import get_settings


router = APIRouter(prefix="/v1", tags=["Inspector review and approval"])


def require_inspector(principal: Principal) -> None:
    if not principal.roles & {"inspector", "admin", "owner"}:
        raise HTTPException(403, "Inspector authorization is required for finding/report approval.")


@router.get("/inspections/{inspection_id}/analyses", response_model=list[AnalysisJobResponse])
def inspection_analyses(inspection_id: UUID, limit: int = Query(50, ge=1, le=100), after: UUID | None = None,
                        principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository)):
    return [AnalysisJobResponse.model_validate(job.model_dump()) for job in repository.list_inspection_analyses(principal, inspection_id, limit, after)]


@router.get("/inspections/{inspection_id}/findings", response_model=list[FindingReview])
def finding_reviews(inspection_id: UUID, limit: int = Query(50, ge=1, le=100), after: UUID | None = None,
                    principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository)):
    return repository.list_finding_reviews(principal, inspection_id, limit, after)


@router.post("/inspections/{inspection_id}/findings", response_model=FindingReview, status_code=201)
def review_finding(inspection_id: UUID, payload: FindingReviewRequest, key: str = Depends(require_idempotency_key),
                   principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository)):
    require_inspector(principal)
    asset = repository.get_media_for_principal(principal, payload.media_asset_id)
    if asset.inspection_id != inspection_id:
        raise HTTPException(422, "Photo belongs to another inspection.")
    if asset.processing_state not in {MediaProcessingState.VALIDATION_QUEUED, MediaProcessingState.READY_FOR_ANALYSIS}:
        raise HTTPException(409, "Complete the upload before reviewing this photo.")
    if not get_settings().development_identity_enabled and asset.security_scan_status != "clean":
        raise HTTPException(409, "Complete the photo security scan before reviewing this evidence.")
    if payload.analysis_id is not None:
        job = repository.get_analysis_for_principal(principal, payload.analysis_id)
        if job.media_asset_id != payload.media_asset_id or job.status != AnalysisJobStatus.SUCCEEDED:
            raise HTTPException(409, "The source analysis must be successful and linked to this photo.")
    return repository.save_finding_review(principal, inspection_id, payload, creation_id(principal, f"finding:{inspection_id}", key))


@router.post("/inspections/{inspection_id}/reports", response_model=ApprovedReport, status_code=201)
def approve_report(inspection_id: UUID, payload: ReportApprovalRequest, key: str = Depends(require_idempotency_key),
                   principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository)):
    require_inspector(principal)
    return repository.approve_report(principal, inspection_id, payload, creation_id(principal, f"report:{inspection_id}", key))


@router.get("/reports/{report_id}", response_model=ApprovedReport)
def get_report(report_id: UUID, principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository)):
    return repository.get_approved_report(principal, report_id)


@router.get("/inspections/{inspection_id}/reports", response_model=list[ApprovedReport])
def approved_reports(inspection_id: UUID, limit: int = Query(20, ge=1, le=100), after: UUID | None = None,
                     principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository)):
    return repository.list_approved_reports(principal, inspection_id, limit, after)


def photo_content(principal: Principal, media_id: UUID, repository: Repository, object_store: ObjectStore) -> tuple[bytes, str]:
    asset = repository.get_media_for_principal(principal, media_id)
    if asset.processing_state in {MediaProcessingState.UPLOAD_PENDING, MediaProcessingState.REJECTED}:
        raise HTTPException(409, "Photo is not available for review/export.")
    if not get_settings().development_identity_enabled and asset.security_scan_status != "clean":
        raise HTTPException(409, "Photo security validation has not completed.")
    try:
        content = object_store.read_object(asset.object_key)
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(409, "Stored photo cannot currently be retrieved.") from None
    if len(content) != asset.content_length or sha256(content).hexdigest() != asset.checksum_sha256.lower():
        raise HTTPException(409, "Stored photo integrity verification failed.")
    return content, asset.content_type


@router.get("/media/{media_id}/content")
def get_photo(media_id: UUID, principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository),
              object_store: ObjectStore = Depends(get_object_store)) -> Response:
    content, content_type = photo_content(principal, media_id, repository, object_store)
    return Response(content, media_type=content_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/reports/{report_id}/pdf")
def report_pdf(report_id: UUID, principal: Principal = Depends(get_principal), repository: Repository = Depends(get_repository),
               object_store: ObjectStore = Depends(get_object_store)) -> Response:
    snapshot = repository.get_approved_report(principal, report_id)
    def load_photo(media_id: UUID) -> bytes:
        return photo_content(principal, media_id, repository, object_store)[0]
    try:
        content = render_report(snapshot, load_photo)
    except (OSError, ValueError):
        raise HTTPException(409, "An evidence image cannot be safely rendered. Review its original before exporting.") from None
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="inspection-{report_id}.pdf"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })