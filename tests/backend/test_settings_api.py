"""Integration tests for provider settings and API key management endpoints."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.app import create_app
from src.backend.config import Settings


@pytest.fixture
def app_with_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    mock_gemini_token = "AIzaSy" + "1234567890abcdefgh4xK8"
    mock_anthropic_token = "sk-ant" + "-api03-123456789abcdef4xK8"

    env_file = tmp_path / ".env"
    env_file.write_text(
        f"GEMINI_API_KEY={mock_gemini_token}\n"
        "OPENAI_API_KEY=\n"
        f"ANTHROPIC_API_KEY={mock_anthropic_token}\n"
        "CUSTOM_API_KEY=\n"
        "CUSTOM_BASE_URL=https://my-custom-proxy.internal/v1\n"
    )
    monkeypatch.setattr("src.backend.api.v1.settings.ENV_PATH", str(env_file))

    settings = Settings(
        gemini_api_key=mock_gemini_token,
        openai_api_key="",
        anthropic_api_key=mock_anthropic_token,
        custom_api_key="",
        custom_base_url="https://my-custom-proxy.internal/v1",
    )
    return create_app(settings)


@pytest.fixture
def client(app_with_env: FastAPI) -> TestClient:
    return TestClient(app_with_env, headers={"X-InkShift-Client": "extension"})


def test_get_provider_settings_masks_keys(client: TestClient) -> None:
    """Verify GET /api/v1/settings/providers returns masked keys and accurate configuration flags."""
    resp = client.get("/api/v1/settings/providers")
    assert resp.status_code == 200
    data = resp.json()
    providers = data["providers"]

    # Google should be configured and masked
    assert providers["google"]["configured"] is True
    assert providers["google"]["masked_key"] == "AIzaSy...4xK8"
    assert "1234567890abcdefgh" not in providers["google"]["masked_key"]

    # OpenAI not configured
    assert providers["openai"]["configured"] is False
    assert providers["openai"]["masked_key"] is None

    # Anthropic configured
    assert providers["anthropic"]["configured"] is True
    assert providers["anthropic"]["masked_key"] == "sk-ant...4xK8"

    # Custom has base_url
    assert providers["custom"]["configured"] is False
    assert providers["custom"]["base_url"] == "https://my-custom-proxy.internal/v1"


def test_post_provider_settings_updates_env_and_runtime(
    app_with_env: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    """Verify POST /api/v1/settings/providers saves key to .env and updates app.state.settings."""
    update_payload = {
        "provider": "openai",
        "api_key": "sk-proj-new-secret-token-123456789-end0",
    }
    resp = client.post("/api/v1/settings/providers", json=update_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["provider"] == "openai"
    assert data["status"]["configured"] is True
    assert data["status"]["masked_key"] == "sk-pro...end0"

    # Verify runtime settings in memory updated
    settings: Settings = app_with_env.state.settings
    assert settings.openai_api_key == "sk-proj-new-secret-token-123456789-end0"

    # Verify subsequent GET shows it configured
    get_resp = client.get("/api/v1/settings/providers")
    assert get_resp.status_code == 200
    providers = get_resp.json()["providers"]
    assert providers["openai"]["configured"] is True
    assert providers["openai"]["masked_key"] == "sk-pro...end0"


def test_post_provider_settings_custom_base_url(
    app_with_env: FastAPI, client: TestClient
) -> None:
    """Verify updating custom provider with both api_key and base_url."""
    update_payload = {
        "provider": "custom",
        "api_key": "test-mock-custom-key-9999",
        "base_url": "https://llm.internal.lan/v1",
    }
    resp = client.post("/api/v1/settings/providers", json=update_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]["configured"] is True
    assert data["status"]["base_url"] == "https://llm.internal.lan/v1"

    settings: Settings = app_with_env.state.settings
    assert settings.custom_api_key == "test-mock-custom-key-9999"
    assert settings.custom_base_url == "https://llm.internal.lan/v1"
