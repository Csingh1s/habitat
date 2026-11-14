from habitat_api.inference import QwenInferenceClient
from habitat_api.settings import Settings


def test_local_development_never_enables_remote_qwen_calls() -> None:
    client = QwenInferenceClient(
        Settings(
            app_env="development",
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
            qwen_cloud_api_key="test-key",
        )
    )

    assert client.configured
    assert client.provider == "qwen_cloud"
    assert client.model_id == "qwen3.7-flash"
    assert client.model_version == "qwen-cloud-managed"
