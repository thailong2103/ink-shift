"""Unit tests for TranslatorRegistry."""

from __future__ import annotations

import pytest

from src.backend.engines.local.translator.registry import (
    TranslatorNotFoundError,
    TranslatorRegistry,
)


class MockTextTranslator:
    """Mock implementation of BaseTextTranslator protocol."""

    def __init__(self, name: str = "mock-translator", available: bool = True) -> None:
        self._name = name
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    async def is_available(self) -> bool:
        return self._available

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model: str | None = None,
    ) -> list[str]:
        return [f"trans:{t}" for t in texts]


def test_translator_registry_registration_and_get() -> None:
    """Registry should store and retrieve translators by name."""
    registry = TranslatorRegistry(default_translator_name="google-free")
    t1 = MockTextTranslator(name="google-free")
    t2 = MockTextTranslator(name="llm-text")

    registry.register("google-free", t1)
    registry.register("llm-text", t2)

    assert registry.get("google-free") is t1
    assert registry.get("llm-text") is t2
    assert registry.list_translators() == ["google-free", "llm-text"]


def test_translator_registry_default_fallback() -> None:
    """Registry should return default translator when name is None or whitespace."""
    registry = TranslatorRegistry(default_translator_name="google-free")
    t1 = MockTextTranslator(name="google-free")
    registry.register("google-free", t1)

    assert registry.get() is t1
    assert registry.get(None) is t1
    assert registry.get("") is t1
    assert registry.get("   ") is t1


def test_translator_registry_aliases() -> None:
    """Registry should resolve configured aliases correctly."""
    registry = TranslatorRegistry()
    t_google = MockTextTranslator(name="google-free")
    t_llm = MockTextTranslator(name="llm-text")

    registry.register("google-free", t_google)
    registry.register("llm-text", t_llm)

    assert registry.get("google") is t_google
    assert registry.get("google_free") is t_google
    assert registry.get("llm") is t_llm
    assert registry.get("qwen") is t_llm

    # Custom alias
    registry.register_alias("fast", "google-free")
    assert registry.get("fast") is t_google


def test_translator_registry_unregistered_raises() -> None:
    """Registry should raise TranslatorNotFoundError when requested name is not registered."""
    registry = TranslatorRegistry()
    with pytest.raises(TranslatorNotFoundError) as exc_info:
        registry.get("unknown-translator")
    assert "unknown-translator" in str(exc_info.value)


@pytest.mark.asyncio
async def test_translator_registry_is_available() -> None:
    """is_available should delegate to translator readiness or return False on unknown."""
    registry = TranslatorRegistry()
    avail_t = MockTextTranslator(available=True)
    unavail_t = MockTextTranslator(available=False)

    registry.register("t-avail", avail_t)
    registry.register("t-unavail", unavail_t)

    assert await registry.is_available("t-avail") is True
    assert await registry.is_available("t-unavail") is False
    assert await registry.is_available("nonexistent") is False


def test_translator_registry_llm_gemini_and_qwen_aliases() -> None:
    """Registry resolves gemini, qwen, xkiro, openai aliases to their canonical LLM translators."""
    registry = TranslatorRegistry()
    t_gemini = MockTextTranslator(name="llm-gemini")
    t_qwen = MockTextTranslator(name="llm-qwen")

    registry.register("llm-gemini", t_gemini)
    registry.register("llm-qwen", t_qwen)

    assert registry.get("gemini") is t_gemini
    assert registry.get("llm-gemini") is t_gemini
    assert registry.get("qwen") is t_qwen
    assert registry.get("xkiro") is t_qwen
    assert registry.get("openai") is t_qwen
    assert registry.get("llm-qwen") is t_qwen

    # Generic llm-text fallback to registered LLM
    assert registry.get("llm-text") is t_gemini
    assert registry.get("llm") is t_gemini

