import pytest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from pydantic import ValidationError

from habitat_api.main import app
from habitat_api.models import ClientCreate, Principal, PropertyResponse
from habitat_api.settings import Settings
from habitat_api.supabase_adapters import SupabaseRepository


HEADERS = {"X-Dev-Tenant-Id": "tenant-a", "X-Dev-User-Id": "inspector-a", "Idempotency-Key": "directory-test-key"}
PROPERTY = {"address_line1": "18 Test Drive", "city": "Brampton", "region": "ON", "postal_code": "L6A 1A1", "country": "CA"}


def create_records(client: TestClient) -> tuple[dict, dict, dict]:
    customer = client.post("/v1/clients", headers=HEADERS, json={"full_name": "Alex Smith"})
    property_record = client.post("/v1/properties", headers=HEADERS, json=PROPERTY)
    assert customer.status_code == property_record.status_code == 201
    inspection = client.post("/v1/inspections", headers=HEADERS, json={
        "client_id": customer.json()["id"], "property_id": property_record.json()["id"],
    })
    assert inspection.status_code == 201
    return customer.json(), property_record.json(), inspection.json()


def test_directory_input_validation() -> None:
    assert ClientCreate(full_name="  Alex Smith  ").full_name == "Alex Smith"
    with pytest.raises(ValidationError):
        ClientCreate(full_name="   ")
    with pytest.raises(ValidationError):
        ClientCreate(full_name="Alex", tenant_id="another-tenant")
    property_record = PropertyResponse(
        address_line1="18 Test Drive", city="Brampton", region="ON",
        postal_code="L6A 1A1", country="CA",
    )
    assert property_record.display_address == "18 Test Drive, Brampton, ON, L6A 1A1, CA"


def test_directory_creation_search_and_upload_connection() -> None:
    with TestClient(app) as client:
        customer, property_record, inspection = create_records(client)
        inspection_id = inspection["id"]
        assert client.get(f"/v1/inspections/{inspection_id}", headers=HEADERS).json() == inspection
        for path in (f"/v1/clients/{customer['id']}/inspections", f"/v1/properties/{property_record['id']}/inspections"):
            assert client.get(path, headers=HEADERS).json() == [inspection]
        assert client.get("/v1/properties?search=brampton", headers=HEADERS).json() == [property_record]
        assert client.get("/v1/properties?search=missing", headers=HEADERS).json() == []
        assert client.get(f"/v1/inspections?client_id={customer['id']}", headers=HEADERS).json() == [inspection]
        intent = client.post(f"/v1/inspections/{inspection_id}/media/upload-intents", headers=HEADERS, json={
            "file_name": "roof.jpg", "content_type": "image/jpeg", "content_length": 100,
            "checksum_sha256": "a" * 64, "capture_timestamp": datetime.now(timezone.utc).isoformat(),
        })
        assert intent.status_code == 201
        media = client.get(f"/v1/inspections/{inspection_id}/media", headers=HEADERS).json()
        assert media[0]["id"] == intent.json()["media_asset_id"]
        assert "object_key" not in media[0]


def test_tenant_and_assignment_boundaries() -> None:
    with TestClient(app) as client:
        customer, property_record, inspection = create_records(client)
        outsider = {**HEADERS, "X-Dev-Tenant-Id": "tenant-b", "X-Dev-Roles": "admin"}
        for path in (f"/v1/clients/{customer['id']}", f"/v1/properties/{property_record['id']}", f"/v1/inspections/{inspection['id']}"):
            assert client.get(path, headers=outsider).status_code == 404
        assert client.get("/v1/clients", headers=outsider).json() == []
        assert client.get("/v1/properties?search=Test", headers=outsider).json() == []
        assert client.post("/v1/inspections", headers=outsider, json={
            "client_id": customer["id"], "property_id": property_record["id"],
        }).status_code == 404
        unassigned = {**HEADERS, "X-Dev-User-Id": "inspector-b"}
        assert client.get("/v1/inspections", headers=unassigned).json() == []
        assert client.get(f"/v1/inspections/{inspection['id']}/media", headers=unassigned).status_code == 403
        owner = {**unassigned, "X-Dev-Roles": "owner"}
        assert client.get(f"/v1/inspections/{inspection['id']}", headers=owner).status_code == 200
        reviewer = {**HEADERS, "X-Dev-Roles": "reviewer"}
        assert client.post("/v1/clients", headers=reviewer, json={"full_name": "Blocked"}).status_code == 403
        assert client.get("/v1/clients").status_code == 401


def test_pagination_validation_and_retries() -> None:
    with TestClient(app) as client:
        first = client.post("/v1/clients", headers=HEADERS, json={"full_name": "Alex"})
        repeated = client.post("/v1/clients", headers=HEADERS, json={"full_name": "Alex"})
        assert first.json() == repeated.json()
        assert client.post("/v1/clients", headers=HEADERS, json={"full_name": "Changed"}).status_code == 409
        for index in range(3):
            assert client.post("/v1/clients", headers={**HEADERS, "Idempotency-Key": f"another-key-{index}"}, json={"full_name": f"Client {index}"}).status_code == 201
        page1 = client.get("/v1/clients?limit=2", headers=HEADERS).json()
        page2 = client.get(f"/v1/clients?limit=2&after={page1[-1]['id']}", headers=HEADERS).json()
        assert len({row["id"] for row in page1 + page2}) == 4
        for query in ("limit=0", "limit=101", "after=invalid"):
            assert client.get(f"/v1/clients?{query}", headers=HEADERS).status_code == 422
        assert client.get("/v1/properties?search=%20%20%20", headers=HEADERS).status_code == 422
        assert client.post("/v1/inspections", headers=HEADERS, json={"client_id": str(uuid4()), "property_id": str(uuid4())}).status_code == 404


def test_supabase_directory_rows_and_bounded_queries() -> None:
    tenant_id, user_id, client_id, property_id = (uuid4() for _ in range(4))
    principal = Principal(tenant_id=str(tenant_id), user_id=str(user_id))
    repository = SupabaseRepository(Settings(
        supabase_url="https://database.example", supabase_service_role_key="test-only-key",
    ))
    transport = Mock()
    repository._client = transport
    transport.request.return_value = ([{
        "id": str(client_id), "tenant_id": str(tenant_id), "full_name": "Alex",
        "email": None, "created_at": "2026-11-14T12:00:00+00:00",
    }], {})
    row = repository.create_client(principal, ClientCreate(full_name="Alex"), client_id)
    assert row.id == client_id
    assert "tenant_id" not in row.model_dump()
    assert transport.request.call_args.kwargs["payload"]["tenant_id"] == str(tenant_id)
    transport.request.return_value = ([], {})
    assert repository.list_inspections(principal, 10, client_id, client_id, property_id) == []
    query = transport.request.call_args.kwargs["query"]
    assert query["limit"] == "10"
    assert query["tenant_id"] == f"eq.{tenant_id}"
    assert query["assigned_inspector_id"] == f"eq.{user_id}"
    assert query["id"] == f"gt.{client_id}"
    assert query["client_id"] == f"eq.{client_id}"
    assert query["property_id"] == f"eq.{property_id}"
    assert repository.list_properties(principal, 10, None, "100%_Main*") == []
    assert transport.request.call_args.args == ("POST", "/rest/v1/rpc/search_inspection_properties")
    assert transport.request.call_args.kwargs["payload"]["p_search"] == "100%_Main*"


def test_concurrent_retries_create_one_record() -> None:
    with TestClient(app) as client:
        def create_customer(_: int) -> dict:
            response = client.post("/v1/clients", headers=HEADERS, json={"full_name": "Concurrent client"})
            assert response.status_code == 201
            return response.json()

        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(create_customer, range(16)))
        assert len({row["id"] for row in responses}) == 1
        assert len(client.get("/v1/clients", headers=HEADERS).json()) == 1


def test_property_and_inspection_retries_preserve_history() -> None:
    with TestClient(app) as client:
        customer, property_record, inspection = create_records(client)
        assert client.post("/v1/properties", headers=HEADERS, json=PROPERTY).json() == property_record
        assert client.post("/v1/properties", headers=HEADERS, json={**PROPERTY, "city": "Changed"}).status_code == 409
        payload = {"client_id": customer["id"], "property_id": property_record["id"]}
        assert client.post("/v1/inspections", headers=HEADERS, json=payload).json() == inspection
        assert client.post("/v1/inspections", headers=HEADERS, json={**payload, "scheduled_for": "2026-11-15T12:00:00Z"}).status_code == 409
        second_customer = client.post("/v1/clients", headers={**HEADERS, "Idempotency-Key": "second-client-key"}, json={"full_name": "New owner"}).json()
        second_inspection = client.post("/v1/inspections", headers={**HEADERS, "Idempotency-Key": "second-inspection-key"}, json={**payload, "client_id": second_customer["id"]})
        assert second_inspection.status_code == 201
        assert len(client.get(f"/v1/properties/{property_record['id']}/inspections", headers=HEADERS).json()) == 2
        assert client.get(f"/v1/clients/{customer['id']}/inspections", headers=HEADERS).json() == [inspection]


def test_existing_mobile_demo_is_in_directory() -> None:
    headers = {"X-Dev-Tenant-Id": "demo-tenant", "X-Dev-User-Id": "demo-inspector"}
    with TestClient(app) as client:
        fixture = client.get("/development/demo-inspection", headers=headers).json()
        inspection_id = fixture["inspection_id"]
        inspection = client.get(f"/v1/inspections/{inspection_id}", headers=headers)
        assert inspection.status_code == 200
        assert inspection.json()["client_id"] is not None
        assert inspection.json()["property_id"] is not None
        assert client.get(f"/v1/inspections/{inspection_id}/media", headers=headers).json() == []