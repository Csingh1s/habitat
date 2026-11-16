import pytest

from habitat_api.inference import QwenInferenceClient
from habitat_api.settings import Settings


def test_local_development_never_enables_remote_qwen_calls() -> None:
    client = QwenInferenceClient(
        Settings(
            app_env="development",
            inference_provider="self_hosted",
            enable_remote_inference=True,
            qwen_inference_url="https://private-gpu.example/v1/chat/completions",
            qwen_inference_api_key="test-key",
        )
    )

    assert not client.configured
    assert "Local development never calls GPU endpoints" in client.unavailable_reason


def test_production_requires_explicit_remote_inference_opt_in() -> None:
    settings = Settings(
        app_env="production",
        inference_provider="self_hosted",
        oidc_issuer_url="https://issuer.example",
        oidc_audience="habitat-api",
        qwen_inference_url="https://private-gpu.example/v1/chat/completions",
        qwen_inference_api_key="test-key",
    )

    assert not QwenInferenceClient(settings).configured


def test_production_can_enable_configured_remote_inference() -> None:
    client = QwenInferenceClient(
        Settings(
            app_env="production",
            inference_provider="self_hosted",
            oidc_issuer_url="https://issuer.example",
            oidc_audience="habitat-api",
            enable_remote_inference=True,
            qwen_inference_url="https://private-gpu.example/v1/chat/completions",
            qwen_inference_api_key="test-key",
        )
    )

    assert client.configured


def test_qwen_cloud_uses_its_managed_endpoint_and_model() -> None:
    client = QwenInferenceClient(
        Settings(
            app_env="production",
            oidc_issuer_url="https://issuer.example",
            oidc_audience="habitat-api",
            enable_remote_inference=True,
            inference_provider="qwen_cloud",
            alibaba_model_studio_host="https://test-workspace.ap-southeast-1.maas.aliyuncs.com/",
            qwen_cloud_api_key="test-key",
        )
    )

    assert client.configured
    assert client.provider == "qwen_cloud"
    assert client.model_id == "qwen3.7-flash"
    assert client.model_version == "qwen-cloud-managed"
    assert client._endpoint == "https://test-workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions"


def test_alibaba_is_default_and_requires_a_workspace_host() -> None:
    settings = Settings(app_env="staging", enable_remote_inference=True, qwen_cloud_api_key="test-key")
    assert settings.inference_provider == "qwen_cloud"
    assert not QwenInferenceClient(settings).configured


@pytest.mark.parametrize("host", [
    "http://workspace.ap-southeast-1.maas.aliyuncs.com",
    "https://untrusted.example",
    "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "https://user:password@workspace.ap-southeast-1.maas.aliyuncs.com",
])
def test_alibaba_host_rejects_insecure_or_incorrect_configuration(host: str) -> None:
    with pytest.raises(ValueError, match="HTTPS workspace host"):
        Settings(_env_file=None, alibaba_model_studio_host=host)
