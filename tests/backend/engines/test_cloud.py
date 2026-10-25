"""Unit tests for Cloud Vision Turbo Provider foundation and GeminiProvider."""

import base64
import io
import json
from typing import Any

import httpx
import pytest
from PIL import Image

from src.backend.config import Settings
from src.backend.detection.base import DetectedBubble, DetectedText
from src.backend.engines.cloud.engine import CloudTranslationEngine
from src.backend.engines.cloud.exceptions import (
    CloudEngineError,
    ContentSafetyBlockedError,
    RateLimitExceededError,
    UpstreamAuthenticationError,
    UpstreamExecutionError,
    UpstreamTimeoutError,
)
from src.backend.engines.cloud.gemini import GeminiProvider
from src.backend.engines.cloud.openai_compat import OpenAICompatibleProvider
from src.backend.engines.cloud.prompts import get_som_system_prompt
from src.backend.engines.cloud.provider import CloudProvider
from src.backend.engines.cloud.provider_registry import ProviderRegistry
from src.backend.engines.cloud.visual_grounding import (
    create_marked_image_bytes,
    draw_set_of_marks,
)
from src.backend.schemas.contract import TranslatedBlock, TranslationRequest

# ---------------------------------------------------------------------------
# Task 1 Foundation Tests
# ---------------------------------------------------------------------------


def test_settings_cloud_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should provide safe and expected defaults for cloud providers."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    monkeypatch.delenv("XKIRO_API_KEY", raising=False)
    monkeypatch.delenv("INKSHIFT_CLOUD_PROVIDER", raising=False)
    settings = Settings()
    assert settings.gemini_api_key == ""
    assert settings.gemini_model == "gemini-2.0-flash"
    assert settings.gemini_base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert settings.custom_api_key == ""
    assert settings.xkiro_api_key == ""
    assert settings.xkiro_model == ""
    assert settings.xkiro_base_url == "https://api.xkiro.com/v1"
    assert settings.inkshift_cloud_provider == "gemini"


def test_settings_cloud_custom_overrides() -> None:
    """Settings should accept custom parameters for all cloud options."""
    settings = Settings(
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_base_url="https://custom.gemini.api/v1beta",
        xkiro_api_key="test-xkiro-key",
        xkiro_model="qwen/qwen3.8-flash",
        xkiro_base_url="https://custom.xkiro.com/v1",
        inkshift_cloud_provider="xkiro",
    )
    assert settings.gemini_api_key == "test-gemini-key"
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_base_url == "https://custom.gemini.api/v1beta"
    assert settings.xkiro_api_key == "test-xkiro-key"
    assert settings.xkiro_model == "qwen/qwen3.8-flash"
    assert settings.xkiro_base_url == "https://custom.xkiro.com/v1"
    assert settings.inkshift_cloud_provider == "xkiro"


def test_cloud_exceptions_attributes() -> None:
    """Domain exceptions should map to contract error codes and HTTP statuses."""
    base_err = CloudEngineError("Generic error")
    assert base_err.code == "ENGINE_EXECUTION_FAILED"
    assert base_err.status_code == 502

    rate_err = RateLimitExceededError()
    assert rate_err.code == "RATE_LIMIT_EXCEEDED"
    assert rate_err.status_code == 429

    safety_err = ContentSafetyBlockedError()
    assert safety_err.code == "CONTENT_SAFETY_BLOCKED"
    assert safety_err.status_code == 422

    timeout_err = UpstreamTimeoutError()
    assert timeout_err.code == "UPSTREAM_TIMEOUT"
    assert timeout_err.status_code == 504

    auth_err = UpstreamAuthenticationError()
    assert auth_err.code == "INVALID_API_KEY"
    assert auth_err.status_code == 401

    exec_err = UpstreamExecutionError()
    assert exec_err.code == "ENGINE_EXECUTION_FAILED"
    assert exec_err.status_code == 502


def test_cloud_provider_protocol_runtime_check() -> None:
    """Classes implementing CloudProvider should satisfy runtime_checkable protocol."""

    class ValidProvider:
        @property
        def name(self) -> str:
            return "mock-cloud"

        @property
        def default_model(self) -> str:
            return "mock-model"

        async def is_available(self) -> bool:
            return True

        async def translate_page(
            self,
            image_base64: str,
            target_lang: str = "vi",
            model: str | None = None,
        ) -> list[TranslatedBlock]:
            return []

    class IncompleteProvider:
        @property
        def name(self) -> str:
            return "incomplete"

    assert isinstance(ValidProvider(), CloudProvider)
    assert not isinstance(IncompleteProvider(), CloudProvider)


def test_som_system_prompt_constraints() -> None:
    """SoM system prompt should instruct returning flat JSON dictionary with target language."""
    prompt_vi = get_som_system_prompt("vi")
    assert "Vietnamese" in prompt_vi
    assert "flat JSON object" in prompt_vi
    assert '"1":' in prompt_vi

    prompt_en = get_som_system_prompt("en")
    assert "en" in prompt_en


# ---------------------------------------------------------------------------
# Task 2 GeminiProvider Tests (Mock Transports)
# ---------------------------------------------------------------------------


def make_gemini_candidate_payload(data: Any, finish_reason: str = "STOP") -> dict[str, Any]:
    """Helper to synthesize valid Gemini API response payload."""
    text_content = json.dumps(data) if not isinstance(data, str) else data
    return {
        "candidates": [
            {
                "finishReason": finish_reason,
                "content": {
                    "parts": [
                        {
                            "text": text_content,
                        }
                    ]
                },
            }
        ]
    }


@pytest.fixture
def sample_bubbles() -> list[DetectedBubble]:
    """Sample YOLO11 detected bubbles for test fixtures."""
    return [
        DetectedBubble(
            id="b1",
            box_2d=(120, 250, 340, 560),
            confidence=0.95,
        ),
        DetectedBubble(
            id="b2",
            box_2d=(500, 100, 700, 400),
            confidence=0.99,
        ),
    ]


@pytest.mark.asyncio
async def test_gemini_provider_properties_and_availability(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should correctly report name, model, and availability."""
    provider_no_key = GeminiProvider(api_key="")
    assert provider_no_key.name == "gemini"
    assert provider_no_key.default_model == "gemini-2.0-flash"
    assert not await provider_no_key.is_available()

    with pytest.raises(UpstreamAuthenticationError) as exc_info:
        await provider_no_key.translate_page("iVBORw0KGgo=", bubbles=sample_bubbles)
    assert "Gemini API key is not configured" in str(exc_info.value)

    provider_with_key = GeminiProvider(api_key="AIzaSyValidKey")
    assert await provider_with_key.is_available()


@pytest.mark.asyncio
async def test_gemini_provider_happy_path(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should extract structured TranslatedBlock objects with normalized coordinates."""
    mock_dict = {
        "b1": "Cái gì thế này?",
        "b2": "Nguy hiểm quá!",
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "AIzaSyTestKey"
        assert "gemini-2.0-flash:generateContent" in str(request.url)
        body = json.loads(request.content)
        assert "contents" in body
        assert body["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/jpeg"
        return httpx.Response(200, json=make_gemini_candidate_payload(mock_dict))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(
            api_key="AIzaSyTestKey",
            http_client=client,
        )
        blocks = await provider.translate_page(
            image_base64="aGVsbG8=",
            target_lang="vi",
            bubbles=sample_bubbles,
        )

    assert len(blocks) == 2
    assert blocks[0].id == "b1"
    assert blocks[0].box == (120, 250, 340, 560)
    assert blocks[0].translated_text == "Cái gì thế này?"
    assert blocks[0].direction == "horizontal"
    assert blocks[0].confidence == 0.95

    assert blocks[1].id == "b2"
    assert blocks[1].box == (500, 100, 700, 400)
    assert blocks[1].translated_text == "Nguy hiểm quá!"
    assert blocks[1].direction == "horizontal"
    assert blocks[1].confidence == 0.99


@pytest.mark.asyncio
async def test_gemini_provider_empty_page() -> None:
    """GeminiProvider should handle zero-bubble pages gracefully returning empty list."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Should not be called")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=[])

    assert blocks == []


@pytest.mark.asyncio
async def test_gemini_provider_data_url_and_mime_extraction(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should extract correct mime-type and strip data URL prefix."""
    captured_mime = ""
    captured_data = ""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_mime, captured_data
        body = json.loads(request.content)
        inline_data = body["contents"][0]["parts"][1]["inlineData"]
        captured_mime = inline_data["mimeType"]
        captured_data = inline_data["data"]
        return httpx.Response(200, json=make_gemini_candidate_payload({"b1": "ok"}))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client)
        png_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA=="
        await provider.translate_page(png_data_url, bubbles=sample_bubbles)

    assert captured_mime == "image/jpeg"
    assert len(captured_data) > 0


@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_retry_success(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should retry on HTTP 429 and succeed if subsequent attempt passes."""
    attempts = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "Resource exhausted"}})
        return httpx.Response(200, json=make_gemini_candidate_payload({"b1": "ok", "b2": "ok"}))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client, max_retries=2)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert attempts == 2
    assert len(blocks) == 2


@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_exhausted(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should raise RateLimitExceededError when retries are exhausted."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Resource exhausted"}})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client, max_retries=1)
        with pytest.raises(RateLimitExceededError):
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)


@pytest.mark.asyncio
async def test_gemini_provider_safety_rejection_candidate(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should raise ContentSafetyBlockedError when finishReason is SAFETY."""
    safety_payload = {
        "candidates": [
            {
                "finishReason": "SAFETY",
                "safetyRatings": [{"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "probability": "HIGH"}],
            }
        ]
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=safety_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client)
        with pytest.raises(ContentSafetyBlockedError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "CONTENT_SAFETY_BLOCKED"
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_gemini_provider_safety_rejection_prompt_feedback(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should raise ContentSafetyBlockedError when promptFeedback blocks request."""
    safety_payload = {
        "promptFeedback": {
            "blockReason": "PROHIBITED_CONTENT",
        }
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=safety_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client)
        with pytest.raises(ContentSafetyBlockedError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "CONTENT_SAFETY_BLOCKED"


@pytest.mark.asyncio
async def test_gemini_provider_upstream_timeout(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should map httpx.TimeoutException to UpstreamTimeoutError."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Socket read timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client)
        with pytest.raises(UpstreamTimeoutError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "UPSTREAM_TIMEOUT"
    assert exc_info.value.status_code == 504


@pytest.mark.asyncio
async def test_gemini_provider_auth_error_http_403(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should raise UpstreamAuthenticationError on HTTP 403."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "The caller does not have permission"}})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="invalid_key", http_client=client)
        with pytest.raises(UpstreamAuthenticationError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "INVALID_API_KEY"
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_gemini_provider_execution_error_http_500(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should raise UpstreamExecutionError on server errors."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client)
        with pytest.raises(UpstreamExecutionError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "ENGINE_EXECUTION_FAILED"


@pytest.mark.asyncio
async def test_gemini_provider_som_ground_truth_coordinates(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider with SoM should preserve exact YOLO11 ground-truth coordinates."""
    som_payload = {"b1": "thử nghiệm", "b2": "thử nghiệm 2"}

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_gemini_candidate_payload(som_payload))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="key", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert len(blocks) == 2
    assert blocks[0].box == (120, 250, 340, 560)
    assert blocks[0].translated_text == "thử nghiệm"



# ---------------------------------------------------------------------------
# Task 3 OpenAICompatibleProvider Tests (Mock Transports)
# ---------------------------------------------------------------------------


def make_openai_chat_payload(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    """Helper to synthesize valid OpenAI Chat Completions response payload."""
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
            }
        ]
    }


@pytest.mark.asyncio
async def test_openai_provider_properties_and_availability(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should report name, model, and availability."""
    provider_no_key = OpenAICompatibleProvider(api_key="", base_url="https://api.xkiro.com/v1")
    assert provider_no_key.name == "xkiro"
    assert provider_no_key.default_model == ""
    assert not await provider_no_key.is_available()

    with pytest.raises(UpstreamAuthenticationError) as exc_info:
        await provider_no_key.translate_page("aGVsbG8=", bubbles=sample_bubbles)
    assert "API key is not configured" in str(exc_info.value)

    # Local endpoints (Ollama/vLLM) should be available even without api_key
    local_provider = OpenAICompatibleProvider(api_key="", base_url="http://localhost:11434/v1")
    assert await local_provider.is_available()

    provider_with_key = OpenAICompatibleProvider(api_key="xkiro-secret-key")
    assert await provider_with_key.is_available()


@pytest.mark.asyncio
async def test_openai_provider_happy_path_clean_json(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should parse clean JSON dictionary output mapping badge IDs."""
    mock_dict = {
        "b1": "Cứu tôi với!",
        "b2": "Nhanh lên!",
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer xkiro-test-key"
        assert "/chat/completions" in str(request.url)
        body = json.loads(request.content)
        assert body["model"] == "test-vision-model"
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        return httpx.Response(200, json=make_openai_chat_payload(json.dumps(mock_dict)))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="xkiro-test-key", model="test-vision-model", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert len(blocks) == 2
    assert blocks[0].id == "b1"
    assert blocks[0].box == (120, 250, 340, 560)
    assert blocks[0].translated_text == "Cứu tôi với!"
    assert blocks[0].direction == "horizontal"

    assert blocks[1].id == "b2"
    assert blocks[1].box == (500, 100, 700, 400)
    assert blocks[1].translated_text == "Nhanh lên!"


@pytest.mark.asyncio
async def test_openai_provider_markdown_fence_stripping(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should strip markdown code fences cleanly."""
    fenced_content = """```json
{
  "b1": "Thử nghiệm",
  "b2": "Thử nghiệm 2"
}
```"""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openai_chat_payload(fenced_content))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="key", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert len(blocks) == 2
    assert blocks[0].id == "b1"
    assert blocks[0].translated_text == "Thử nghiệm"
    assert blocks[0].box == (120, 250, 340, 560)


@pytest.mark.asyncio
async def test_openai_provider_dict_wrapper(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should extract dict from wrapper keys like {'translations': {...}}."""
    dict_wrapped = json.dumps(
        {
            "translations": {
                "b1": "Bọc trong dict",
                "b2": "Bọc trong dict 2",
            }
        }
    )

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openai_chat_payload(dict_wrapped))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="key", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert len(blocks) == 2
    assert blocks[0].id == "b1"
    assert blocks[0].translated_text == "Bọc trong dict"


@pytest.mark.asyncio
async def test_openai_provider_rate_limit_retry(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should retry on HTTP 429 and raise RateLimitExceededError on exhaustion."""
    attempts = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})
        return httpx.Response(200, json=make_openai_chat_payload(json.dumps({"b1": "ok", "b2": "ok 2"})))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="key", http_client=client, max_retries=2)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert attempts == 2
    assert len(blocks) == 2

    # Test persistent 429 raises RateLimitExceededError
    async def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Persistent 429"}})

    fail_transport = httpx.MockTransport(failing_handler)
    async with httpx.AsyncClient(transport=fail_transport) as client:
        fail_provider = OpenAICompatibleProvider(api_key="key", http_client=client, max_retries=1)
        with pytest.raises(RateLimitExceededError):
            await fail_provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)


@pytest.mark.asyncio
async def test_openai_provider_refusal_detection(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should detect textual refusals and finish_reason='content_filter'."""
    # Textual refusal in English
    refusal_content = "I cannot fulfill this request due to our safety policy regarding explicit imagery."
    async def refusal_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openai_chat_payload(refusal_content))

    transport = httpx.MockTransport(refusal_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="key", http_client=client)
        with pytest.raises(ContentSafetyBlockedError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)
    assert exc_info.value.code == "CONTENT_SAFETY_BLOCKED"

    # Finish reason content_filter
    async def filter_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openai_chat_payload("", finish_reason="content_filter"))

    transport_filter = httpx.MockTransport(filter_handler)
    async with httpx.AsyncClient(transport=transport_filter) as client:
        provider_filter = OpenAICompatibleProvider(api_key="key", http_client=client)
        with pytest.raises(ContentSafetyBlockedError):
            await provider_filter.translate_page("aGVsbG8=", bubbles=sample_bubbles)


@pytest.mark.asyncio
async def test_openai_provider_upstream_timeout(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should raise UpstreamTimeoutError on network timeouts."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Socket timeout")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="key", http_client=client)
        with pytest.raises(UpstreamTimeoutError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "UPSTREAM_TIMEOUT"
    assert exc_info.value.status_code == 504


@pytest.mark.asyncio
async def test_openai_provider_auth_error_http_401(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should raise UpstreamAuthenticationError on HTTP 401."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="wrong_key", http_client=client)
        with pytest.raises(UpstreamAuthenticationError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "INVALID_API_KEY"
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_openai_provider_execution_error_http_500(sample_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should raise UpstreamExecutionError on server failures."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="key", http_client=client)
        with pytest.raises(UpstreamExecutionError) as exc_info:
            await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert exc_info.value.code == "ENGINE_EXECUTION_FAILED"



# ---------------------------------------------------------------------------
# Task 4 CloudTranslationEngine Tests
# ---------------------------------------------------------------------------


class MockCloudProvider:
    """Mock implementation of CloudProvider protocol for engine tests."""

    def __init__(
        self,
        name: str = "mock-cloud",
        default_model: str = "mock-model",
        available: bool = True,
        blocks: list[TranslatedBlock] | None = None,
        error_to_raise: Exception | None = None,
    ) -> None:
        self._name = name
        self._default_model = default_model
        self._available = available
        self._blocks = blocks if blocks is not None else []
        self._error_to_raise = error_to_raise
        self.translate_called_with: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def default_model(self) -> str:
        return self._default_model

    async def is_available(self) -> bool:
        return self._available

    async def translate_page(
        self,
        image_base64: str,
        target_lang: str = "vi",
        model: str | None = None,
        bubbles: list[DetectedBubble] | None = None,
    ) -> list[TranslatedBlock]:
        if self._error_to_raise is not None:
            raise self._error_to_raise
        self.translate_called_with = {
            "image_base64": image_base64,
            "target_lang": target_lang,
            "model": model,
            "bubbles": bubbles,
        }
        return self._blocks


@pytest.mark.asyncio
async def test_cloud_translation_engine_properties() -> None:
    """CloudTranslationEngine should expose name, provider, and delegate is_available."""
    provider_available = MockCloudProvider(available=True)
    engine = CloudTranslationEngine(provider=provider_available, name="cloud-test")
    assert engine.name == "cloud-test"
    assert engine.provider is provider_available
    assert await engine.is_available() is True

    provider_unavailable = MockCloudProvider(available=False)
    engine_unavail = CloudTranslationEngine(provider=provider_unavailable)
    assert engine_unavail.name == "cloud"
    assert await engine_unavail.is_available() is False


@pytest.mark.asyncio
async def test_cloud_translation_engine_translate_happy_path() -> None:
    """CloudTranslationEngine should strip data URL prefix, execute provider, and return TranslationResponse."""
    sample_blocks = [
        TranslatedBlock(
            id="blk_01",
            box=(100, 200, 300, 400),
            source_text="こんにちは",
            translated_text="Xin chào",
            direction="vertical",
            confidence=0.99,
        )
    ]
    provider = MockCloudProvider(blocks=sample_blocks)
    engine = CloudTranslationEngine(provider=provider, name="cloud")

    request = TranslationRequest(
        image="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        image_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        source_lang="ja",
        target_lang="vi",
        engine="cloud",
    )

    response = await engine.translate(request)
    assert response.success is True
    assert response.page_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert response.engine_used == "cloud"
    assert response.from_cache is False
    assert response.execution_time_ms >= 0
    assert len(response.blocks) == 1
    assert response.blocks[0].translated_text == "Xin chào"

    # Verify provider received raw Base64 without 'data:image/png;base64,' prefix
    assert not provider.translate_called_with["image_base64"].startswith("data:")
    assert provider.translate_called_with["target_lang"] == "vi"


@pytest.mark.asyncio
async def test_cloud_translation_engine_auto_computes_sha256() -> None:
    """When image_hash is not provided, CloudTranslationEngine computes sha256 hex digest."""
    provider = MockCloudProvider(blocks=[])
    engine = CloudTranslationEngine(provider=provider, name="cloud-gemini")

    request = TranslationRequest(
        image="aGVsbG8gd29ybGQ=",
        engine="cloud",
    )

    response = await engine.translate(request)
    assert len(response.page_hash) == 64
    assert response.engine_used == "cloud-gemini"
    assert response.blocks == []


@pytest.mark.asyncio
async def test_cloud_translation_engine_propagates_domain_exceptions() -> None:
    """CloudTranslationEngine should allow CloudEngineError exceptions to bubble up for HTTP handling."""
    provider = MockCloudProvider(error_to_raise=ContentSafetyBlockedError("NSFW Manga Blocked"))
    engine = CloudTranslationEngine(provider=provider)

    request = TranslationRequest(
        image="aGVsbG8gd29ybGQ=",
        engine="cloud",
    )

    with pytest.raises(ContentSafetyBlockedError) as exc_info:
        await engine.translate(request)
    assert exc_info.value.code == "CONTENT_SAFETY_BLOCKED"


@pytest.mark.asyncio
async def test_cloud_translation_engine_dynamic_provider_routing(sample_bubbles: list[DetectedBubble]) -> None:
    """CloudTranslationEngine should dynamically route requests to providers via ProviderRegistry."""
    gemini_blocks = [
        TranslatedBlock(
            id="b1",
            box=(120, 250, 340, 560),
            translated_text="Bản dịch Gemini",
            direction="vertical",
        )
    ]
    openai_blocks = [
        TranslatedBlock(
            id="b1",
            box=(120, 250, 340, 560),
            translated_text="Bản dịch OpenAI",
            direction="vertical",
        )
    ]
    p_gemini = MockCloudProvider(name="gemini", blocks=gemini_blocks)
    p_openai = MockCloudProvider(name="openai", blocks=openai_blocks)

    reg = ProviderRegistry(default_provider_name="gemini")
    reg.register("gemini", p_gemini)
    reg.register("openai", p_openai)

    engine = CloudTranslationEngine(registry=reg, name="cloud")
    assert engine.name == "cloud"

    # 1. Default routing (no provider specified) -> gemini
    req_default = TranslationRequest(image="aGVsbG8=", engine="cloud")
    resp_default = await engine.translate(req_default, bubbles=sample_bubbles)
    assert resp_default.engine_used == "cloud"
    assert resp_default.blocks[0].translated_text == "Bản dịch Gemini"
    assert p_gemini.translate_called_with["bubbles"] == sample_bubbles

    # 2. Explicit provider="openai" -> openai
    req_openai = TranslationRequest(image="aGVsbG8=", engine="cloud", provider="openai")
    resp_openai = await engine.translate(req_openai, bubbles=sample_bubbles)
    assert resp_openai.engine_used == "cloud"
    assert resp_openai.blocks[0].translated_text == "Bản dịch OpenAI"

    # 3. Alias provider="xkiro" -> resolves to openai
    req_xkiro = TranslationRequest(image="aGVsbG8=", engine="cloud", provider="xkiro")
    resp_xkiro = await engine.translate(req_xkiro, bubbles=sample_bubbles)
    assert resp_xkiro.blocks[0].translated_text == "Bản dịch OpenAI"

    # 4. Explicit provider="gemini" -> gemini
    req_gemini = TranslationRequest(image="aGVsbG8=", engine="cloud", provider="gemini")
    resp_gemini = await engine.translate(req_gemini, bubbles=sample_bubbles)
    assert resp_gemini.blocks[0].translated_text == "Bản dịch Gemini"



# ---------------------------------------------------------------------------
# Set-of-Marks (SoM) & Visual Grounding Tests
# ---------------------------------------------------------------------------


def test_visual_grounding_draw_marks() -> None:
    """draw_set_of_marks should annotate bubbles with 1px contours and high-contrast badges."""
    img = Image.new("RGB", (800, 1200), (255, 255, 255))
    bubble1 = DetectedBubble(
        id="1",
        box_2d=(100, 500, 300, 750),
        polygon=[(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)],
    )
    bubble2 = DetectedBubble(
        id="2",
        box_2d=(400, 100, 600, 350),
    )

    marked = draw_set_of_marks(img, [bubble1, bubble2])
    assert marked.size == (800, 1200)

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    res_bytes = create_marked_image_bytes(buf.getvalue(), [bubble1, bubble2])
    assert len(res_bytes) > 0
    loaded = Image.open(io.BytesIO(res_bytes))
    assert loaded.size == (800, 1200)


def test_visual_grounding_styling_and_text_box_only() -> None:
    """draw_set_of_marks should outline only text boxes and paint vibrant amber badges."""
    # White canvas (800x1000)
    img = Image.new("RGB", (800, 1000), (255, 255, 255))
    bubble = DetectedBubble(
        id="1",
        box_2d=(100, 200, 400, 600),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        texts=[
            DetectedText(box_2d=(150, 250, 250, 550), confidence=0.9),
            DetectedText(box_2d=(280, 250, 380, 550), confidence=0.9),
        ],
    )

    marked = draw_set_of_marks(img, [bubble])
    # The image must contain crimson red outline pixels (220, 38, 38)
    # and amber gold badge background pixels (245, 158, 11)
    colors = {c[1] for c in (marked.getcolors(maxcolors=800 * 1000) or [])}
    assert (220, 38, 38) in colors, "Expected crimson red outline pixels on the marked image"
    assert (245, 158, 11) in colors, "Expected amber gold badge background pixels on the marked image"



def test_som_system_prompt() -> None:
    """get_som_system_prompt should instruct Gemini to return flat JSON dictionary."""
    prompt = get_som_system_prompt("vi")
    assert "Vietnamese" in prompt
    assert "flat JSON object" in prompt
    assert '"1":' in prompt


@pytest.mark.asyncio
async def test_gemini_provider_som_flow() -> None:
    """GeminiProvider with detector should run SoM, send marked image, and return blocks with YOLO11 coordinates."""
    bubble1 = DetectedBubble(
        id="1",
        box_2d=(100, 600, 300, 850),
        polygon=[(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)],
        confidence=0.98,
    )
    bubble2 = DetectedBubble(
        id="2",
        box_2d=(500, 100, 700, 350),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.95,
    )

    som_response_json = json.dumps({"1": "Lời thoại số 1", "2": "Lời thoại số 2"})

    captured_prompt = ""
    captured_mime = ""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_prompt, captured_mime
        body = json.loads(request.content)
        captured_prompt = body["contents"][0]["parts"][0]["text"]
        captured_mime = body["contents"][0]["parts"][1]["inlineData"]["mimeType"]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": som_response_json}],
                        },
                    }
                ]
            },
        )

    # Create dummy manga image
    dummy_img = Image.new("RGB", (800, 1200), color="white")
    buf = io.BytesIO()
    dummy_img.save(buf, format="JPEG")
    raw_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(
            api_key="test-key",
            http_client=client,
        )
        blocks = await provider.translate_page(raw_b64, target_lang="vi", bubbles=[bubble1, bubble2])

    assert "flat JSON object" in captured_prompt
    assert captured_mime == "image/jpeg"

    assert len(blocks) == 2
    # Block 1
    assert blocks[0].id == "1"
    assert blocks[0].box == (100, 600, 300, 850)
    assert blocks[0].polygon == [(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)]
    assert blocks[0].translated_text == "Lời thoại số 1"
    assert blocks[0].confidence == 0.98

    # Block 2
    assert blocks[1].id == "2"
    assert blocks[1].box == (500, 100, 700, 350)
    assert blocks[1].translated_text == "Lời thoại số 2"
    assert blocks[1].confidence == 0.95


@pytest.mark.asyncio
async def test_gemini_provider_som_zero_bubbles_no_api_call() -> None:
    """When bubbles is empty, GeminiProvider returns [] immediately with zero network requests."""
    http_called = False

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_called
        http_called = True
        return httpx.Response(500, text="Should not be called")

    dummy_img = Image.new("RGB", (500, 500), color="white")
    buf = io.BytesIO()
    dummy_img.save(buf, format="JPEG")
    raw_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(
            api_key="test-key",
            http_client=client,
        )
        blocks = await provider.translate_page(raw_b64, bubbles=[])

    assert http_called is False  # Zero API cost!
    assert blocks == []


@pytest.mark.asyncio
async def test_gemini_provider_retries_on_503(sample_bubbles: list[DetectedBubble]) -> None:
    """GeminiProvider should retry on HTTP 503 temporary capacity error and succeed."""
    call_count = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, text="Service Unavailable: Model experiencing high demand")
        return httpx.Response(
            200,
            json=make_gemini_candidate_payload({"b1": "Chào bạn", "b2": "Hẹn gặp lại"}),
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(
            api_key="AIzaSyTestKey",
            http_client=client,
            max_retries=2,
        )
        blocks = await provider.translate_page("aGVsbG8=", bubbles=sample_bubbles)

    assert call_count == 2
    assert len(blocks) == 2
    assert blocks[0].translated_text == "Chào bạn"


@pytest.mark.asyncio
async def test_gemini_provider_polygon_safe_zone_fitting() -> None:
    """GeminiProvider should compute polygon safe-zones and link parent_box/parent_bubble_id."""
    complex_poly = [
        (20.0, 0.0),
        (80.0, 0.0),
        (100.0, 50.0),
        (80.0, 100.0),
        (20.0, 100.0),
        (0.0, 50.0),
    ]
    bubbles = [
        DetectedBubble(
            id="poly_1",
            box_2d=(100, 100, 500, 500),
            polygon=complex_poly,
            confidence=0.95,
        )
    ]

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_gemini_candidate_payload({"poly_1": "Dịch bên trong polygon"}),
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(
            api_key="AIzaSyTestKey",
            http_client=client,
        )
        blocks = await provider.translate_page("aGVsbG8=", bubbles=bubbles)

    assert len(blocks) == 1
    assert blocks[0].id == "poly_1"
    assert blocks[0].translated_text == "Dịch bên trong polygon"
    assert blocks[0].parent_box == (100, 100, 500, 500)
    assert blocks[0].parent_bubble_id == "poly_1"
    assert blocks[0].polygon == complex_poly


@pytest.mark.asyncio
async def test_gemini_provider_multi_child_bubble() -> None:
    """GeminiProvider should emit separate TranslatedBlocks for connected/multi-child bubbles."""
    poly = [(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)]
    bubble = DetectedBubble(
        id="1",
        box_2d=(100, 150, 300, 350),
        polygon=poly,
        confidence=0.96,
        texts=[
            DetectedText(box_2d=(110, 160, 190, 340), confidence=0.92),
            DetectedText(box_2d=(210, 160, 290, 340), confidence=0.91),
        ],
    )

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_gemini_candidate_payload(
                {
                    "1": "Dòng thoại trên từ Gemini",
                    "2": "Dòng thoại dưới từ Gemini",
                }
            ),
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="AIzaValidKey", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=[bubble])

    assert len(blocks) == 2
    assert blocks[0].id == "blk_0_1"
    assert blocks[0].translated_text == "Dòng thoại trên từ Gemini"
    assert blocks[0].parent_bubble_id == "1"
    assert blocks[0].parent_box == (100, 150, 300, 350)
    assert blocks[0].polygon == poly

    assert blocks[1].id == "blk_1_2"
    assert blocks[1].translated_text == "Dòng thoại dưới từ Gemini"
    assert blocks[1].parent_bubble_id == "1"
    assert blocks[1].parent_box == (100, 150, 300, 350)
    assert blocks[1].polygon == poly


@pytest.mark.asyncio
async def test_openai_provider_multi_child_bubble() -> None:
    """OpenAICompatibleProvider should emit separate TranslatedBlocks for multi-child bubbles."""
    poly = [(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)]
    bubble = DetectedBubble(
        id="1",
        box_2d=(100, 150, 300, 350),
        polygon=poly,
        confidence=0.95,
        texts=[
            DetectedText(box_2d=(110, 160, 190, 340), confidence=0.9),
            DetectedText(box_2d=(210, 160, 290, 340), confidence=0.88),
        ],
    )

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps(
            {
                "1": "OpenAI child top",
                "2": "OpenAI child bottom",
            }
        )
        payload = {
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="sk-test", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=[bubble])

    assert len(blocks) == 2
    assert blocks[0].id == "blk_0_1"
    assert blocks[0].translated_text == "OpenAI child top"
    assert blocks[0].parent_bubble_id == "1"
    assert blocks[0].parent_box == (100, 150, 300, 350)

    assert blocks[1].id == "blk_1_2"
    assert blocks[1].translated_text == "OpenAI child bottom"
    assert blocks[1].parent_bubble_id == "1"
    assert blocks[1].parent_box == (100, 150, 300, 350)


def test_visual_grounding_draw_marks_multi_child() -> None:
    """draw_set_of_marks should annotate individual child text boxes when multiple exist."""
    img = Image.new("RGB", (800, 1200), (255, 255, 255))
    bubble = DetectedBubble(
        id="1",
        box_2d=(100, 200, 400, 500),
        polygon=[(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)],
        texts=[
            DetectedText(box_2d=(120, 220, 220, 480), confidence=0.9),
            DetectedText(box_2d=(250, 220, 380, 480), confidence=0.9),
        ],
    )

    marked = draw_set_of_marks(img, [bubble])
    assert marked.size == (800, 1200)

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    res_bytes = create_marked_image_bytes(buf.getvalue(), [bubble])
    assert len(res_bytes) > 0


@pytest.mark.asyncio
async def test_gemini_provider_mixed_multi_bubble() -> None:
    """GeminiProvider maps strictly sequential badge IDs on pages with mixed multi and single bubbles."""
    bubble1 = DetectedBubble(
        id="1",
        box_2d=(100, 150, 300, 350),
        polygon=[(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)],
        confidence=0.96,
        texts=[
            DetectedText(box_2d=(110, 160, 190, 340), confidence=0.92),
            DetectedText(box_2d=(210, 160, 290, 340), confidence=0.91),
        ],
    )
    bubble2 = DetectedBubble(
        id="2",
        box_2d=(400, 500, 550, 700),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.94,
        texts=[
            DetectedText(box_2d=(420, 520, 530, 680), confidence=0.9),
        ],
    )

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_gemini_candidate_payload(
                {
                    "1": "Gemini child 1",
                    "2": "Gemini child 2",
                    "3": "Gemini single bubble 2",
                }
            ),
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="AIzaValidKey", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=[bubble1, bubble2])

    assert len(blocks) == 3
    assert blocks[0].id == "blk_0_1"
    assert blocks[0].translated_text == "Gemini child 1"
    assert blocks[0].parent_bubble_id == "1"

    assert blocks[1].id == "blk_1_2"
    assert blocks[1].translated_text == "Gemini child 2"
    assert blocks[1].parent_bubble_id == "1"

    assert blocks[2].id == "2"
    assert blocks[2].translated_text == "Gemini single bubble 2"


def test_get_som_system_prompt_non_text_rules() -> None:
    """Prompt must explicitly instruct LLM to return empty string for hair, art, textures, and non-text."""
    prompt = get_som_system_prompt(target_lang="vi")
    assert "CRITICAL RULES FOR NON-TEXT OR EMPTY REGIONS" in prompt
    assert 'character hair, artwork textures, or blank background' in prompt
    assert 'Do not hallucinate or duplicate adjacent dialogue' in prompt
    assert 'set its value to an empty string ""' in prompt


@pytest.mark.asyncio
async def test_gemini_provider_omits_empty_translation_keys() -> None:
    """Provider drops regions where LLM returned empty string or whitespace-only translation."""
    bubble1 = DetectedBubble(
        id="1",
        box_2d=(100, 100, 200, 200),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )
    bubble2 = DetectedBubble(
        id="2",
        box_2d=(300, 300, 400, 400),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )
    bubble3 = DetectedBubble(
        id="3",
        box_2d=(500, 500, 600, 600),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_gemini_candidate_payload(
                {
                    "1": "Valid speech",
                    "2": "",
                    "3": "   ",
                }
            ),
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="AIzaValidKey", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=[bubble1, bubble2, bubble3])

    assert len(blocks) == 1
    assert blocks[0].id == "1"
    assert blocks[0].translated_text == "Valid speech"






