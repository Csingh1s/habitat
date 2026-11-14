from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from habitat_api.main import app


HEADERS = {"X-Dev-Tenant-Id": "demo-tenant", "X-Dev-User-Id": "demo-inspector", "Idempotency-Key": "review-test-key"}


def test_inspector_approval_is_required_and_tenant_scoped() -> None:
    with TestClient(app) as client:
        inspection_id = client.get("/development/demo-inspection", headers=HEADERS).json()["inspection_id"]
        image_buffer = BytesIO()
        Image.new("RGB", (80, 60), "green").save(image_buffer, format="JPEG")
        content = image_buffer.getvalue()
        checksum = sha256(content).hexdigest()
        intent = client.post(f"/v1/inspections/{inspection_id}/media/upload-intents", headers=HEADERS, json={
            "file_name": "roof.jpg", "content_type": "image/jpeg", "content_length": len(content),
            "checksum_sha256": checksum, "capture_timestamp": datetime.now(timezone.utc).isoformat(), "inspector_note": "Original field note",
        }).json()
        media = intent["media_asset_id"]
        assert client.put(intent["upload_url"].split("localhost:8000")[1], content=content, headers={"Content-Type": "application/octet-stream", "X-Checksum-Sha256": checksum}).status_code == 204
        assert client.post(f"/v1/media/{media}/complete", headers=HEADERS, json={"checksum_sha256": checksum, "storage_etag": "development-etag"}).status_code == 200
        assert client.get(f"/v1/inspections/{inspection_id}/media", headers=HEADERS).json()[0]["inspector_note"] == "Original field note"
        payload = {"media_asset_id": media, "decision": "accepted", "category": "roofing", "location": "Rear slope",
                   "caption": "Roof surface", "observation": "Inspector verified a visible condition."}
        finding = client.post(f"/v1/inspections/{inspection_id}/findings", headers=HEADERS, json=payload)
        assert finding.status_code == 201
        finding_id = finding.json()["id"]
        assert client.post(f"/v1/inspections/{inspection_id}/findings", headers=HEADERS, json=payload).json() == finding.json()
        approval = {"finding_ids": [finding_id], "inspector_approved": True}
        assert client.post(f"/v1/inspections/{inspection_id}/reports", headers=HEADERS, json={**approval, "inspector_approved": False}).status_code == 422
        assert client.post(f"/v1/inspections/{inspection_id}/reports", headers={**HEADERS, "X-Dev-Roles": "operations"}, json=approval).status_code == 403
        report = client.post(f"/v1/inspections/{inspection_id}/reports", headers=HEADERS, json=approval)
        assert report.status_code == 201
        assert report.json()["findings"][0]["observation"] == payload["observation"]
        assert client.get(f"/v1/reports/{report.json()['id']}", headers={**HEADERS, "X-Dev-Tenant-Id": "foreign"}).status_code == 404
        rejected = client.post(f"/v1/inspections/{inspection_id}/findings", headers={**HEADERS, "Idempotency-Key": "rejected-review-key"}, json={**payload, "decision": "rejected"}).json()
        assert client.post(f"/v1/inspections/{inspection_id}/reports", headers={**HEADERS, "Idempotency-Key": "another-report-key"}, json={**approval, "finding_ids": [rejected['id']]}).status_code == 409
        assert client.post(f"/v1/inspections/{inspection_id}/reports", headers={**HEADERS, "Idempotency-Key": "stale-approved-finding-key"}, json=approval).status_code == 409
        assert client.get(f"/v1/reports/{report.json()['id']}", headers=HEADERS).json()["findings"][0]["decision"] == "accepted"
        assert client.post(f"/v1/inspections/{inspection_id}/findings", headers={**HEADERS, "Idempotency-Key": "unknown-analysis-key"}, json={**payload, "analysis_id": str(uuid4())}).status_code == 404


def test_pdf_contains_reviewed_words_and_integrity_checked_photo() -> None:
    with TestClient(app) as client:
        inspection_id = client.get("/development/demo-inspection", headers=HEADERS).json()["inspection_id"]
        image_buffer = BytesIO()
        Image.new("RGB", (80, 60), "green").save(image_buffer, format="JPEG")
        content = image_buffer.getvalue()
        checksum = sha256(content).hexdigest()
        intent = client.post(f"/v1/inspections/{inspection_id}/media/upload-intents", headers=HEADERS, json={
            "file_name": "original.jpg", "content_type": "image/jpeg", "content_length": len(content),
            "checksum_sha256": checksum, "capture_timestamp": datetime.now(timezone.utc).isoformat(),
        }).json()
        media_id = intent["media_asset_id"]
        object_path = intent["upload_url"].split("localhost:8000")[1]
        assert client.put(object_path, content=content, headers={"Content-Type": "application/octet-stream", "X-Checksum-Sha256": checksum}).status_code == 204
        assert client.post(f"/v1/media/{media_id}/complete", headers=HEADERS, json={"checksum_sha256": checksum, "storage_etag": "development-etag"}).status_code == 200
        assert client.get(f"/v1/media/{media_id}/content", headers=HEADERS).content == content
        retried_intent = client.post(f"/v1/inspections/{inspection_id}/media/upload-intents", headers=HEADERS, json={
            "file_name": "original.jpg", "content_type": "image/jpeg", "content_length": len(content),
            "checksum_sha256": checksum, "capture_timestamp": app.state.repository.media[UUID(media_id)].capture_timestamp.isoformat(),
        })
        assert retried_intent.status_code == 201
        assert retried_intent.json()["storage_etag"] == "development-etag"
        finding = client.post(f"/v1/inspections/{inspection_id}/findings", headers=HEADERS, json={
            "media_asset_id": media_id, "decision": "accepted", "category": "roofing", "location": "Rear slope",
            "caption": "Roof surface reviewed", "observation": "Inspector verified condition <not AI-approved>.",
        }).json()
        report = client.post(f"/v1/inspections/{inspection_id}/reports", headers=HEADERS, json={"finding_ids": [finding["id"]], "inspector_approved": True}).json()
        pdf = client.get(f"/v1/reports/{report['id']}/pdf", headers=HEADERS)
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        reader = PdfReader(BytesIO(pdf.content))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "Photo 01: Roof surface reviewed" in text
        assert "Inspector verified condition <not AI-approved>." in text
        assert sum(len(page.images) for page in reader.pages) == 1
        assert client.get(f"/v1/reports/{report['id']}/pdf", headers={**HEADERS, "X-Dev-Tenant-Id": "foreign"}).status_code == 404