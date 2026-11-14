from __future__ import annotations

from uuid import UUID

import jwt
from jwt import PyJWKClient

from .models import AuthenticatedIdentity
from .settings import Settings


class OidcTokenVerifier:
    """Validates Entra External ID access tokens against its published JWKS."""

    def __init__(self, settings: Settings) -> None:
        if not settings.oidc_issuer_url or not settings.oidc_audience or not settings.oidc_jwks_url:
            raise ValueError("OIDC issuer, audience, and JWKS URL are required.")
        self._issuer = settings.oidc_issuer_url
        self._audience = settings.oidc_audience
        self._jwks_client = PyJWKClient(settings.oidc_jwks_url, cache_keys=True)

    def verify(self, token: str) -> AuthenticatedIdentity:
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        subject = claims.get("oid") or claims["sub"]
        return AuthenticatedIdentity(
            issuer=claims["iss"],
            subject=str(subject),
            user_id=UUID(str(subject)),
            email=claims.get("email") or claims.get("preferred_username"),
            display_name=claims.get("name"),
        )


def get_oidc_verifier(settings: Settings) -> OidcTokenVerifier:
    return OidcTokenVerifier(settings)
