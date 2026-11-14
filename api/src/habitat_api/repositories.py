from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID

from .models import (
    AnalysisJob,
    AnalysisJobStatus,
    AnalysisRequest,
    AuthenticatedIdentity,
    AuditEvent,
    CompletedUpload,
    ClientCreate,
    ClientResponse,
    PropertyCreate,
    PropertyResponse,
    InspectionCreate,
    MediaSummary,
    FindingReview,
    FindingReviewRequest,
    ApprovedReport,
    ReportApprovalRequest,
    MediaAsset,
    MediaProcessingState,
    ObjectHead,
    Principal,
    ProfileResponse,
    ReviewCandidate,
    InspectionResponse,
    OnboardingRequest,
    UploadIntentRequest,
    ValidationJob,
    utc_now,
)


class ObjectStore(Protocol):
    def write_object(self, object_key: str, content: bytes, content_type: str) -> None: ...
    def read_object(self, object_key: str) -> bytes: ...

    def create_upload_url(self, object_key: str) -> tuple[str, dict[str, str]]: ...

    def head_object(self, object_key: str) -> ObjectHead | None: ...

    def create_analysis_url(self, object_key: str) -> str: ...


class Repository(Protocol):
    def mark_media_validated(self, asset: MediaAsset, sanitized_key: str) -> None: ...
    def list_approved_reports(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[ApprovedReport]: ...
    def list_finding_reviews(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[FindingReview]: ...

    def save_finding_review(self, principal: Principal, inspection_id: UUID, payload: FindingReviewRequest, resource_id: UUID) -> FindingReview: ...

    def approve_report(self, principal: Principal, inspection_id: UUID, payload: ReportApprovalRequest, resource_id: UUID) -> ApprovedReport: ...

    def get_approved_report(self, principal: Principal, resource_id: UUID) -> ApprovedReport: ...

    def list_inspection_analyses(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[AnalysisJob]: ...
    def get_principal_for_identity(self, identity: AuthenticatedIdentity) -> Principal: ...

    def onboard_identity(
        self, identity: AuthenticatedIdentity, request: OnboardingRequest
    ) -> ProfileResponse: ...

    def list_inspections(
        self, principal: Principal, limit: int = 50, after: UUID | None = None,
        client_id: UUID | None = None, property_id: UUID | None = None,
    ) -> list[InspectionResponse]: ...

    def create_client(self, principal: Principal, payload: ClientCreate, resource_id: UUID) -> ClientResponse: ...

    def get_client(self, principal: Principal, resource_id: UUID) -> ClientResponse: ...

    def list_clients(self, principal: Principal, limit: int, after: UUID | None) -> list[ClientResponse]: ...

    def create_property(self, principal: Principal, payload: PropertyCreate, resource_id: UUID) -> PropertyResponse: ...

    def get_property(self, principal: Principal, resource_id: UUID) -> PropertyResponse: ...

    def list_properties(self, principal: Principal, limit: int, after: UUID | None, search: str | None) -> list[PropertyResponse]: ...

    def create_inspection(self, principal: Principal, payload: InspectionCreate, resource_id: UUID) -> InspectionResponse: ...

    def get_inspection(self, principal: Principal, resource_id: UUID) -> InspectionResponse: ...

    def list_inspection_media(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[MediaSummary]: ...

    def assert_inspection_access(self, principal: Principal, inspection_id: UUID) -> None: ...

    def create_or_get_upload_intent(
        self,
        principal: Principal,
        inspection_id: UUID,
        request: UploadIntentRequest,
        idempotency_key: str,
    ) -> tuple[MediaAsset, bool]: ...

    def get_media_for_principal(self, principal: Principal, media_id: UUID) -> MediaAsset: ...

    def get_media_by_id(self, media_id: UUID) -> MediaAsset: ...

    def complete_upload(
        self, asset: MediaAsset, completion: CompletedUpload, idempotency_key: str
    ) -> tuple[ValidationJob, bool]: ...

    def create_analysis_job(
        self,
        asset: MediaAsset,
        request: AnalysisRequest,
        idempotency_key: str,
        model_id: str,
        model_version: str,
    ) -> tuple[AnalysisJob, bool]: ...

    def get_analysis_for_principal(
        self, principal: Principal, analysis_id: UUID
    ) -> AnalysisJob: ...

    def get_analysis_by_id(self, analysis_id: UUID) -> AnalysisJob: ...

    def set_analysis_running(self, job: AnalysisJob) -> None: ...

    def block_analysis(self, job: AnalysisJob, error_message: str) -> None: ...

    def complete_analysis(self, job: AnalysisJob, candidate: ReviewCandidate) -> None: ...

    def append_audit(self, event: AuditEvent) -> None: ...

    def upload_expiry(self) -> object: ...


class InMemoryObjectStore:
    """Development-only object-storage seam; production uses an S3-compatible adapter."""

    def __init__(self, upload_directory: Path) -> None:
        self._uploaded: dict[str, ObjectHead] = {}
        self._upload_directory = upload_directory

    def create_upload_url(self, object_key: str) -> tuple[str, dict[str, str]]:
        return f"http://localhost:8000/development/uploads/{object_key}", {}

    def record_development_upload(
        self, object_key: str, storage_etag: str, checksum_sha256: str, content: bytes
    ) -> None:
        target = (self._upload_directory / object_key).resolve()
        root = self._upload_directory.resolve()
        if root not in target.parents:
            raise ValueError("Invalid development object key.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self._uploaded[object_key] = ObjectHead(
            etag=storage_etag, checksum_sha256=checksum_sha256.lower()
        )

    def head_object(self, object_key: str) -> ObjectHead | None:
        return self._uploaded.get(object_key)

    def read_object(self, object_key: str) -> bytes:
        target = (self._upload_directory / object_key).resolve()
        if self._upload_directory.resolve() not in target.parents:
            raise ValueError("Invalid development object key.")
        with target.open("rb") as source:
            content = source.read(25_000_001)
        if len(content) > 25_000_000:
            raise ValueError("Stored image exceeds the size limit.")
        return content

    def write_object(self, object_key: str, content: bytes, content_type: str) -> None:
        from hashlib import sha256

        self.record_development_upload(object_key, sha256(content).hexdigest(), sha256(content).hexdigest(), content)

    def create_analysis_url(self, object_key: str) -> str:
        """Development-only placeholder; production returns a short-lived private read URL."""
        return f"http://localhost:8000/development/uploads/{object_key}"


class InMemoryRepository:
    """Development-only repository preserving tenancy and idempotency semantics."""

    def __init__(self) -> None:
        self.media: dict[UUID, MediaAsset] = {}
        self.validation_jobs: dict[UUID, ValidationJob] = {}
        self.analysis_jobs: dict[UUID, AnalysisJob] = {}
        self.audit_events: list[AuditEvent] = []
        self.idempotency: dict[tuple[str, str, str], UUID] = {}
        self.inspection_access: dict[tuple[str, UUID], set[str]] = defaultdict(set)
        self.clients: dict[tuple[str, UUID], ClientResponse] = {}
        self.properties: dict[tuple[str, UUID], PropertyResponse] = {}
        self.inspections: dict[tuple[str, UUID], InspectionResponse] = {}
        self._directory_lock = RLock()
        self.finding_reviews: dict[tuple[str, UUID], FindingReview] = {}
        self.approved_reports: dict[tuple[str, UUID], ApprovedReport] = {}

    def list_inspection_analyses(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[AnalysisJob]:
        self.get_inspection(principal, inspection_id)
        rows = [job for job in list(self.analysis_jobs.values())
                if job.tenant_id == principal.tenant_id and self.media[job.media_asset_id].inspection_id == inspection_id
                and (after is None or job.id > after)]
        return sorted(rows, key=lambda job: job.id)[:limit]

    def list_finding_reviews(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[FindingReview]:
        self.get_inspection(principal, inspection_id)
        with self._directory_lock:
            rows = [row for (tenant_id, resource_id), row in self.finding_reviews.items()
                    if tenant_id == principal.tenant_id and row.inspection_id == inspection_id
                    and (after is None or resource_id > after)]
        return sorted(rows, key=lambda row: row.id)[:limit]

    def save_finding_review(self, principal: Principal, inspection_id: UUID, payload: FindingReviewRequest, resource_id: UUID) -> FindingReview:
        from fastapi import HTTPException

        self.get_inspection(principal, inspection_id)
        asset = self.get_media_for_principal(principal, payload.media_asset_id)
        if asset.inspection_id != inspection_id:
            raise HTTPException(422, "Photo belongs to another inspection.")
        candidate = FindingReview(id=resource_id, inspection_id=inspection_id, reviewer_id=principal.user_id, **payload.model_dump())
        with self._directory_lock:
            existing = self.finding_reviews.setdefault((principal.tenant_id, resource_id), candidate)
            if any(getattr(existing, field) != value for field, value in payload.model_dump().items()):
                raise HTTPException(409, "Review retry payload changed.")
            return existing

    def approve_report(self, principal: Principal, inspection_id: UUID, payload: ReportApprovalRequest, resource_id: UUID) -> ApprovedReport:
        from fastapi import HTTPException

        with self._directory_lock:
            inspection = self.get_inspection(principal, inspection_id)
            existing = self.approved_reports.get((principal.tenant_id, resource_id))
            if existing:
                if [row.id for row in existing.findings] != payload.finding_ids:
                    raise HTTPException(409, "Approval retry payload changed.")
                return existing
            findings = []
            for finding_id in payload.finding_ids:
                row = self.finding_reviews.get((principal.tenant_id, finding_id))
                if row is None or row.inspection_id != inspection_id or row.decision != "accepted":
                    raise HTTPException(409, "Only accepted findings from this inspection can be approved.")
                if any(tenant_id == principal.tenant_id and newer.inspection_id == inspection_id and newer.media_asset_id == row.media_asset_id
                       and (newer.reviewed_at, newer.id) > (row.reviewed_at, row.id) for (tenant_id, _), newer in self.finding_reviews.items()):
                    raise HTTPException(409, "A selected finding has a newer review. Refresh before approving.")
                findings.append(row)
            if len({row.media_asset_id for row in findings}) != len(findings):
                raise HTTPException(409, "Select only one reviewed finding per photo.")
            client_name = self.get_client(principal, inspection.client_id).full_name if inspection.client_id else "Not recorded"
            report = ApprovedReport(id=resource_id, inspection_id=inspection_id,
                                    property_address=inspection.property_address or "Not recorded", client_name=client_name,
                                    approved_by=principal.user_id, findings=findings)
            self.approved_reports[(principal.tenant_id, resource_id)] = report
            return report

    def get_approved_report(self, principal: Principal, resource_id: UUID) -> ApprovedReport:
        from fastapi import HTTPException

        report = self.approved_reports.get((principal.tenant_id, resource_id))
        if report is None:
            raise HTTPException(404, "Approved report not found.")
        self.get_inspection(principal, report.inspection_id)
        return report

    def list_approved_reports(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[ApprovedReport]:
        self.get_inspection(principal, inspection_id)
        with self._directory_lock:
            rows = [row for (tenant_id, resource_id), row in self.approved_reports.items()
                    if tenant_id == principal.tenant_id and row.inspection_id == inspection_id
                    and (after is None or resource_id > after)]
        return sorted(rows, key=lambda row: row.id)[:limit]

    def get_principal_for_identity(self, identity: AuthenticatedIdentity) -> Principal:
        raise RuntimeError("External identities are unavailable in the development repository.")

    def onboard_identity(
        self, identity: AuthenticatedIdentity, request: OnboardingRequest
    ) -> ProfileResponse:
        raise RuntimeError("External identities are unavailable in the development repository.")

    def list_inspections(
        self, principal: Principal, limit: int = 50, after: UUID | None = None,
        client_id: UUID | None = None, property_id: UUID | None = None,
    ) -> list[InspectionResponse]:
        with self._directory_lock:
            rows = [
                row for (tenant_id, resource_id), row in self.inspections.items()
                if tenant_id == principal.tenant_id
                and (after is None or resource_id > after)
                and (client_id is None or row.client_id == client_id)
                and (property_id is None or row.property_id == property_id)
                and (
                    principal.roles & {"admin", "owner"}
                    or principal.user_id in self.inspection_access.get((tenant_id, resource_id), set())
                )
            ]
        return sorted(rows, key=lambda row: row.id)[:limit]

    def create_client(self, principal: Principal, payload: ClientCreate, resource_id: UUID) -> ClientResponse:
        from fastapi import HTTPException

        key = (principal.tenant_id, resource_id)
        candidate = ClientResponse(id=resource_id, **payload.model_dump())
        with self._directory_lock:
            existing = self.clients.setdefault(key, candidate)
            if existing != candidate:
                raise HTTPException(409, "Idempotency key was already used with different data.")
            return existing

    def get_client(self, principal: Principal, resource_id: UUID) -> ClientResponse:
        from fastapi import HTTPException

        row = self.clients.get((principal.tenant_id, resource_id))
        if row is None:
            raise HTTPException(404, "Client not found.")
        return row

    def list_clients(self, principal: Principal, limit: int, after: UUID | None) -> list[ClientResponse]:
        with self._directory_lock:
            rows = [row for (tenant_id, resource_id), row in self.clients.items()
                    if tenant_id == principal.tenant_id and (after is None or resource_id > after)]
        return sorted(rows, key=lambda row: row.id)[:limit]

    def create_property(self, principal: Principal, payload: PropertyCreate, resource_id: UUID) -> PropertyResponse:
        from fastapi import HTTPException

        key = (principal.tenant_id, resource_id)
        candidate = PropertyResponse(id=resource_id, **payload.model_dump())
        with self._directory_lock:
            existing = self.properties.setdefault(key, candidate)
            if existing != candidate:
                raise HTTPException(409, "Idempotency key was already used with different data.")
            return existing

    def get_property(self, principal: Principal, resource_id: UUID) -> PropertyResponse:
        from fastapi import HTTPException

        row = self.properties.get((principal.tenant_id, resource_id))
        if row is None:
            raise HTTPException(404, "Property not found.")
        return row

    def list_properties(self, principal: Principal, limit: int, after: UUID | None, search: str | None) -> list[PropertyResponse]:
        with self._directory_lock:
            rows = [row for (tenant_id, resource_id), row in self.properties.items()
                    if tenant_id == principal.tenant_id and (after is None or resource_id > after)
                    and (not search or search.casefold() in row.display_address.casefold())]
        return sorted(rows, key=lambda row: row.id)[:limit]

    def create_inspection(self, principal: Principal, payload: InspectionCreate, resource_id: UUID) -> InspectionResponse:
        from fastapi import HTTPException

        with self._directory_lock:
            self.get_client(principal, payload.client_id)
            property_record = self.get_property(principal, payload.property_id)
            key = (principal.tenant_id, resource_id)
            existing = self.inspections.get(key)
            if existing is not None:
                if any(getattr(existing, field) != value for field, value in payload.model_dump().items()):
                    raise HTTPException(409, "Idempotency key was already used with different data.")
                return existing
            row = InspectionResponse(
                id=resource_id, status="scheduled", service_template_version="habitat-v1",
                property_address=property_record.display_address, **payload.model_dump(),
            )
            self.inspections[key] = row
            self.grant_inspection_access(principal.tenant_id, row.id, principal.user_id)
            return row

    def get_inspection(self, principal: Principal, resource_id: UUID) -> InspectionResponse:
        from fastapi import HTTPException

        row = self.inspections.get((principal.tenant_id, resource_id))
        if row is None:
            raise HTTPException(404, "Inspection not found.")
        self.assert_inspection_access(principal, resource_id)
        return row

    def list_inspection_media(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[MediaSummary]:
        self.get_inspection(principal, inspection_id)
        rows = [row for row in list(self.media.values())
                if row.tenant_id == principal.tenant_id and row.inspection_id == inspection_id
                and (after is None or row.id > after)]
        return [MediaSummary.model_validate(row.model_dump())
                for row in sorted(rows, key=lambda row: row.id)[:limit]]

    def grant_inspection_access(
        self, tenant_id: str, inspection_id: UUID, user_id: str
    ) -> None:
        self.inspection_access[(tenant_id, inspection_id)].add(user_id)

    def assert_inspection_access(self, principal: Principal, inspection_id: UUID) -> None:
        allowed = self.inspection_access.get((principal.tenant_id, inspection_id))
        if allowed is None or (
            principal.user_id not in allowed and not principal.roles & {"admin", "owner"}
        ):
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to add evidence to this inspection.",
            )

    def create_or_get_upload_intent(
        self,
        principal: Principal,
        inspection_id: UUID,
        request: UploadIntentRequest,
        idempotency_key: str,
    ) -> tuple[MediaAsset, bool]:
        key = (principal.tenant_id, f"upload-intent:{inspection_id}", idempotency_key)
        asset = MediaAsset(
            tenant_id=principal.tenant_id,
            inspection_id=inspection_id,
            created_by=principal.user_id,
            object_key=f"tenants/{principal.tenant_id}/media/{UUID(int=0)}",
            file_name=request.file_name,
            content_type=request.content_type,
            content_length=request.content_length,
            checksum_sha256=request.checksum_sha256.lower(),
            capture_timestamp=request.capture_timestamp,
            requested_category=request.requested_category,
            inspector_note=request.inspector_note,
        )
        asset.object_key = f"tenants/{principal.tenant_id}/media/{asset.id}"
        with self._directory_lock:
            existing_id = self.idempotency.get(key)
            if existing_id:
                existing = self.media[existing_id]
                if any(getattr(existing, field) != value for field, value in request.model_dump().items() if field != "checksum_sha256") or existing.checksum_sha256 != request.checksum_sha256.lower():
                    from fastapi import HTTPException

                    raise HTTPException(409, "Upload retry changed the photo or inspector context.")
                return existing, False
            self.media[asset.id] = asset
            self.idempotency[key] = asset.id
            return asset, True

    def get_media_for_principal(self, principal: Principal, media_id: UUID) -> MediaAsset:
        from fastapi import HTTPException, status

        asset = self.media.get(media_id)
        if asset is None or asset.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
        self.assert_inspection_access(principal, asset.inspection_id)
        return asset

    def get_media_by_id(self, media_id: UUID) -> MediaAsset:
        return self.media[media_id]

    def complete_upload(
        self,
        asset: MediaAsset,
        completion: CompletedUpload,
        idempotency_key: str,
    ) -> tuple[ValidationJob, bool]:
        key = (asset.tenant_id, f"upload-complete:{asset.id}", idempotency_key)
        existing_id = self.idempotency.get(key)
        if existing_id:
            return self.validation_jobs[existing_id], False

        job = ValidationJob(tenant_id=asset.tenant_id, media_asset_id=asset.id)
        self.validation_jobs[job.id] = job
        self.idempotency[key] = job.id
        asset.processing_state = MediaProcessingState.VALIDATION_QUEUED
        return job, True

    def create_analysis_job(
        self, asset: MediaAsset, request: AnalysisRequest, idempotency_key: str, model_id: str, model_version: str
    ) -> tuple[AnalysisJob, bool]:
        key = (asset.tenant_id, f"analysis:{asset.id}", idempotency_key)
        existing_id = self.idempotency.get(key)
        if existing_id:
            return self.analysis_jobs[existing_id], False

        job = AnalysisJob(
            tenant_id=asset.tenant_id,
            media_asset_id=asset.id,
            model_id=model_id,
            model_version=model_version,
        )
        self.analysis_jobs[job.id] = job
        self.idempotency[key] = job.id
        return job, True

    def get_analysis_for_principal(self, principal: Principal, analysis_id: UUID) -> AnalysisJob:
        from fastapi import HTTPException, status

        job = self.analysis_jobs.get(analysis_id)
        if job is None or job.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found.")
        self.get_media_for_principal(principal, job.media_asset_id)
        return job

    def mark_media_validated(self, asset: MediaAsset, sanitized_key: str) -> None:
        asset.processing_state = MediaProcessingState.READY_FOR_ANALYSIS
        asset.security_scan_status = "clean"

    def get_analysis_by_id(self, analysis_id: UUID) -> AnalysisJob:
        return self.analysis_jobs[analysis_id]

    @staticmethod
    def set_analysis_running(job: AnalysisJob) -> None:
        job.status = AnalysisJobStatus.RUNNING

    def block_analysis(self, job: AnalysisJob, error_message: str) -> None:
        job.status = AnalysisJobStatus.BLOCKED
        job.error_message = error_message

    def complete_analysis(self, job: AnalysisJob, candidate: ReviewCandidate) -> None:
        job.status = AnalysisJobStatus.SUCCEEDED
        job.review_candidate = candidate

    def append_audit(self, event: AuditEvent) -> None:
        self.audit_events.append(event)

    @staticmethod
    def upload_expiry() -> object:
        return utc_now() + timedelta(minutes=10)
