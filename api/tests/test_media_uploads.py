from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient

from habitat_api.dependencies import seed_inspection_access
from habitat_api.main import app


HEADERS = {
    "X-Dev-Tenant-Id": "tenant-a",
    "X-Dev-User-Id": "inspector-a",
    "Idempotency-Key": "a-unique-request-key",
}
CHECKSUM = "a" * 64


def test_upload_intent_is_idempotent_and_scoped() -> None:
    inspection_id = uuid4()
    with TestClient(app) as client:
        seed_inspection_access(
            app.state.repository, "tenant-a", inspection_id, "inspector-a"
        )
        payload = {
            "file_name": "roof.jpg",
            "content_type": "image/jpeg",
            "content_length": 1024,
            "checksum_sha256": CHECKSUM,
            "capture_timestamp": datetime.now(timezone.utc).isoformat(),
            "requested_category": "roofing",
        }
        first = client.post(
            f"/v1/inspections/{inspection_id}/media/upload-intents",
            headers=HEADERS,
            json=payload,
        )
        second = client.post(
            f"/v1/inspections/{inspection_id}/media/upload-intents",
            headers=HEADERS,
            json=payload,
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["media_asset_id"] == second.json()["media_asset_id"]


def test_development_demo_inspection_is_limited_to_demo_principal() -> None:
    demo_headers = {
        "X-Dev-Tenant-Id": "demo-tenant",
        "X-Dev-User-Id": "demo-inspector",
    }
    with TestClient(app) as client:
        allowed = client.get("/development/demo-inspection", headers=demo_headers)
        denied = client.get(
            "/development/demo-inspection",
            headers={
                **demo_headers,
                "X-Dev-Tenant-Id": "another-tenant",
                "X-Dev-User-Id": "another-inspector",
            },
        )

    assert allowed.status_code == 200
    assert allowed.json()["environment"] == "development"
    assert denied.status_code == 403


def test_completion_requires_storage_confirmation() -> None:
    inspection_id = uuid4()
    content = b"not-an-image-in-development-emulator"
    checksum = sha256(content).hexdigest()
    with TestClient(app) as client:
        seed_inspection_access(
            app.state.repository, "tenant-a", inspection_id, "inspector-a"
        )
        intent = client.post(
            f"/v1/inspections/{inspection_id}/media/upload-intents",
            headers=HEADERS,
            json={
                "file_name": "panel.jpg",
                "content_type": "image/jpeg",
                "content_length": 1024,
                "checksum_sha256": checksum,
                "capture_timestamp": datetime.now(timezone.utc).isoformat(),
                "requested_category": "electrical",
            },
        ).json()
        missing = client.post(
            f"/v1/media/{intent['media_asset_id']}/complete",
            headers=HEADERS,
            json={"storage_etag": "etag-1", "checksum_sha256": checksum},
        )
        client.put(
            intent["upload_url"],
            headers={"X-Checksum-Sha256": checksum, "X-Storage-ETag": "etag-1"},
            content=content,
        )
        completed = client.post(
            f"/v1/media/{intent['media_asset_id']}/complete",
            headers=HEADERS,
            json={"storage_etag": "etag-1", "checksum_sha256": checksum},
        )

    assert missing.status_code == 409
    assert completed.status_code == 200
    assert completed.json()["processing_state"] == "validation_queued"


def test_development_upload_rejects_a_mismatched_content_checksum() -> None:
    inspection_id = uuid4()
    with TestClient(app) as client:
        seed_inspection_access(
            app.state.repository, "tenant-a", inspection_id, "inspector-a"
        )
        intent = client.post(
            f"/v1/inspections/{inspection_id}/media/upload-intents",
            headers=HEADERS,
            json={
                "file_name": "exterior.jpg",
                "content_type": "image/jpeg",
                "content_length": 1024,
                "checksum_sha256": CHECKSUM,
                "capture_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ).json()
        response = client.put(
            intent["upload_url"],
            headers={"X-Checksum-Sha256": CHECKSUM, "X-Storage-ETag": "etag-1"},
            content=b"content-that-does-not-match-declared-checksum",
        )

    assert response.status_code == 422


def test_other_tenant_cannot_complete_media_upload() -> None:
    inspection_id = uuid4()
    with TestClient(app) as client:
        seed_inspection_access(
            app.state.repository, "tenant-a", inspection_id, "inspector-a"
        )
        intent = client.post(
            f"/v1/inspections/{inspection_id}/media/upload-intents",
            headers=HEADERS,
            json={
                "file_name": "exterior.jpg",
                "content_type": "image/jpeg",
                "content_length": 1024,
                "checksum_sha256": CHECKSUM,
                "capture_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ).json()
        other_tenant_headers = {
            "X-Dev-Tenant-Id": "tenant-b",
            "X-Dev-User-Id": "inspector-b",
            "Idempotency-Key": "a-different-request-key",
        }
        response = client.post(
            f"/v1/media/{intent['media_asset_id']}/complete",
            headers=other_tenant_headers,
            json={"storage_etag": "etag-1", "checksum_sha256": CHECKSUM},
        )

    assert response.status_code == 404


def test_unconfigured_qwen_job_is_explicitly_blocked() -> None:
    inspection_id = uuid4()
    content = b"development-test-image"
    checksum = sha256(content).hexdigest()
    with TestClient(app) as client:
        seed_inspection_access(
            app.state.repository, "tenant-a", inspection_id, "inspector-a"
        )
        intent = client.post(
            f"/v1/inspections/{inspection_id}/media/upload-intents",
            headers=HEADERS,
            json={
                "file_name": "roof.jpg",
                "content_type": "image/jpeg",
                "content_length": 1024,
                "checksum_sha256": checksum,
                "capture_timestamp": datetime.now(timezone.utc).isoformat(),
                "requested_category": "roofing",
            },
        ).json()
        client.put(
            intent["upload_url"],
            headers={"X-Checksum-Sha256": checksum, "X-Storage-ETag": "etag-1"},
            content=content,
        )
        headers = {**HEADERS, "Idempotency-Key": "complete-analysis-test-key"}
        client.post(
            f"/v1/media/{intent['media_asset_id']}/complete",
            headers=headers,
            json={"storage_etag": "etag-1", "checksum_sha256": checksum},
        )
        analysis = client.post(
            f"/v1/media/{intent['media_asset_id']}/analyses",
            headers={**HEADERS, "Idempotency-Key": "analysis-request-test-key"},
            json={"requested_category": "roofing"},
        )

    assert analysis.status_code == 202
    status_response = client.get(
        f"/v1/analyses/{analysis.json()['id']}",
        headers=HEADERS,
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "blocked"
    assert "Local development never calls GPU endpoints" in status_response.json()["error_message"]
