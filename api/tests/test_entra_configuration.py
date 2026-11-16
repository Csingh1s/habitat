import pytest
from fastapi.testclient import TestClient

from habitat_api.auth import OidcTokenVerifier
from habitat_api.main import app
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


def test_local_login_checks_credentials_and_does_not_return_password(monkeypatch) -> None:
    settings = Settings(_env_file=None, app_env="development", development_login_email="inspector@example.com", development_login_password="HabitatDemo123!")
    monkeypatch.setattr("habitat_api.main.get_settings", lambda: settings)
    with TestClient(app) as client:
        result = client.post("/development/login", json={"email": "Inspector@Example.com", "password": "HabitatDemo123!"})
        assert result.status_code == 200
        assert result.json() == {
            "authenticated": True,
            "email": "inspector@example.com",
            "tenant_id": "demo-tenant",
            "user_id": "demo-inspector",
            "role": "inspector",
        }
        assert result.headers["Cache-Control"] == "no-store"
        assert "HabitatDemo123!" not in result.text
        for email, password in [("other@example.com", "HabitatDemo123!"), ("inspector@example.com", "wrong-password"), ("inspector@example.com", "\u00e9wrong-password")]:
            rejected = client.post("/development/login", json={"email": email, "password": password})
            assert rejected.status_code == 401
            assert rejected.json()["detail"] == "Email or password is incorrect."


def test_local_admin_login_returns_admin_identity_and_can_list_company_inspections(monkeypatch) -> None:
    settings = Settings(_env_file=None, app_env="development")
    monkeypatch.setattr("habitat_api.main.get_settings", lambda: settings)
    with TestClient(app) as client:
        result = client.post("/development/login", json={"email": "admin@example.com", "password": "HabitatAdmin12345"})
        assert result.status_code == 200
        identity = result.json()
        assert identity == {
            "authenticated": True,
            "email": "admin@example.com",
            "tenant_id": "demo-tenant",
            "user_id": "demo-admin",
            "role": "admin",
        }
        inspections = client.get("/v1/inspections", headers={
            "X-Dev-Tenant-Id": identity["tenant_id"],
            "X-Dev-User-Id": identity["user_id"],
            "X-Dev-Roles": identity["role"],
        })
        assert inspections.status_code == 200
        assert len(inspections.json()) >= 1


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_local_login_is_unavailable_outside_development(monkeypatch, environment) -> None:
    settings = Settings(_env_file=None, app_env="development")
    monkeypatch.setattr("habitat_api.main.get_settings", lambda: settings)
    with TestClient(app) as client:
        settings.app_env = environment
        result = client.post("/development/login", json={"email": "inspector@example.com", "password": "HabitatDemo123!"})
        assert result.status_code == 404
