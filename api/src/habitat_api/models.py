from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InspectionCategory(StrEnum):
    ROOFING = "roofing"
    EXTERIOR = "exterior"
    STRUCTURE = "structure"
    ELECTRICAL = "electrical"
    HEATING = "heating"
    COOLING = "cooling"
    INSULATION = "insulation"
    PLUMBING = "plumbing"
    INTERIOR = "interior"


class MediaProcessingState(StrEnum):
    UPLOAD_PENDING = "upload_pending"
    VALIDATION_QUEUED = "validation_queued"
    READY_FOR_ANALYSIS = "ready_for_analysis"
    REJECTED = "rejected"


class AnalysisJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"


class UploadIntentRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(pattern=r"^image/(jpeg|png|webp)$")
    content_length: int = Field(gt=0, le=25_000_000)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    capture_timestamp: datetime
    requested_category: InspectionCategory | None = None
    inspector_note: str = Field(default="", max_length=1_000)


class UploadIntentResponse(BaseModel):
    media_asset_id: UUID
    upload_url: HttpUrl
    required_headers: dict[str, str]
    expires_at: datetime
    storage_etag: str | None = None


class DevelopmentDemoInspectionResponse(BaseModel):
    inspection_id: UUID
    tenant_id: str
    user_id: str
    address: str
    environment: str


class DevelopmentLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)


class ShortTranscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_base64: str = Field(min_length=4, max_length=7_000_000)
    audio_format: Literal["aac", "amr", "flac", "m4a", "mp3", "ogg", "opus", "wav"]
    sample_rate: int = Field(ge=8_000, le=48_000)
    duration_seconds: float = Field(gt=0, le=300)

    @field_validator("audio_base64")
    @classmethod
    def validate_audio_base64(cls, value: str) -> str:
        try:
            audio = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Audio must be valid base64 data.") from error
        if not audio or len(audio) > 5_000_000:
            raise ValueError("Audio must be between 1 byte and 5 MB.")
        return value


class UploadCompletionRequest(BaseModel):
    storage_etag: str = Field(min_length=1, max_length=255)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class MediaResponse(BaseModel):
    media_asset_id: UUID
    processing_state: MediaProcessingState
    validation_job_id: UUID | None = None


class AnalysisRequest(BaseModel):
    requested_category: InspectionCategory | None = None


class EvidenceMarker(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    label: str = Field(min_length=1, max_length=128)


class ReviewCandidate(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    media_asset_id: UUID
    model_id: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    category_candidate: InspectionCategory | None = None
    component_candidate: str | None = Field(default=None, max_length=128)
    visible_indicator_candidates: list[str] = Field(default_factory=list, max_length=8)
    evidence_marker: EvidenceMarker | None = None
    draft_caption: str = Field(min_length=1, max_length=500)
    draft_observation: str | None = Field(default=None, max_length=1_000)
    confidence: float = Field(ge=0, le=1)
    uncertainty_reason: str = Field(min_length=1, max_length=1_000)
    requires_human_review: Literal[True] = True


class AnalysisJobResponse(BaseModel):
    id: UUID
    media_asset_id: UUID
    status: AnalysisJobStatus
    model_id: str
    model_version: str
    review_candidate: ReviewCandidate | None = None
    error_message: str | None = None
    created_at: datetime | None = None


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    roles: frozenset[str] = frozenset({"inspector"})


class AuthenticatedIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer: str = Field(min_length=1, max_length=1_000)
    subject: str = Field(min_length=1, max_length=255)
    user_id: UUID
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)


class OnboardingRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    country: str = Field(pattern=r"^(United States|Canada)$")
    region: str = Field(min_length=2, max_length=100)


class ProfileResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    full_name: str
    email: str | None = None
    role: str
    country: str | None = None
    region: str | None = None


class InspectionResponse(BaseModel):
    id: UUID
    status: str
    service_template_version: str
    scheduled_for: datetime | None = None
    property_address: str | None = None
    assigned_inspector_id: UUID | None = None
    client_id: UUID | None = None
    property_id: UUID | None = None


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)


class ClientResponse(ClientCreate):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)


class PropertyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    address_line1: str = Field(min_length=1, max_length=200)
    address_line2: str = Field(default="", max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    country: str = Field(pattern=r"^(CA|US)$")


class PropertyResponse(PropertyCreate):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)

    @property
    def display_address(self) -> str:
        return ", ".join(
            part for part in (
                self.address_line1, self.address_line2, self.city,
                self.region, self.postal_code, self.country,
            ) if part
        )


class InspectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    property_id: UUID
    scheduled_for: datetime | None = None


class MediaSummary(BaseModel):
    id: UUID
    inspection_id: UUID
    file_name: str
    content_type: str
    content_length: int
    capture_timestamp: datetime
    requested_category: InspectionCategory | None
    processing_state: MediaProcessingState
    inspector_note: str = ""


class FindingReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    media_asset_id: UUID
    analysis_id: UUID | None = None
    decision: Literal["accepted", "rejected", "needs_verification"]
    category: InspectionCategory
    location: str = Field(min_length=1, max_length=200)
    caption: str = Field(min_length=1, max_length=500)
    observation: str = Field(min_length=1, max_length=1_000)


class FindingReview(FindingReviewRequest):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: UUID
    inspection_id: UUID
    reviewer_id: str
    reviewed_at: datetime = Field(default_factory=utc_now)


class ReportApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_ids: list[UUID] = Field(min_length=1, max_length=200)
    inspector_approved: Literal[True]

    @field_validator("finding_ids")
    @classmethod
    def unique_findings(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Finding IDs must be unique.")
        return value


class ApprovedReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    inspection_id: UUID
    property_address: str
    client_name: str
    approved_by: str
    approved_at: datetime = Field(default_factory=utc_now)
    findings: list[FindingReview]


class MediaAsset(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    inspection_id: UUID
    created_by: str
    object_key: str
    file_name: str
    content_type: str
    content_length: int
    checksum_sha256: str
    capture_timestamp: datetime
    requested_category: InspectionCategory | None
    processing_state: MediaProcessingState = MediaProcessingState.UPLOAD_PENDING
    security_scan_status: str = "pending"
    inspector_note: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ValidationJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    media_asset_id: UUID
    status: str = "queued"
    created_at: datetime = Field(default_factory=utc_now)


class AnalysisJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    media_asset_id: UUID
    model_id: str
    model_version: str
    status: AnalysisJobStatus = AnalysisJobStatus.QUEUED
    review_candidate: ReviewCandidate | None = None
    error_message: str | None = None
    lease_token: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)

class AuditEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    actor_id: str
    correlation_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    occurred_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, str] = Field(default_factory=dict)


class ObjectHead(BaseModel):
    etag: str
    checksum_sha256: str


class CompletedUpload(BaseModel):
    media_asset_id: UUID
    storage_etag: str
    checksum_sha256: str

    @field_validator("checksum_sha256")
    @classmethod
    def normalize_checksum(cls, value: str) -> str:
        return value.lower()
