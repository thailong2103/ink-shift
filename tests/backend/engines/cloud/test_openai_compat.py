"""Unit tests for OpenAICompatibleProvider (xKiro, OpenRouter, Ollama) using Set-of-Marks."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.backend.detection.base import DetectedBubble
from src.backend.engines.cloud.exceptions import (
    ContentSafetyBlockedError,
    UpstreamAuthenticationError,
    UpstreamExecutionError,
    UpstreamTimeoutError,
)
from src.backend.engines.cloud.openai_compat import OpenAICompatibleProvider


def make_openai_chat_payload(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    """Helper to synthesize valid OpenAI Chat Completions API response payload."""
    return {
        "id": "chatcmpl-test-id",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
            }
        ],
    }


@pytest.fixture
def test_bubbles() -> list[DetectedBubble]:
    """Provide realistic YOLO11-detected bubbles with polygons."""
    return [
        DetectedBubble(
            id="1",
            box_2d=(100, 600, 300, 850),
            polygon=[(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)],
            confidence=0.98,
        ),
        DetectedBubble(
            id="2",
            box_2d=(500, 100, 700, 350),
            polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            confidence=0.95,
        ),
    ]


@pytest.mark.asyncio
async def test_openai_compat_som_flow(test_bubbles: list[DetectedBubble]) -> None:
    """OpenAICompatibleProvider should send marked image and map translations to ground-truth YOLO11 coordinates."""
    mock_dict = {
        "1": "Lời thoại số một",
        "2": "Lời thoại số hai",
    }

    captured_messages: list[dict[str, Any]] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_messages
        assert request.headers["authorization"] == "Bearer test-key"
        assert "/chat/completions" in str(request.url)
        body = json.loads(request.content)
        captured_messages = body["messages"]
        return httpx.Response(200, json=make_openai_chat_payload(json.dumps(mock_dict)))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            http_client=client,
            name="xkiro",
        )
        blocks = await provider.translate_page("aGVsbG8=", target_lang="vi", bubbles=test_bubbles)

    assert len(captured_messages) == 2
    assert "flat JSON object" in captured_messages[0]["content"]
    assert captured_messages[1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    assert len(blocks) == 2
    # Block 1 mapped accurately
    assert blocks[0].id == "1"
    assert blocks[0].box == (100, 600, 300, 850)
    assert blocks[0].polygon == [(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)]
    assert blocks[0].translated_text == "Lời thoại số một"
    assert blocks[0].confidence == 0.98

    # Block 2 mapped accurately
    assert blocks[1].id == "2"
    assert blocks[1].box == (500, 100, 700, 350)
    assert blocks[1].translated_text == "Lời thoại số hai"
    assert blocks[1].confidence == 0.95


@pytest.mark.asyncio
async def test_openai_compat_zero_bubbles_no_call() -> None:
    """When bubbles list is empty, return [] without making network requests."""
    called = False

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, text="Should not be called")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="test-key", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=[])

    assert called is False
    assert blocks == []


@pytest.mark.asyncio
async def test_openai_compat_code_fence_and_dict_wrapper(test_bubbles: list[DetectedBubble]) -> None:
    """Markdown code fences and wrapped JSON should be parsed defensively."""
    fenced_json = """```json
{
  "translations": {
    "1": "Bản dịch 1",
    "2": "Bản dịch 2"
  }
}
```"""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openai_chat_payload(fenced_json))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="test-key", http_client=client)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=test_bubbles)

    assert len(blocks) == 2
    assert blocks[0].translated_text == "Bản dịch 1"
    assert blocks[1].translated_text == "Bản dịch 2"


@pytest.mark.asyncio
async def test_openai_compat_refusal_and_safety(test_bubbles: list[DetectedBubble]) -> None:
    """Textual refusal or finish_reason='content_filter' raises ContentSafetyBlockedError."""
    # Textual refusal
    async def refusal_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openai_chat_payload("I cannot assist with this request."))

    transport = httpx.MockTransport(refusal_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="test-key", http_client=client)
        with pytest.raises(ContentSafetyBlockedError):
            await provider.translate_page("aGVsbG8=", bubbles=test_bubbles)

    # Content filter finish reason
    async def filter_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openai_chat_payload("", finish_reason="content_filter"))

    transport_filter = httpx.MockTransport(filter_handler)
    async with httpx.AsyncClient(transport=transport_filter) as client:
        provider = OpenAICompatibleProvider(api_key="test-key", http_client=client)
        with pytest.raises(ContentSafetyBlockedError):
            await provider.translate_page("aGVsbG8=", bubbles=test_bubbles)


@pytest.mark.asyncio
async def test_openai_compat_retry_and_rate_limit(test_bubbles: list[DetectedBubble]) -> None:
    """Retry on 429 backoff and raise RateLimitExceededError when retries are exhausted."""
    attempts = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})
        return httpx.Response(200, json=make_openai_chat_payload(json.dumps({"1": "ok", "2": "ok 2"})))

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key="test-key", http_client=client, max_retries=2)
        blocks = await provider.translate_page("aGVsbG8=", bubbles=test_bubbles)

    assert attempts == 2
    assert len(blocks) == 2
    assert blocks[0].translated_text == "ok"


@pytest.mark.asyncio
async def test_openai_compat_errors(test_bubbles: list[DetectedBubble]) -> None:
    """Authentication, server error, and timeout exceptions."""
    # 401
    async def h_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(h_401)) as client:
        provider = OpenAICompatibleProvider(api_key="bad-key", http_client=client)
        with pytest.raises(UpstreamAuthenticationError):
            await provider.translate_page("aGVsbG8=", bubbles=test_bubbles)

    # 500
    async def h_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(h_500)) as client:
        provider = OpenAICompatibleProvider(api_key="test-key", http_client=client)
        with pytest.raises(UpstreamExecutionError):
            await provider.translate_page("aGVsbG8=", bubbles=test_bubbles)

    # Timeout
    async def h_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(h_timeout)) as client:
        provider = OpenAICompatibleProvider(api_key="test-key", http_client=client)
        with pytest.raises(UpstreamTimeoutError):
            await provider.translate_page("aGVsbG8=", bubbles=test_bubbles)
