from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEVELOPMENT_DEMO_INSPECTION_ID = "d7ed3ba7-bf5d-4c26-a4aa-4b0ef08d4489"
DEVELOPMENT_DEMO_TENANT_ID = "demo-tenant"
DEVELOPMENT_DEMO_USER_ID = "demo-inspector"


class Settings(BaseSettings):
    app_env: str = "development"
    development_login_email: str = "inspector@example.com"
    development_login_password: SecretStr = SecretStr("HabitatDemo123!")
    development_admin_email: str = "admin@example.com"
    development_admin_password: SecretStr = SecretStr("HabitatAdmin12345")
    oidc_issuer_url: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    qwen_inference_url: str | None = None
    qwen_inference_api_key: str | None = None
    qwen_model_id: str = "Qwen/Qwen2.5-VL-3B-Instruct"
    qwen_model_version: str = "deployment-managed"
    inference_provider: Literal["self_hosted", "qwen_cloud"] = "qwen_cloud"
    alibaba_model_studio_host: str | None = None
    qwen_cloud_inference_url: str | None = None
    qwen_cloud_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("QWEN_CLOUD_API_KEY", "DASHSCOPE_API_KEY"),
    )
    qwen_cloud_model_id: str = "qwen3.7-flash"
    qwen_cloud_model_version: str = "qwen-cloud-managed"
    alibaba_speech_model_id: str = "qwen-audio-3.1-asr-flash"
    alibaba_speech_file_model_id: str = "qwen-audio-3.1-asr-flash-filetrans"
    enable_remote_inference: bool = False
    persistence_backend: Literal["memory", "supabase"] = "memory"
    inference_execution_mode: Literal["background", "worker"] = "background"
    clamav_host: str | None = None
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    deployed_cors_origins: tuple[str, ...] = ()
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "inspection-evidence"
    development_upload_directory: Path = Path(".data") / "uploads"
    development_cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:8081",
        "http://localhost:8081",
        "http://127.0.0.1:8083",
        "http://localhost:8083",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("alibaba_model_studio_host")
    @classmethod
    def validate_alibaba_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not (parsed.hostname or "").endswith(".maas.aliyuncs.com")
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or parsed.port not in {None, 443}
        ):
            raise ValueError("ALIBABA_MODEL_STUDIO_HOST must be the HTTPS workspace host from Model Studio, without an API path.")
        return value.rstrip("/")

    @property
    def development_identity_enabled(self) -> bool:
        return self.app_env == "development"

    @property
    def remote_inference_allowed(self) -> bool:
        """Remote GPU calls are a production-only, explicit cost-bearing operation."""
        return self.app_env in {"staging", "production"} and self.enable_remote_inference

    def validate_security_configuration(self) -> None:
        if not self.development_identity_enabled and not (
            self.oidc_issuer_url and self.oidc_audience and self.oidc_jwks_url
        ):
            raise RuntimeError(
                "Production requires OIDC_ISSUER_URL, OIDC_AUDIENCE, and OIDC_JWKS_URL; "
                "development identity headers are disabled outside APP_ENV=development."
            )
        if self.persistence_backend == "supabase" and not (
            self.supabase_url and self.supabase_service_role_key
        ):
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required when "
                "PERSISTENCE_BACKEND=supabase."
            )
        if not self.development_identity_enabled and (
            self.persistence_backend != "supabase" or self.inference_execution_mode != "worker"
        ):
            raise RuntimeError("Deployed services require PERSISTENCE_BACKEND=supabase and INFERENCE_EXECUTION_MODE=worker.")
        if not self.development_identity_enabled and not self.clamav_host:
            raise RuntimeError("Deployed evidence validation requires a private CLAMAV_HOST.")
        if any(not origin.startswith("https://") for origin in self.deployed_cors_origins):
            raise RuntimeError("Deployed browser origins must use HTTPS.")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_security_configuration()
    return settings
