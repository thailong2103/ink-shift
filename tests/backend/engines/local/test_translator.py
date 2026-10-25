"""Unit tests for swappable local translation adapters (GoogleFreeTranslator & LLMTextTranslator)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.backend.engines.local.translator.base import BaseTextTranslator
from src.backend.engines.local.translator.google_free import GoogleFreeTranslator
from src.backend.engines.local.translator.llm_text import LLMTextTranslator

# ---------------------------------------------------------------------------
# GoogleFreeTranslator Tests
# ---------------------------------------------------------------------------


class MockGoogleTranslatorClient:
    """Mock client simulating deep_translator.GoogleTranslator."""

    def __init__(self, translation_map: dict[str, str] | None = None, should_fail: bool = False) -> None:
        self.translation_map = translation_map or {}
        self.should_fail = should_fail
        self.call_count = 0

    def translate_batch(self, batch: list[str]) -> list[str]:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError("429 Too Many Requests: Rate limit exceeded")
        return [self.translation_map.get(t, f"vi_{t}") for t in batch]


@pytest.mark.asyncio
async def test_google_free_protocol_conformance() -> None:
    """GoogleFreeTranslator must conform to BaseTextTranslator protocol."""
    translator = GoogleFreeTranslator(client_factory=lambda **kwargs: MockGoogleTranslatorClient())
    assert isinstance(translator, BaseTextTranslator)
    assert translator.name == "google-free"
    assert await translator.is_available() is True


@pytest.mark.asyncio
async def test_google_free_default_import_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default client creation should instantiate deep_translator or raise RuntimeError if missing."""
    default_translator = GoogleFreeTranslator()
    assert await default_translator.is_available() is True
    client = default_translator._create_client("en", "vi")
    assert client is not None

    def failing_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "deep_translator":
            raise ImportError("deep_translator not installed")
        import importlib
        return importlib.__import__(name, *args, **kwargs)

    import importlib
    monkeypatch.setattr(importlib, "import_module", failing_import)

    missing_translator = GoogleFreeTranslator()
    assert await missing_translator.is_available() is False
    with pytest.raises(RuntimeError) as exc_info:
        missing_translator._create_client("en", "vi")
    assert "Failed to import GoogleTranslator" in str(exc_info.value)


@pytest.mark.asyncio
async def test_google_free_translate_batch_success() -> None:
    """GoogleFreeTranslator should translate batch of texts in a single call."""
    mock_client = MockGoogleTranslatorClient({
        "こんにちは": "Xin chào",
        "元気ですか？": "Bạn có khỏe không?",
    })
    translator = GoogleFreeTranslator(client_factory=lambda **kwargs: mock_client)

    input_texts = ["こんにちは", "元気ですか？"]
    results = await translator.translate_batch(input_texts, source_lang="ja", target_lang="vi")

    assert results == ["Xin chào", "Bạn có khỏe không?"]
    assert mock_client.call_count == 1


@pytest.mark.asyncio
async def test_google_free_empty_and_whitespace_handling() -> None:
    """Empty and whitespace strings should be preserved without invoking translation client."""
    mock_client = MockGoogleTranslatorClient({"Hello": "Xin chào"})
    translator = GoogleFreeTranslator(client_factory=lambda **kwargs: mock_client)

    input_texts = ["", "   ", "Hello", "\n\t"]
    results = await translator.translate_batch(input_texts, source_lang="en", target_lang="vi")

    assert results == ["", "   ", "Xin chào", "\n\t"]
    assert mock_client.call_count == 1


@pytest.mark.asyncio
async def test_google_free_empty_batch() -> None:
    """Empty batch returns empty list immediately."""
    mock_client = MockGoogleTranslatorClient()
    translator = GoogleFreeTranslator(client_factory=lambda **kwargs: mock_client)

    results = await translator.translate_batch([], source_lang="en", target_lang="vi")
    assert results == []
    assert mock_client.call_count == 0


@pytest.mark.asyncio
async def test_google_free_retry_and_fallback_to_source() -> None:
    """On repeated rate limits or network failures, translator falls back to source text."""
    mock_client = MockGoogleTranslatorClient(should_fail=True)
    translator = GoogleFreeTranslator(
        client_factory=lambda **kwargs: mock_client,
        max_retries=2,
        retry_delay=0.01,
    )

    input_texts = ["Sample dialogue 1", "Sample dialogue 2"]
    results = await translator.translate_batch(input_texts, source_lang="en", target_lang="vi")

    # Retried max_retries + 1 times and safely returned source texts
    assert mock_client.call_count == 3
    assert results == input_texts


# ---------------------------------------------------------------------------
# LLMTextTranslator Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_text_protocol_conformance() -> None:
    """LLMTextTranslator must conform to BaseTextTranslator protocol."""
    translator = LLMTextTranslator(api_key="test_key", provider="gemini")
    assert isinstance(translator, BaseTextTranslator)
    assert translator.name == "llm-text"


@pytest.mark.asyncio
async def test_llm_text_availability() -> None:
    """is_available reflects presence of API keys."""
    unavail = LLMTextTranslator(api_key="", provider="gemini")
    assert await unavail.is_available() is False

    avail = LLMTextTranslator(api_key="valid_key", provider="gemini")
    assert await avail.is_available() is True


@pytest.mark.asyncio
async def test_llm_text_gemini_translation() -> None:
    """LLMTextTranslator correctly queries Gemini endpoint with pure text and parses JSON array."""
    gemini_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(["Xin chào", "Tôi là Shinichi"]),
                        }
                    ]
                }
            }
        ]
    }

    recorded_request: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_request["method"] = request.method
        recorded_request["url"] = str(request.url)
        recorded_request["body"] = json.loads(request.content)
        return httpx.Response(200, json=gemini_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        translator = LLMTextTranslator(
            api_key="gemini_test_key",
            model="gemini-2.0-flash",
            provider="gemini",
            http_client=client,
        )

        input_texts = ["こんにちは", "俺は新一だ"]
        results = await translator.translate_batch(input_texts, source_lang="ja", target_lang="vi")

        assert results == ["Xin chào", "Tôi là Shinichi"]
        # Verify no images were sent
        assert "inline_data" not in json.dumps(recorded_request["body"])
        assert "contents" in recorded_request["body"]


@pytest.mark.asyncio
async def test_llm_text_openai_compat_translation() -> None:
    """LLMTextTranslator correctly queries OpenAI/xKiro endpoint with pure text and parses JSON."""
    openai_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(["Chào buổi sáng", "Đi thôi"]),
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=openai_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        translator = LLMTextTranslator(
            api_key="custom_test_key",
            model="custom-text-model",
            provider="custom",
            http_client=client,
        )

        input_texts = ["おはよう", "行こうぜ"]
        results = await translator.translate_batch(input_texts, source_lang="ja", target_lang="vi")
        assert results == ["Chào buổi sáng", "Đi thôi"]


@pytest.mark.asyncio
async def test_llm_text_fallback_on_error() -> None:
    """When upstream returns 500 or network fails, LLMTextTranslator falls back to source text."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "Internal server error"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        translator = LLMTextTranslator(
            api_key="key",
            provider="gemini",
            http_client=client,
            max_retries=1,
            retry_delay=0.01,
        )

        input_texts = ["Text 1", "Text 2"]
        results = await translator.translate_batch(input_texts, source_lang="en", target_lang="vi")
        assert results == input_texts


@pytest.mark.asyncio
async def test_llm_text_empty_and_whitespace_batch() -> None:
    """Empty and whitespace strings should be preserved without querying LLM."""
    translator = LLMTextTranslator(api_key="key", provider="gemini")
    assert await translator.translate_batch([]) == []

    results = await translator.translate_batch(["", "   ", "\n"])
    assert results == ["", "   ", "\n"]


def test_llm_text_custom_naming_and_provider_defaults() -> None:
    """LLMTextTranslator respects custom name parameter and falls back cleanly."""
    gemini_custom = LLMTextTranslator(provider="gemini", name="llm-gemini")
    assert gemini_custom.name == "llm-gemini"

    qwen_custom = LLMTextTranslator(provider="xkiro", name="llm-qwen")
    assert qwen_custom.name == "llm-qwen"

    default_name = LLMTextTranslator(provider="gemini")
    assert default_name.name == "llm-text"

