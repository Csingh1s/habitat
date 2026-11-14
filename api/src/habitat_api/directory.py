from __future__ import annotations

import json
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query

from .dependencies import get_principal, get_repository, require_idempotency_key
from .models import (
    ClientCreate, ClientResponse, InspectionCreate, InspectionResponse,
    MediaSummary, Principal, PropertyCreate, PropertyResponse,
)
from .repositories import Repository


router = APIRouter(prefix="/v1", tags=["Inspection directory"])
PageLimit = Annotated[int, Query(ge=1, le=100)]


def creation_id(principal: Principal, operation: str, key: str) -> UUID:
    if not principal.roles & {"owner", "admin", "inspector", "operations"}:
        raise HTTPException(403, "Your role cannot create inspection records.")
    return uuid5(NAMESPACE_URL, json.dumps([
        "habitat-directory-v1", principal.tenant_id, principal.user_id, operation, key,
    ]))


@router.post("/clients", response_model=ClientResponse, status_code=201)
def create_client(
    payload: ClientCreate,
    principal: Principal = Depends(get_principal),
    key: str = Depends(require_idempotency_key),
    repository: Repository = Depends(get_repository),
) -> ClientResponse:
    return repository.create_client(principal, payload, creation_id(principal, "client", key))


@router.get("/clients", response_model=list[ClientResponse])
def list_clients(
    limit: PageLimit = 50, after: UUID | None = None,
    principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> list[ClientResponse]:
    return repository.list_clients(principal, limit, after)


@router.get("/clients/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: UUID, principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> ClientResponse:
    return repository.get_client(principal, client_id)


@router.post("/properties", response_model=PropertyResponse, status_code=201)
def create_property(
    payload: PropertyCreate,
    principal: Principal = Depends(get_principal),
    key: str = Depends(require_idempotency_key),
    repository: Repository = Depends(get_repository),
) -> PropertyResponse:
    return repository.create_property(principal, payload, creation_id(principal, "property", key))


@router.get("/properties", response_model=list[PropertyResponse])
def list_properties(
    limit: PageLimit = 50, after: UUID | None = None,
    search: Annotated[str | None, Query(min_length=3, max_length=200)] = None,
    principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> list[PropertyResponse]:
    if search is not None:
        search = search.strip()
        if len(search) < 3:
            raise HTTPException(422, "Address search needs at least three non-space characters.")
    return repository.list_properties(principal, limit, after, search)


@router.get("/properties/{property_id}", response_model=PropertyResponse)
def get_property(
    property_id: UUID, principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> PropertyResponse:
    return repository.get_property(principal, property_id)


@router.post("/inspections", response_model=InspectionResponse, status_code=201)
def create_inspection(
    payload: InspectionCreate,
    principal: Principal = Depends(get_principal),
    key: str = Depends(require_idempotency_key),
    repository: Repository = Depends(get_repository),
) -> InspectionResponse:
    return repository.create_inspection(principal, payload, creation_id(principal, "inspection", key))


@router.get("/inspections/{inspection_id}", response_model=InspectionResponse)
def get_inspection(
    inspection_id: UUID, principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> InspectionResponse:
    return repository.get_inspection(principal, inspection_id)


@router.get("/clients/{client_id}/inspections", response_model=list[InspectionResponse])
def client_inspections(
    client_id: UUID, limit: PageLimit = 50, after: UUID | None = None,
    principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> list[InspectionResponse]:
    repository.get_client(principal, client_id)
    return repository.list_inspections(principal, limit, after, client_id=client_id)


@router.get("/properties/{property_id}/inspections", response_model=list[InspectionResponse])
def property_inspections(
    property_id: UUID, limit: PageLimit = 50, after: UUID | None = None,
    principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> list[InspectionResponse]:
    repository.get_property(principal, property_id)
    return repository.list_inspections(principal, limit, after, property_id=property_id)


@router.get("/inspections/{inspection_id}/media", response_model=list[MediaSummary])
def inspection_media(
    inspection_id: UUID, limit: PageLimit = 50, after: UUID | None = None,
    principal: Principal = Depends(get_principal),
    repository: Repository = Depends(get_repository),
) -> list[MediaSummary]:
    return repository.list_inspection_media(principal, inspection_id, limit, after)