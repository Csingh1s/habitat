from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException, status

from .models import (
    AnalysisJob,
    AnalysisJobStatus,
    AnalysisRequest,
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
from .settings import Settings


class SupabaseRequestError(RuntimeError):
    """A server-side Supabase REST or Storage request did not complete successfully."""


def _uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authenticated {field_name} must be a UUID.",
        ) from error


class _SupabaseHttpClient:
    def __init__(self, base_url: str, service_role_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_role_key = service_role_key

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | list[dict[str, Any]] | bytes | None = None,
        headers: dict[str, str] | None = None,
        raw: bool = False,
        max_bytes: int | None = None,
    ) -> tuple[Any, dict[str, str]]:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request_headers = {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
        }
        if headers:
            request_headers.update(headers)
        body = None
        if isinstance(payload, bytes):
            body = payload
        elif payload is not None:
            body = json.dumps(payload).encode()
            request_headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                body_bytes = response.read(max_bytes + 1) if max_bytes is not None else response.read()
                if max_bytes is not None and len(body_bytes) > max_bytes:
                    raise SupabaseRequestError("Supabase response exceeds the allowed size.")
                response_headers = dict(response.headers.items())
        except HTTPError as error:
            body_bytes = error.read().decode(errors="replace")
            raise SupabaseRequestError(
                f"Supabase request {method} {path} failed with {error.code}: {body_bytes}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise SupabaseRequestError(
                f"Supabase request {method} {path} could not reach the service: {error}"
            ) from error

        if raw:
            return body_bytes, response_headers
        if not body_bytes:
            return None, response_headers
        return json.loads(body_bytes), response_headers


class SupabaseObjectStore:
    """Private Supabase Storage adapter; only FastAPI holds the service-role key."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("Supabase storage requires server-side configuration.")
        self._client = _SupabaseHttpClient(
            settings.supabase_url, settings.supabase_service_role_key
        )
        self._bucket = settings.supabase_storage_bucket
        self._base_url = settings.supabase_url.rstrip("/")

    def _storage_path(self, suffix: str) -> str:
        return f"/storage/v1/{suffix.lstrip('/')}"

    def _signed_url(self, relative_url: str) -> str:
        if relative_url.startswith("http"):
            return relative_url
        return f"{self._base_url}/storage/v1{relative_url}"

    def create_upload_url(self, object_key: str) -> tuple[str, dict[str, str]]:
        path = quote(object_key, safe="/")
        payload, _ = self._client.request(
            "POST",
            self._storage_path(f"object/upload/sign/{self._bucket}/{path}"),
            payload={"upsert": "false"},
        )
        signed_url = payload.get("url") or payload.get("signedURL")
        if not isinstance(signed_url, str):
            raise SupabaseRequestError("Supabase did not return a signed upload URL.")
        return self._signed_url(signed_url), {"x-upsert": "false"}

    def head_object(self, object_key: str) -> ObjectHead | None:
        path = quote(object_key, safe="/")
        try:
            _, headers = self._client.request(
                "GET",
                self._storage_path(f"object/{self._bucket}/{path}"),
                headers={"Range": "bytes=0-0"},
                raw=True,
            )
        except SupabaseRequestError as error:
            if " failed with 404:" in str(error):
                return None
            raise
        etag = headers.get("ETag") or headers.get("etag")
        if not etag:
            raise SupabaseRequestError("Supabase object confirmation did not include an ETag.")
        return ObjectHead(etag=etag.strip('"'), checksum_sha256="")

    def create_analysis_url(self, object_key: str) -> str:
        path = quote(object_key, safe="/")
        payload, _ = self._client.request(
            "POST",
            self._storage_path(f"object/sign/{self._bucket}/{path}"),
            payload={"expiresIn": 60},
        )
        signed_url = payload.get("signedURL")
        if not isinstance(signed_url, str):
            raise SupabaseRequestError("Supabase did not return a signed analysis URL.")
        return self._signed_url(signed_url)

    def read_object(self, object_key: str) -> bytes:
        path = quote(object_key, safe="/")
        content, _ = self._client.request("GET", self._storage_path(f"object/{self._bucket}/{path}"),
                                           raw=True, max_bytes=25_000_000)
        return content

    def write_object(self, object_key: str, content: bytes, content_type: str) -> None:
        path = quote(object_key, safe="/")
        self._client.request("POST", self._storage_path(f"object/{self._bucket}/{path}"), payload=content,
                             headers={"Content-Type": content_type, "x-upsert": "true"})


class SupabaseRepository:
    """PostgREST adapter using a server-only service role behind FastAPI authorization."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("Supabase database requires server-side configuration.")
        self._client = _SupabaseHttpClient(
            settings.supabase_url, settings.supabase_service_role_key
        )

    @staticmethod
    def _tenant_id(principal: Principal) -> UUID:
        return _uuid(principal.tenant_id, "tenant ID")

    @staticmethod
    def _user_id(principal: Principal) -> UUID:
        return _uuid(principal.user_id, "user ID")

    def _select_one(self, table: str, query: dict[str, str]) -> dict[str, Any] | None:
        payload, _ = self._client.request(
            "GET", f"/rest/v1/{table}", query={**query, "limit": "1"}
        )
        if not payload:
            return None
        return payload[0]

    def _insert(
        self, table: str, payload: dict[str, Any], *, on_conflict: str | None = None
    ) -> dict[str, Any]:
        headers = {"Prefer": "return=representation"}
        query = {"on_conflict": on_conflict} if on_conflict else None
        response, _ = self._client.request(
            "POST", f"/rest/v1/{table}", query=query, payload=payload, headers=headers
        )
        if not response:
            raise SupabaseRequestError(f"Supabase did not return inserted {table} data.")
        return response[0]

    def _update(
        self, table: str, query: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        response, _ = self._client.request(
            "PATCH",
            f"/rest/v1/{table}",
            query=query,
            payload=payload,
            headers={"Prefer": "return=representation"},
        )
        if not response:
            raise SupabaseRequestError(f"Supabase did not return updated {table} data.")
        return response[0]

    @staticmethod
    def _media(row: dict[str, Any]) -> MediaAsset:
        return MediaAsset(
            id=UUID(row["id"]),
            tenant_id=row["tenant_id"],
            inspection_id=UUID(row["inspection_id"]),
            created_by=row["created_by"],
            object_key=row["original_object_key"],
            file_name=row["file_name"],
            content_type=row["content_type"],
            content_length=row["content_length"],
            checksum_sha256=row["checksum_sha256"],
            capture_timestamp=datetime.fromisoformat(row["capture_timestamp"]),
            requested_category=row.get("requested_category"),
            processing_state=MediaProcessingState(row["processing_status"]),
            security_scan_status=row.get("security_scan_status", "pending"),
            inspector_note=row.get("inspector_note", ""),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _analysis_job(
        row: dict[str, Any], candidate: ReviewCandidate | None = None
    ) -> AnalysisJob:
        return AnalysisJob(
            id=UUID(row["id"]),
            tenant_id=row["tenant_id"],
            media_asset_id=UUID(row["media_asset_id"]),
            model_id=row["model_id"],
            model_version=row["model_version"],
            status=AnalysisJobStatus(row["status"]),
            review_candidate=candidate,
            error_message=row.get("error_code"),
            lease_token=row.get("lease_token"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _profile(row: dict[str, Any]) -> ProfileResponse:
        return ProfileResponse(
            user_id=UUID(row["id"]),
            tenant_id=UUID(row["tenant_id"]),
            full_name=row["display_name"],
            email=row.get("email"),
            role=row["role"],
            country=row.get("country"),
            region=row.get("region"),
        )

    def get_principal_for_identity(self, identity: AuthenticatedIdentity) -> Principal:
        row = self._select_one(
            "profiles",
            {
                "select": "id,tenant_id,role,is_active",
                "identity_issuer": f"eq.{identity.issuer}",
                "identity_subject": f"eq.{identity.subject}",
            },
        )
        if row is None or not row["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Complete account onboarding before accessing inspection data.",
            )
        return Principal(
            tenant_id=row["tenant_id"],
            user_id=row["id"],
            roles=frozenset({row["role"]}),
        )

    def onboard_identity(
        self, identity: AuthenticatedIdentity, request: OnboardingRequest
    ) -> ProfileResponse:
        payload, _ = self._client.request(
            "POST",
            "/rest/v1/rpc/onboard_entra_identity",
            payload={
                "p_user_id": str(identity.user_id),
                "p_identity_issuer": identity.issuer,
                "p_identity_subject": identity.subject,
                "p_email": identity.email,
                "p_display_name": request.full_name,
                "p_company_name": request.company_name,
                "p_country": request.country,
                "p_region": request.region,
            },
        )
        row = payload[0] if isinstance(payload, list) else payload
        if not isinstance(row, dict):
            raise SupabaseRequestError("Supabase onboarding did not return a profile.")
        return self._profile(row)

    def list_inspections(
        self, principal: Principal, limit: int = 50, after: UUID | None = None,
        client_id: UUID | None = None, property_id: UUID | None = None,
    ) -> list[InspectionResponse]:
        query = {
            "select": "id,status,service_template_version,scheduled_for,property_address,assigned_inspector_id,client_id,property_id",
            "tenant_id": f"eq.{self._tenant_id(principal)}",
            "order": "id.asc",
            "limit": str(limit),
        }
        if after is not None:
            query["id"] = f"gt.{after}"
        if client_id is not None:
            query["client_id"] = f"eq.{client_id}"
        if property_id is not None:
            query["property_id"] = f"eq.{property_id}"
        if "admin" not in principal.roles and "owner" not in principal.roles:
            query["assigned_inspector_id"] = f"eq.{self._user_id(principal)}"
        rows, _ = self._client.request("GET", "/rest/v1/inspections", query=query)
        return [InspectionResponse.model_validate(row) for row in rows]

    def _directory_get(self, principal: Principal, table: str, resource_id: UUID) -> dict[str, Any]:
        row = self._select_one(table, {
            "select": "*", "tenant_id": f"eq.{self._tenant_id(principal)}",
            "id": f"eq.{resource_id}",
        })
        if row is None:
            raise HTTPException(404, "Record not found.")
        return row

    def list_inspection_analyses(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[AnalysisJob]:
        self.assert_inspection_access(principal, inspection_id)
        query = {"select": "*,ai_review_candidates(*)", "tenant_id": f"eq.{self._tenant_id(principal)}",
                 "inspection_id": f"eq.{inspection_id}", "order": "id.asc", "limit": str(limit)}
        if after is not None:
            query["id"] = f"gt.{after}"
        rows, _ = self._client.request("GET", "/rest/v1/analysis_jobs", query=query)
        jobs = []
        for row in rows:
            related = row.get("ai_review_candidates")
            candidate_row = related[0] if isinstance(related, list) and related else related if isinstance(related, dict) else None
            candidate = ReviewCandidate.model_validate(candidate_row) if candidate_row else None
            jobs.append(self._analysis_job(row, candidate))
        return jobs

    @staticmethod
    def _finding(row: dict[str, Any]) -> FindingReview:
        return FindingReview.model_validate({**row["payload"], "id": row["id"], "inspection_id": row["inspection_id"],
                                             "reviewer_id": row["reviewer_id"], "reviewed_at": row["reviewed_at"]})

    def list_finding_reviews(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[FindingReview]:
        self.assert_inspection_access(principal, inspection_id)
        query = {"select": "*", "tenant_id": f"eq.{self._tenant_id(principal)}",
                 "inspection_id": f"eq.{inspection_id}", "order": "id.asc", "limit": str(limit)}
        if after is not None:
            query["id"] = f"gt.{after}"
        rows, _ = self._client.request("GET", "/rest/v1/finding_review_records", query=query)
        return [self._finding(row) for row in rows]

    def save_finding_review(self, principal: Principal, inspection_id: UUID, payload: FindingReviewRequest, resource_id: UUID) -> FindingReview:
        self.assert_inspection_access(principal, inspection_id)
        asset = self.get_media_for_principal(principal, payload.media_asset_id)
        if asset.inspection_id != inspection_id:
            raise HTTPException(422, "Photo belongs to another inspection.")
        data = payload.model_dump(mode="json")
        row = self._directory_insert(principal, "finding_review_records", resource_id, {
            "inspection_id": str(inspection_id), "media_asset_id": str(asset.id), "payload": data,
            "reviewer_id": str(self._user_id(principal)), "decision": payload.decision,
        }, {"payload": data, "inspection_id": str(inspection_id)})
        return self._finding(row)

    def approve_report(self, principal: Principal, inspection_id: UUID, payload: ReportApprovalRequest, resource_id: UUID) -> ApprovedReport:
        self.assert_inspection_access(principal, inspection_id)
        snapshot, _ = self._client.request("POST", "/rest/v1/rpc/approve_inspector_report", payload={
            "p_report_id": str(resource_id), "p_inspection_id": str(inspection_id), "p_tenant_id": str(self._tenant_id(principal)),
            "p_approver_id": str(self._user_id(principal)), "p_finding_ids": [str(finding_id) for finding_id in payload.finding_ids],
        })
        if isinstance(snapshot, dict) and "error" in snapshot:
            raise HTTPException(409, snapshot["error"])
        return ApprovedReport.model_validate(snapshot)

    def get_approved_report(self, principal: Principal, resource_id: UUID) -> ApprovedReport:
        row = self._directory_get(principal, "approved_report_snapshots", resource_id)
        self.assert_inspection_access(principal, UUID(row["inspection_id"]))
        return ApprovedReport.model_validate(row["snapshot"])

    def list_approved_reports(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[ApprovedReport]:
        self.assert_inspection_access(principal, inspection_id)
        query = {"select": "snapshot", "tenant_id": f"eq.{self._tenant_id(principal)}", "inspection_id": f"eq.{inspection_id}",
                 "order": "id.asc", "limit": str(limit)}
        if after is not None:
            query["id"] = f"gt.{after}"
        rows, _ = self._client.request("GET", "/rest/v1/approved_report_snapshots", query=query)
        return [ApprovedReport.model_validate(row["snapshot"]) for row in rows]

    def _directory_insert(
        self, principal: Principal, table: str, resource_id: UUID,
        payload: dict[str, Any], comparison: dict[str, Any],
    ) -> dict[str, Any]:
        rows, _ = self._client.request(
            "POST", f"/rest/v1/{table}", query={"on_conflict": "id"},
            payload={**payload, "id": str(resource_id), "tenant_id": str(self._tenant_id(principal))},
            headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
        )
        row = rows[0] if rows else self._directory_get(principal, table, resource_id)
        for field, value in comparison.items():
            actual = row.get(field)
            if field == "scheduled_for" and actual is not None and value is not None:
                matches = datetime.fromisoformat(actual) == datetime.fromisoformat(value)
            else:
                matches = actual == value
            if not matches:
                raise HTTPException(409, "Idempotency key was already used with different data.")
        return row

    def create_client(self, principal: Principal, payload: ClientCreate, resource_id: UUID) -> ClientResponse:
        data = payload.model_dump(mode="json")
        return ClientResponse.model_validate(self._directory_insert(principal, "clients", resource_id, data, data))

    def get_client(self, principal: Principal, resource_id: UUID) -> ClientResponse:
        return ClientResponse.model_validate(self._directory_get(principal, "clients", resource_id))

    def list_clients(self, principal: Principal, limit: int, after: UUID | None) -> list[ClientResponse]:
        query = {"select": "id,full_name,email", "tenant_id": f"eq.{self._tenant_id(principal)}",
                 "order": "id.asc", "limit": str(limit)}
        if after is not None:
            query["id"] = f"gt.{after}"
        rows, _ = self._client.request("GET", "/rest/v1/clients", query=query)
        return [ClientResponse.model_validate(row) for row in rows]

    def create_property(self, principal: Principal, payload: PropertyCreate, resource_id: UUID) -> PropertyResponse:
        data = payload.model_dump(mode="json")
        return PropertyResponse.model_validate(self._directory_insert(principal, "properties", resource_id, data, data))

    def get_property(self, principal: Principal, resource_id: UUID) -> PropertyResponse:
        return PropertyResponse.model_validate(self._directory_get(principal, "properties", resource_id))

    def list_properties(self, principal: Principal, limit: int, after: UUID | None, search: str | None) -> list[PropertyResponse]:
        rows, _ = self._client.request("POST", "/rest/v1/rpc/search_inspection_properties", payload={
            "p_tenant_id": str(self._tenant_id(principal)), "p_limit": limit,
            "p_after": str(after) if after is not None else None, "p_search": search,
        })
        return [PropertyResponse.model_validate(row) for row in rows]

    def create_inspection(self, principal: Principal, payload: InspectionCreate, resource_id: UUID) -> InspectionResponse:
        self.get_client(principal, payload.client_id)
        property_record = self.get_property(principal, payload.property_id)
        data = payload.model_dump(mode="json")
        assigned_id = str(self._user_id(principal))
        row = self._directory_insert(principal, "inspections", resource_id, {
            **data, "assigned_inspector_id": assigned_id, "status": "scheduled",
            "service_template_version": "habitat-v1", "property_address": property_record.display_address,
        }, {**data, "assigned_inspector_id": assigned_id})
        return InspectionResponse.model_validate(row)

    def get_inspection(self, principal: Principal, resource_id: UUID) -> InspectionResponse:
        row = self._directory_get(principal, "inspections", resource_id)
        if not principal.roles & {"admin", "owner"} and row["assigned_inspector_id"] != str(self._user_id(principal)):
            raise HTTPException(403, "You are not authorized to access this inspection.")
        return InspectionResponse.model_validate(row)

    def list_inspection_media(self, principal: Principal, inspection_id: UUID, limit: int, after: UUID | None) -> list[MediaSummary]:
        self.assert_inspection_access(principal, inspection_id)
        query = {
            "select": "id,inspection_id,file_name,content_type,content_length,capture_timestamp,requested_category,inspector_note,processing_state:processing_status",
            "tenant_id": f"eq.{self._tenant_id(principal)}", "inspection_id": f"eq.{inspection_id}",
            "order": "id.asc", "limit": str(limit),
        }
        if after is not None:
            query["id"] = f"gt.{after}"
        rows, _ = self._client.request("GET", "/rest/v1/media_assets", query=query)
        return [MediaSummary.model_validate(row) for row in rows]

    def assert_inspection_access(self, principal: Principal, inspection_id: UUID) -> None:
        tenant_id = self._tenant_id(principal)
        row = self._select_one(
            "inspections",
            {
                "select": "id,assigned_inspector_id",
                "id": f"eq.{inspection_id}",
                "tenant_id": f"eq.{tenant_id}",
            },
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found."
            )
        if not principal.roles & {"admin", "owner"} and row["assigned_inspector_id"] != str(
            self._user_id(principal)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to add evidence to this inspection.",
            )

    def _existing_idempotent_resource(
        self, tenant_id: UUID, operation: str, idempotency_key: str
    ) -> UUID | None:
        row = self._select_one(
            "api_idempotency_keys",
            {
                "select": "resource_id",
                "tenant_id": f"eq.{tenant_id}",
                "operation": f"eq.{operation}",
                "idempotency_key": f"eq.{idempotency_key}",
            },
        )
        return UUID(row["resource_id"]) if row else None

    def _record_idempotency(
        self, tenant_id: UUID, operation: str, idempotency_key: str, resource_id: UUID
    ) -> None:
        self._insert(
            "api_idempotency_keys",
            {
                "tenant_id": str(tenant_id),
                "operation": operation,
                "idempotency_key": idempotency_key,
                "resource_id": str(resource_id),
            },
        )

    def create_or_get_upload_intent(
        self,
        principal: Principal,
        inspection_id: UUID,
        request: UploadIntentRequest,
        idempotency_key: str,
    ) -> tuple[MediaAsset, bool]:
        tenant_id = self._tenant_id(principal)
        media_id = uuid5(NAMESPACE_URL, json.dumps(["habitat-upload-v1", str(tenant_id), str(inspection_id), idempotency_key]))
        data = request.model_dump(mode="json")
        data["checksum_sha256"] = request.checksum_sha256.lower()
        rows, _ = self._client.request("POST", "/rest/v1/media_assets", query={"on_conflict": "id"}, payload={
            **data, "id": str(media_id), "tenant_id": str(tenant_id), "inspection_id": str(inspection_id),
            "created_by": str(self._user_id(principal)), "original_object_key": f"tenants/{tenant_id}/inspections/{inspection_id}/original/{media_id}",
        }, headers={"Prefer": "resolution=ignore-duplicates,return=representation"})
        row = rows[0] if rows else self._directory_get(principal, "media_assets", media_id)
        stored = self._media(row)
        if any(getattr(stored, field) != value for field, value in request.model_dump().items() if field != "checksum_sha256") or stored.checksum_sha256 != data["checksum_sha256"]:
            raise HTTPException(409, "Upload retry changed the photo or inspector context.")
        return stored, bool(rows)

    def get_media_for_principal(self, principal: Principal, media_id: UUID) -> MediaAsset:
        tenant_id = self._tenant_id(principal)
        row = self._select_one(
            "media_assets",
            {
                "select": "*",
                "id": f"eq.{media_id}",
                "tenant_id": f"eq.{tenant_id}",
            },
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Media not found."
            )
        asset = self._media(row)
        self.assert_inspection_access(principal, asset.inspection_id)
        return asset

    def get_media_by_id(self, media_id: UUID) -> MediaAsset:
        row = self._select_one("media_assets", {"select": "*", "id": f"eq.{media_id}"})
        if row is None:
            raise SupabaseRequestError("Analysis job references missing media.")
        return self._media(row)

    def complete_upload(
        self, asset: MediaAsset, completion: CompletedUpload, idempotency_key: str
    ) -> tuple[ValidationJob, bool]:
        result, _ = self._client.request("POST", "/rest/v1/rpc/queue_evidence_validation", payload={
            "p_media_id": str(asset.id), "p_tenant_id": asset.tenant_id, "p_etag": completion.storage_etag,
        })
        if not isinstance(result, dict):
            raise SupabaseRequestError("Validation queue did not return a job.")
        row = result["job"]
        asset.processing_state = MediaProcessingState(result["processing_status"])
        return ValidationJob(
            id=UUID(row["id"]),
            tenant_id=row["tenant_id"],
            media_asset_id=UUID(row["media_asset_id"]),
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        ), bool(result["created"])

    def create_analysis_job(
        self,
        asset: MediaAsset,
        request: AnalysisRequest,
        idempotency_key: str,
        model_id: str,
        model_version: str,
    ) -> tuple[AnalysisJob, bool]:
        job_id = uuid5(NAMESPACE_URL, json.dumps(["habitat-analysis-v1", asset.tenant_id, str(asset.id), idempotency_key]))
        category = request.requested_category.value if request.requested_category else None
        payload = {"id": str(job_id), "tenant_id": asset.tenant_id, "inspection_id": str(asset.inspection_id),
                   "media_asset_id": str(asset.id), "requested_category": category, "model_policy_version": "v1",
                   "model_id": model_id, "model_version": model_version}
        rows, _ = self._client.request("POST", "/rest/v1/analysis_jobs", query={"on_conflict": "id"}, payload=payload,
                                      headers={"Prefer": "resolution=ignore-duplicates,return=representation"})
        row = rows[0] if rows else self._select_one("analysis_jobs", {"id": f"eq.{job_id}", "tenant_id": f"eq.{asset.tenant_id}", "select": "*"})
        if row is None:
            raise SupabaseRequestError("Analysis job could not be retrieved after enqueue.")
        if row.get("requested_category") != category:
            raise HTTPException(409, "Analysis retry changed the requested category.")
        return self._analysis_job(row), bool(rows)

    def get_analysis_for_principal(
        self, principal: Principal, analysis_id: UUID
    ) -> AnalysisJob:
        row = self._select_one("analysis_jobs", {"select": "*", "id": f"eq.{analysis_id}"})
        if row is None or row["tenant_id"] != str(self._tenant_id(principal)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found."
            )
        self.get_media_for_principal(principal, UUID(row["media_asset_id"]))
        candidate_row = self._select_one(
            "ai_review_candidates", {"select": "*", "analysis_job_id": f"eq.{analysis_id}"}
        )
        candidate = None
        if candidate_row:
            candidate = ReviewCandidate(
                id=UUID(candidate_row["id"]),
                media_asset_id=UUID(candidate_row["media_asset_id"]),
                model_id=candidate_row["model_id"],
                model_version=candidate_row["model_version"],
                category_candidate=candidate_row["category_candidate"],
                component_candidate=candidate_row["component_candidate"],
                visible_indicator_candidates=candidate_row["visible_indicator_candidates"],
                evidence_marker=candidate_row["evidence_marker"],
                draft_caption=candidate_row["draft_caption"],
                draft_observation=candidate_row["draft_observation"],
                confidence=float(candidate_row["confidence"]),
                uncertainty_reason=candidate_row["uncertainty_reason"],
                requires_human_review=candidate_row["requires_human_review"],
            )
        return self._analysis_job(row, candidate)

    def get_analysis_by_id(self, analysis_id: UUID) -> AnalysisJob:
        row = self._select_one("analysis_jobs", {"select": "*", "id": f"eq.{analysis_id}"})
        if row is None:
            raise SupabaseRequestError("Analysis job not found.")
        return self._analysis_job(row)

    def set_analysis_running(self, job: AnalysisJob) -> None:
        if job.lease_token is not None:
            return
        job.status = AnalysisJobStatus.RUNNING
        self._update(
            "analysis_jobs",
            {"id": f"eq.{job.id}"},
            {"status": AnalysisJobStatus.RUNNING.value, "started_at": utc_now().isoformat()},
        )

    def block_analysis(self, job: AnalysisJob, error_message: str) -> None:
        if job.lease_token is not None:
            self._finish_claimed_job(job, "blocked", error_message, None)
            return
        job.status = AnalysisJobStatus.BLOCKED
        job.error_message = error_message
        self._update(
            "analysis_jobs",
            {"id": f"eq.{job.id}"},
            {
                "status": AnalysisJobStatus.BLOCKED.value,
                "error_code": error_message,
                "completed_at": utc_now().isoformat(),
            },
        )

    def complete_analysis(self, job: AnalysisJob, candidate: ReviewCandidate) -> None:
        if job.lease_token is not None:
            self._finish_claimed_job(job, "succeeded", None, candidate)
            return
        self._insert(
            "ai_review_candidates",
            {
                "id": str(candidate.id),
                "tenant_id": job.tenant_id,
                "analysis_job_id": str(job.id),
                "media_asset_id": str(candidate.media_asset_id),
                "schema_version": "v1",
                "model_id": candidate.model_id,
                "model_version": candidate.model_version,
                "category_candidate": (
                    candidate.category_candidate.value if candidate.category_candidate else None
                ),
                "component_candidate": candidate.component_candidate,
                "visible_indicator_candidates": candidate.visible_indicator_candidates,
                "evidence_marker": (
                    candidate.evidence_marker.model_dump()
                    if candidate.evidence_marker
                    else None
                ),
                "draft_caption": candidate.draft_caption,
                "draft_observation": candidate.draft_observation,
                "confidence": candidate.confidence,
                "uncertainty_reason": candidate.uncertainty_reason,
                "requires_human_review": True,
            },
        )
        self._update(
            "analysis_jobs",
            {"id": f"eq.{job.id}"},
            {
                "status": AnalysisJobStatus.SUCCEEDED.value,
                "completed_at": utc_now().isoformat(),
            },
        )
        job.status = AnalysisJobStatus.SUCCEEDED
        job.review_candidate = candidate

    def append_audit(self, event: AuditEvent) -> None:
        self._insert(
            "audit_events",
            {
                "id": str(event.id),
                "tenant_id": event.tenant_id,
                "actor_id": event.actor_id,
                "correlation_id": event.correlation_id,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "event_type": event.event_type,
                "metadata_redacted": event.metadata,
                "occurred_at": event.occurred_at.isoformat(),
            },
        )

    def mark_media_validated(self, asset: MediaAsset, sanitized_key: str) -> None:
        self._client.request("POST", "/rest/v1/rpc/complete_evidence_validation", payload={
            "p_media_id": str(asset.id), "p_tenant_id": asset.tenant_id, "p_sanitized_key": sanitized_key,
        })
        asset.processing_state = MediaProcessingState.READY_FOR_ANALYSIS
        asset.security_scan_status = "clean"

    def claim_analysis_job(self) -> tuple[AnalysisJob, AnalysisRequest] | None:
        rows, _ = self._client.request("POST", "/rest/v1/rpc/claim_inspection_analysis", payload={})
        if not rows:
            return None
        row = rows[0]
        return self._analysis_job(row), AnalysisRequest(requested_category=row.get("requested_category"))

    def _finish_claimed_job(self, job: AnalysisJob, outcome: str, error: str | None, candidate: ReviewCandidate | None) -> None:
        result, _ = self._client.request("POST", "/rest/v1/rpc/finish_inspection_analysis", payload={
            "p_job_id": str(job.id), "p_lease_token": str(job.lease_token), "p_outcome": outcome,
            "p_error": error, "p_candidate": candidate.model_dump(mode="json") if candidate else None,
        })
        if result is not True:
            raise SupabaseRequestError("Analysis lease expired; stale worker result was not committed.")
        job.status = AnalysisJobStatus(outcome)
        job.error_message = error
        job.review_candidate = candidate

    @staticmethod
    def upload_expiry() -> object:
        return utc_now()
