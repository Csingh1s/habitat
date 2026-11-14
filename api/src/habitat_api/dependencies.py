from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import get_oidc_verifier
from .models import AuthenticatedIdentity, Principal
from .repositories import InMemoryRepository, ObjectStore, Repository
from .settings import get_settings


bearer_scheme = HTTPBearer(auto_error=False)


def require_idempotency_key(
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
) -> str:
    return idempotency_key


def correlation_id(
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
) -> str:
    from uuid import uuid4

    return x_correlation_id or str(uuid4())


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_dev_tenant_id: str | None = Header(None, alias="X-Dev-Tenant-Id"),
    x_dev_user_id: str | None = Header(None, alias="X-Dev-User-Id"),
    x_dev_roles: str | None = Header(None, alias="X-Dev-Roles"),
) -> Principal:
    settings = get_settings()
    if settings.development_identity_enabled:
        if not x_dev_tenant_id or not x_dev_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Development requests require X-Dev-Tenant-Id and X-Dev-User-Id.",
            )
        roles = frozenset(
            role.strip() for role in (x_dev_roles or "inspector").split(",") if role.strip()
        )
        return Principal(tenant_id=x_dev_tenant_id, user_id=x_dev_user_id, roles=roles)
    identity = get_authenticated_identity(request, credentials)
    return get_repository(request).get_principal_for_identity(identity)


def get_authenticated_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedIdentity:
    if get_settings().development_identity_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity onboarding is not available in development.",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A bearer access token is required.",
        )
    try:
        return get_oidc_verifier(get_settings()).verify(credentials.credentials)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The access token is invalid or expired.",
        ) from None


def get_repository(request: Request) -> Repository:
    return request.app.state.repository


def get_object_store(request: Request) -> ObjectStore:
    return request.app.state.object_store


def seed_inspection_access(
    repository: InMemoryRepository, tenant_id: str, inspection_id: UUID, user_id: str
) -> None:
    """Temporary development seam; replace with inspection/work-order repository checks."""
    repository.grant_inspection_access(tenant_id, inspection_id, user_id)
