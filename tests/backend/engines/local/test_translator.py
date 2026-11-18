"""Unit tests for swappable local translation adapters (GoogleFreeTranslator & LLMTextTranslator)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

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



@pytest.mark.asyncio
async def test_llm_text_http_409_concurrency_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLMTextTranslator recognizes HTTP 409 conflict, performs adaptive backoff, and recovers successfully."""
    call_count = 0
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    openai_conflict_payload = {
        "error": {
            "message": "A duplicate request is already being processed - please try again.",
            "type": "invalid_request_error",
            "code": "conflict",
        }
    }
    openai_success_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(["Chào buổi sáng", "Thế giới"]),
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(409, json=openai_conflict_payload)
        return httpx.Response(200, json=openai_success_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        translator = LLMTextTranslator(
            api_key="test_key",
            model="qwen/qwen3.8-max:free",
            provider="custom",
            http_client=client,
            max_retries=2,
        )

        input_texts = ["Good morning", "World"]
        results = await translator.translate_batch(input_texts, source_lang="en", target_lang="vi")

    assert results == ["Chào buổi sáng", "Thế giới"]
    assert call_count == 2
    # Sleep duration for 409 should be adaptive (>= 2.0s)
    assert len(sleep_calls) >= 1
    assert sleep_calls[0] >= 2.0


@pytest.mark.asyncio
async def test_llm_text_single_concurrency_serialization() -> None:
    """Free-tier models with :free suffix serialize concurrent requests through in-process lock."""
    active_requests = 0
    max_concurrent = 0

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_requests, max_concurrent
        active_requests += 1
        max_concurrent = max(max_concurrent, active_requests)
        # Yield to event loop to allow concurrency race if not locked
        await asyncio.sleep(0.01)
        active_requests -= 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(["Dịch xong"])}}]
            },
        )

    transport = httpx.MockTransport(slow_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        translator = LLMTextTranslator(
            api_key="test_key",
            model="meta-llama/llama-3.3-70b:free",
            provider="custom",
            http_client=client,
        )

        # Launch 3 simultaneous requests
        task1 = asyncio.create_task(translator.translate_batch(["Text 1"], source_lang="en", target_lang="vi"))
        task2 = asyncio.create_task(translator.translate_batch(["Text 2"], source_lang="en", target_lang="vi"))
        task3 = asyncio.create_task(translator.translate_batch(["Text 3"], source_lang="en", target_lang="vi"))

        res1, res2, res3 = await asyncio.gather(task1, task2, task3)

        assert res1 == ["Dịch xong"]
        assert res2 == ["Dịch xong"]
        assert res3 == ["Dịch xong"]
        # Concurrency was strictly serialized to 1!
        assert max_concurrent == 1


def test_llm_text_build_prompt_into_target_without_forced_source() -> None:
    """Prompt must instruct translation into target language without restricting source language."""
    translator = LLMTextTranslator(provider="custom")
    prompt_vi = translator._build_prompt(["Hello"], source_lang="en", target_lang="vi")
    assert "Translate the following list of dialogue strings into natural Vietnamese." in prompt_vi
    assert "from en" not in prompt_vi

    prompt_custom = translator._build_prompt(
        ["Hola"],
        source_lang="auto",
        target_lang="vi",
        custom_prompt="Keep names original",
    )
    assert "Translate the following list of dialogue strings into natural Vietnamese." in prompt_custom
    assert "USER TRANSLATION STYLE & GLOSSARY GUIDELINES" in prompt_custom
    assert "Keep names original" in prompt_custom


def test_llm_text_dual_role_prompt_separation() -> None:
    """System prompt contains meta-instructions, user prompt contains data-only JSON array."""
    translator = LLMTextTranslator(provider="custom")
    sys_prompt = translator._build_system_prompt(target_lang="vi", custom_prompt="Tone: dramatic")
    assert "You are a professional manga dialogue translator." in sys_prompt
    assert "Translate all dialogue strings into natural Vietnamese" in sys_prompt
    assert "Return ONLY a valid JSON array" in sys_prompt
    assert "Tone: dramatic" in sys_prompt

    user_prompt = translator._build_user_prompt(["Hello", "World"])
    assert user_prompt == json.dumps(["Hello", "World"], ensure_ascii=False)
    # Ensure no English instructions leaked into the user message
    assert "translator" not in user_prompt
    assert "dialogue" not in user_prompt


def test_llm_text_parse_json_response_with_regex_recovery() -> None:
    """_parse_json_response must safely parse direct JSON, markdown-fenced, and conversational prefixes."""
    translator = LLMTextTranslator(provider="custom")

    # 1. Standard valid JSON array
    assert translator._parse_json_response('["Xin chào", "Tạm biệt"]', 2) == ["Xin chào", "Tạm biệt"]

    # 2. Markdown-fenced JSON array
    markdown_str = "```json\n[\"Xin chào\", \"Tạm biệt\"]\n```"
    assert translator._parse_json_response(markdown_str, 2) == ["Xin chào", "Tạm biệt"]

    # 3. Conversational preamble (e.g. from Hy-MT2 or small LLMs)
    preamble_str = "Bạn là chuyên gia dịch thoại. Dưới đây là mảng JSON hợp lệ:\n[\"Xin chào\", \"Tạm biệt\"]"
    assert translator._parse_json_response(preamble_str, 2) == ["Xin chào", "Tạm biệt"]

    # 4. Conversational postscript
    postscript_str = "[\"Xin chào\", \"Tạm biệt\"]\nHy vọng bạn hài lòng với bản dịch!"
    assert translator._parse_json_response(postscript_str, 2) == ["Xin chào", "Tạm biệt"]

    # 5. Dict with array value
    dict_str = '{"translations": ["Xin chào", "Tạm biệt"]}'
    assert translator._parse_json_response(dict_str, 2) == ["Xin chào", "Tạm biệt"]

    # 6. Length mismatch returns None
    assert translator._parse_json_response('["Chỉ có 1 câu"]', 2) is None


@pytest.mark.asyncio
async def test_llm_text_provider_payload_standardization() -> None:
    """OpenAI, Gemini, and Anthropic adapters must send native system/user separated payloads."""
    recorded_openai: dict[str, Any] = {}
    recorded_gemini: dict[str, Any] = {}
    recorded_anthropic: dict[str, Any] = {}

    def openai_handler(req: httpx.Request) -> httpx.Response:
        recorded_openai["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(["Chào"])}}]})

    def gemini_handler(req: httpx.Request) -> httpx.Response:
        recorded_gemini["body"] = json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(["Chào"])}]}}]})

    def anthropic_handler(req: httpx.Request) -> httpx.Response:
        recorded_anthropic["body"] = json.loads(req.content)
        return httpx.Response(200, json={"content": [{"text": json.dumps(["Chào"])}]})

    # Test OpenAI-compatible adapter
    async with httpx.AsyncClient(transport=httpx.MockTransport(openai_handler)) as client:
        t_openai = LLMTextTranslator(provider="custom", http_client=client)
        res = await t_openai.translate_batch(["Hi"], target_lang="vi")
        assert res == ["Chào"]
        messages = recorded_openai["body"]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "manga dialogue translator" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == json.dumps(["Hi"], ensure_ascii=False)

    # Test Gemini adapter
    async with httpx.AsyncClient(transport=httpx.MockTransport(gemini_handler)) as client:
        t_gemini = LLMTextTranslator(provider="gemini", http_client=client)
        res = await t_gemini.translate_batch(["Hi"], target_lang="vi")
        assert res == ["Chào"]
        body = recorded_gemini["body"]
        assert "systemInstruction" in body
        assert "manga dialogue translator" in body["systemInstruction"]["parts"][0]["text"]
        assert body["contents"][0]["parts"][0]["text"] == json.dumps(["Hi"], ensure_ascii=False)

    # Test Anthropic adapter
    async with httpx.AsyncClient(transport=httpx.MockTransport(anthropic_handler)) as client:
        t_anthropic = LLMTextTranslator(provider="anthropic", http_client=client)
        res = await t_anthropic.translate_batch(["Hi"], target_lang="vi")
        assert res == ["Chào"]
        body = recorded_anthropic["body"]
        assert "system" in body
        assert "manga dialogue translator" in body["system"]
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][0]["content"] == json.dumps(["Hi"], ensure_ascii=False)


def test_llm_text_parse_json_response_strips_think_and_repairs_malformed() -> None:
    """_parse_json_response strips <think> tags and repairs trailing commas and unescaped inner quotes."""
    translator = LLMTextTranslator(provider="custom")

    think_wrapped = '<think>Analyzing tone...\nLet me translate [these].</think>\n["Xin chào", "Tạm biệt"]'
    assert translator._parse_json_response(think_wrapped, 2) == ["Xin chào", "Tạm biệt"]

    trailing_comma = '["Chào cậu", "Đi thôi",]'
    assert translator._parse_json_response(trailing_comma, 2) == ["Chào cậu", "Đi thôi"]

    unescaped_quotes = '["Anh ấy hét "Dừng lại!" rồi chạy", "Khoan đã!"]'
    assert translator._parse_json_response(unescaped_quotes, 2) == [
        'Anh ấy hét "Dừng lại!" rồi chạy',
        "Khoan đã!",
    ]


@pytest.mark.asyncio
async def test_llm_text_retries_with_count_constraint_and_recovers_partial_alignment() -> None:
    """When LLM mismatches element count, retries with reinforced constraint and recovers via partial alignment."""
    call_bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        call_bodies.append(json.loads(req.content))
        # Always return 2 items when 3 were requested (e.g. local MT model merged two short lines)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(["Câu một", "Câu hai và ba"])}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        translator = LLMTextTranslator(
            api_key="test_key",
            model="hy-mt2-7b-abliterated",
            provider="custom",
            http_client=client,
            max_retries=2,
            retry_delay=0.001,
        )
        results = await translator.translate_batch(
            ["Line 1", "Line 2", "Line 3"],
            source_lang="en",
            target_lang="vi",
        )

    # Should reinforce exact count on retry and stop after 2 attempts once partial recovery is available
    assert len(call_bodies) == 2
    assert "EXACTLY 3 elements" in call_bodies[1]["messages"][0]["content"]
    assert getattr(results, "is_fallback", False) is False
    assert len(results) == 3
    assert results[0] == "Câu một"
    assert results[1] == "Câu hai và ba"
    assert results[2] == "Line 3"

    # Also verify over-length alignment collapses extra tail elements cleanly
    def over_length_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(["Phần 1", "Phần 2a", "Phần 2b"])}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(over_length_handler)) as client:
        translator_over = LLMTextTranslator(
            api_key="test_key",
            model="hy-mt2-7b-abliterated",
            provider="custom",
            http_client=client,
            max_retries=1,
            retry_delay=0.001,
        )
        res_over = await translator_over.translate_batch(["Part 1", "Part 2"], target_lang="vi")
    assert getattr(res_over, "is_fallback", False) is False
    assert res_over == ["Phần 1", "Phần 2a Phần 2b"]


@pytest.mark.asyncio
async def test_llm_text_stops_retrying_on_timeout_exception() -> None:
    """TimeoutException logs ReadTimeout details and breaks immediately without retry storm."""
    call_count = 0

    def timeout_handler(req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("", request=req)

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        translator = LLMTextTranslator(
            api_key="test_key",
            model="hy-mt2-7b-abliterated",
            provider="custom",
            http_client=client,
            max_retries=2,
            retry_delay=0.001,
        )
        with patch("src.backend.engines.local.translator.llm_text.logger.warning") as mock_warn:
            results = await translator.translate_batch(["Timed out line"], target_lang="vi")

    assert call_count == 1
    assert getattr(results, "is_fallback", False) is True
    assert results == ["Timed out line"]
    logged = " ".join(str(call.args[0]) for call in mock_warn.call_args_list if call.args)
    assert "ReadTimeout" in logged


