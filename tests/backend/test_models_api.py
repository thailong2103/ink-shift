"""Integration tests for dynamic live model discovery API endpoint."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.app import create_app
from src.backend.config import Settings


@pytest.fixture
def app() -> FastAPI:
    settings = Settings(
        gemini_api_key="test-gemini-key",
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        custom_api_key="test-custom-key",
        custom_base_url="https://custom.api/v1",
    )
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, headers={"X-InkShift-Client": "extension"})


def test_discover_models_google_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify live discovery parsing for Google Gemini models."""
    sample_google_payload = {
        "models": [
            {
                "name": "models/gemini-2.5-flash",
                "displayName": "Gemini 2.5 Flash",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-1.5-pro",
                "displayName": "Gemini 1.5 Pro",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/text-embedding-004",
                "displayName": "Embedding 004",
                "supportedGenerationMethods": ["embedContent"],
            },
        ]
    }

    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=sample_google_payload, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resp = client.post("/api/v1/models/discover", json={"provider": "google"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "google"
    models = data["models"]
    # Embedding model excluded
    assert len(models) == 2
    model_ids = [m["id"] for m in models]
    assert "gemini-2.5-flash" in model_ids
    assert "gemini-1.5-pro" in model_ids
    for m in models:
        assert m["supports_vision"] is True


def test_discover_models_openai_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify live discovery parsing and vision classification for OpenAI models."""
    sample_openai_payload = {
        "data": [
            {"id": "gpt-4o", "created": 1715368132},
            {"id": "gpt-4o-mini", "created": 1715368132},
            {"id": "gpt-3.5-turbo", "created": 1715368132},
            {"id": "o1-mini", "created": 1715368132},
            {"id": "text-embedding-3-small", "created": 1715368132},
            {"id": "dall-e-3", "created": 1715368132},
        ]
    }

    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=sample_openai_payload, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resp = client.post("/api/v1/models/discover", json={"provider": "openai"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openai"
    models = {m["id"]: m for m in data["models"]}

    # Non-chat models filtered
    assert "text-embedding-3-small" not in models
    assert "dall-e-3" not in models

    # Multimodal check
    assert models["gpt-4o"]["supports_vision"] is True
    assert models["gpt-4o-mini"]["supports_vision"] is True
    assert models["gpt-3.5-turbo"]["supports_vision"] is False
    assert models["o1-mini"]["supports_vision"] is False


def test_discover_models_anthropic_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify live discovery parsing for Anthropic Claude models."""
    sample_anthropic_payload = {
        "data": [
            {"id": "claude-3-5-sonnet-20241022", "display_name": "Claude 3.5 Sonnet"},
            {"id": "claude-3-5-haiku-20241022", "display_name": "Claude 3.5 Haiku"},
        ]
    }

    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=sample_anthropic_payload, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resp = client.post("/api/v1/models/discover", json={"provider": "anthropic"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "anthropic"
    assert len(data["models"]) == 2
    for m in data["models"]:
        assert m["supports_vision"] is True


def test_discover_models_anthropic_fallback(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify fallback to catalog when Anthropic returns 404 or unsupported."""
    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(404, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resp = client.post("/api/v1/models/discover", json={"provider": "anthropic"})
    assert resp.status_code == 200
    data = resp.json()
    model_ids = [m["id"] for m in data["models"]]
    assert any("claude-3-5-sonnet" in mid for mid in model_ids)


def test_discover_models_custom_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify custom provider models discovery via base URL."""
    sample_custom_payload = {
        "data": [
            {"id": "deepseek-chat"},
            {"id": "deepseek-vl"},
            {"id": "qwen2.5-vl-72b-instruct"},
        ]
    }

    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=sample_custom_payload, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resp = client.post(
        "/api/v1/models/discover",
        json={"provider": "custom", "base_url": "https://custom.api/v1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    models = {m["id"]: m for m in data["models"]}
    assert models["deepseek-chat"]["supports_vision"] is False
    assert models["deepseek-vl"]["supports_vision"] is True
    assert models["qwen2.5-vl-72b-instruct"]["supports_vision"] is True


def test_discover_models_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify error when API key is not configured and not provided."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    settings = Settings(gemini_api_key="")
    test_app = create_app(settings)
    test_client = TestClient(test_app, headers={"X-InkShift-Client": "extension"})

    resp = test_client.post("/api/v1/models/discover", json={"provider": "google"})
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "MISSING_API_KEY"


def test_discover_models_auth_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 401 upstream error is mapped properly."""
    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        req = httpx.Request("GET", url)
        return httpx.Response(401, json={"error": {"message": "Invalid API Key"}}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resp = client.post("/api/v1/models/discover", json={"provider": "openai"})
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "INVALID_API_KEY"


def test_discover_models_timeout_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify timeout is mapped to 504."""
    async def mock_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resp = client.post("/api/v1/models/discover", json={"provider": "openai"})
    assert resp.status_code == 504
    data = resp.json()
    assert data["error"]["code"] == "UPSTREAM_TIMEOUT"
