import pytest

from habitat_api.auth import OidcTokenVerifier
from habitat_api.settings import Settings


def test_staging_requires_entra_jwks_configuration() -> None:
    with pytest.raises(RuntimeError, match="OIDC_JWKS_URL"):
        Settings(
            app_env="staging",
            oidc_issuer_url="https://issuer.example",
            oidc_audience="api://habitat-api",
        ).validate_security_configuration()


def test_entra_verifier_uses_explicit_issuer_audience_and_jwks() -> None:
    settings = Settings(
        app_env="staging",
        oidc_issuer_url="https://issuer.example",
        oidc_audience="api://habitat-api",
        oidc_jwks_url="https://issuer.example/discovery/v2.0/keys",
    )

    verifier = OidcTokenVerifier(settings)

    assert verifier is not None
