"""Unit tests for AnthropicProvider (Claude 3 & 3.5) using Set-of-Marks."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.backend.detection.base import DetectedBubble
from src.backend.engines.cloud.anthropic import AnthropicProvider
from src.backend.engines.cloud.exceptions import (
    ContentSafetyBlockedError,
    UpstreamAuthenticationError,
    UpstreamTimeoutError,
)


def make_anthropic_message_payload(content: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    """Helper to synthesize valid Anthropic Messages API response payload."""
    return {
        "id": "msg_test_123",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-5-sonnet-20241022",
        "content": [
            {
                "type": "text",
                "text": content,
            }
        ],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 100, "output_tokens": 50},
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


@pytest.fixture
def sample_image_b64() -> str:
    """1x1 transparent PNG in base64."""
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )


@pytest.mark.asyncio
async def test_anthropic_som_flow(
    test_bubbles: list[DetectedBubble],
    sample_image_b64: str,
) -> None:
    """AnthropicProvider should send marked image and map translations to ground-truth YOLO11 coordinates."""
    mock_dict = {
        "1": "Chào buổi sáng!",
        "2": "Cậu khỏe không?",
    }

    captured_requests: list[httpx.Request] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "claude-3-5-sonnet-20241022"
        assert body["messages"][0]["content"][0]["type"] == "image"
        assert request.headers["x-api-key"] == "test-anthropic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"

        resp_payload = make_anthropic_message_payload(json.dumps(mock_dict))
        return httpx.Response(200, json=resp_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AnthropicProvider(
            api_key="test-anthropic-key",
            http_client=client,
        )

        assert provider.name == "anthropic"
        assert provider.default_model == "claude-3-5-sonnet-20241022"
        assert await provider.is_available() is True

        blocks = await provider.translate_page(
            image_base64=sample_image_b64,
            target_lang="vi",
            bubbles=test_bubbles,
        )

        assert len(blocks) == 2
        assert blocks[0].id == "1"
        assert blocks[0].translated_text == "Chào buổi sáng!"
        assert blocks[0].box == (100, 600, 300, 850)
        assert blocks[1].id == "2"
        assert blocks[1].translated_text == "Cậu khỏe không?"
        assert blocks[1].box == (500, 100, 700, 350)


@pytest.mark.asyncio
async def test_anthropic_missing_key_raises_error(
    sample_image_b64: str,
    test_bubbles: list[DetectedBubble],
) -> None:
    """Invoking translation without an API key raises UpstreamAuthenticationError."""
    provider = AnthropicProvider(api_key="")
    assert await provider.is_available() is False

    with pytest.raises(UpstreamAuthenticationError) as exc_info:
        await provider.translate_page(
            image_base64=sample_image_b64,
            bubbles=test_bubbles,
        )
    assert "Anthropic API key is not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_anthropic_empty_bubbles_returns_empty(sample_image_b64: str) -> None:
    """Empty bubble list returns [] immediately without making network calls."""
    provider = AnthropicProvider(api_key="valid-key")
    res = await provider.translate_page(
        image_base64=sample_image_b64,
        bubbles=[],
    )
    assert res == []


@pytest.mark.asyncio
async def test_anthropic_refusal_raises_safety_error(
    test_bubbles: list[DetectedBubble],
    sample_image_b64: str,
) -> None:
    """Refusal stop_reason raises ContentSafetyBlockedError."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        resp_payload = make_anthropic_message_payload("", stop_reason="refusal")
        return httpx.Response(200, json=resp_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AnthropicProvider(api_key="valid-key", http_client=client)
        with pytest.raises(ContentSafetyBlockedError) as exc:
            await provider.translate_page(image_base64=sample_image_b64, bubbles=test_bubbles)
        assert "refused by Anthropic safety policy" in str(exc.value)


@pytest.mark.asyncio
async def test_anthropic_rate_limit_backoff(
    test_bubbles: list[DetectedBubble],
    sample_image_b64: str,
) -> None:
    """HTTP 429 triggers exponential backoff retry up to max_retries."""
    attempts = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(429, text="Rate limit exceeded")
        return httpx.Response(
            200,
            json=make_anthropic_message_payload(json.dumps({"1": "Thành công"})),
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AnthropicProvider(api_key="valid-key", http_client=client, max_retries=2)
        blocks = await provider.translate_page(image_base64=sample_image_b64, bubbles=test_bubbles[:1])
        assert attempts == 2
        assert len(blocks) == 1
        assert blocks[0].translated_text == "Thành công"


@pytest.mark.asyncio
async def test_anthropic_401_authentication_error(
    test_bubbles: list[DetectedBubble],
    sample_image_b64: str,
) -> None:
    """HTTP 401 raises UpstreamAuthenticationError immediately."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Invalid x-api-key")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AnthropicProvider(api_key="bad-key", http_client=client)
        with pytest.raises(UpstreamAuthenticationError) as exc:
            await provider.translate_page(image_base64=sample_image_b64, bubbles=test_bubbles)
        assert "authentication failed (HTTP 401)" in str(exc.value)


@pytest.mark.asyncio
async def test_anthropic_timeout_raises_timeout_error(
    test_bubbles: list[DetectedBubble],
    sample_image_b64: str,
) -> None:
    """Timeout exception raises UpstreamTimeoutError."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AnthropicProvider(api_key="valid-key", http_client=client)
        with pytest.raises(UpstreamTimeoutError):
            await provider.translate_page(image_base64=sample_image_b64, bubbles=test_bubbles)
