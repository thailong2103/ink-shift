"""Translator Registry coordinating swappable text translators for Local Engine."""

from __future__ import annotations

from src.backend.config import Settings
from src.backend.engines.local.translator.base import BaseTextTranslator
from src.backend.logging import get_logger

logger = get_logger("local.translator.registry")


class TranslatorNotFoundError(KeyError):
    """Raised when a requested text translator is not registered."""


class TranslatorRegistry:
    """Registry coordinating available text translators (GoogleFree, LLMText, etc.)."""

    def __init__(self, default_translator_name: str | None = None) -> None:
        settings = Settings()
        configured_default = getattr(settings, "inkshift_local_translator", "google-free")
        self._default_name = (
            default_translator_name if default_translator_name is not None else configured_default
        ) or "google-free"
        self._translators: dict[str, BaseTextTranslator] = {}
        # Convenient aliases
        self._aliases: dict[str, str] = {
            "google": "google-free",
            "google_free": "google-free",
            "gemini": "llm-google",
            "llm-gemini": "llm-google",
            "openai": "llm-openai",
            "anthropic": "llm-anthropic",
            "custom": "llm-custom",
            "qwen": "llm-custom",
            "xkiro": "llm-custom",
            "llm-qwen": "llm-custom",
            "llm": "llm-text",
            "llm_text": "llm-text",
        }

    @property
    def default_name(self) -> str:
        """Name of the default text translator."""
        return self._default_name

    def register(self, name: str, translator: BaseTextTranslator) -> None:
        """Register a text translator under a normalized name."""
        key = name.strip().lower()
        self._translators[key] = translator
        logger.debug(
            "Registered local translator: '%s' (%s)", key, translator.__class__.__name__
        )

    def register_alias(self, alias: str, target_name: str) -> None:
        """Register an alias pointing to a registered translator name."""
        self._aliases[alias.strip().lower()] = target_name.strip().lower()

    def get(self, name: str | None = None) -> BaseTextTranslator:
        """Retrieve a translator by name or return the configured default.

        Args:
            name: Translator name or alias ('google-free', 'llm-google', 'llm-openai', 'llm-anthropic', 'llm-custom', etc.).

        Returns:
            Registered BaseTextTranslator instance.

        Raises:
            TranslatorNotFoundError: If requested name or default is not registered.
        """
        raw_name = name if (name and name.strip()) else self._default_name
        lookup_name = raw_name.strip().lower()

        # Check alias first
        resolved_name = self._aliases.get(lookup_name, lookup_name)

        if resolved_name in self._translators:
            return self._translators[resolved_name]

        if lookup_name in self._translators:
            return self._translators[lookup_name]

        # Bidirectional fallback between new canonical names and legacy names
        pair_mappings = {
            "llm-google": "llm-gemini",
            "llm-gemini": "llm-google",
            "llm-openai": "llm-qwen",
            "llm-custom": "llm-qwen",
            "llm-qwen": "llm-custom",
        }
        fallback_target = pair_mappings.get(resolved_name)
        if fallback_target and fallback_target in self._translators:
            return self._translators[fallback_target]

        # Fallback for generic 'llm-text' when provider-specific translator is registered
        if resolved_name == "llm-text" or lookup_name == "llm-text":
            for candidate in ("llm-google", "llm-gemini", "llm-openai", "llm-anthropic", "llm-custom", "llm-qwen"):
                if candidate in self._translators:
                    return self._translators[candidate]

        # Backwards compatibility: if provider was requested but only generic 'llm-text' is registered
        if lookup_name in ("qwen", "gemini", "xkiro", "openai", "anthropic", "custom", "google") and "llm-text" in self._translators:
            return self._translators["llm-text"]

        avail = ", ".join(sorted(self._translators.keys()))
        raise TranslatorNotFoundError(
            f"Local translator '{lookup_name}' is not registered. Available: [{avail}]"
        )

    async def is_available(self, name: str | None = None) -> bool:
        """Check whether the requested translator is registered and available."""
        try:
            translator = self.get(name)
            return await translator.is_available()
        except TranslatorNotFoundError:
            return False

    def list_translators(self) -> list[str]:
        """List all canonical registered translator identifiers."""
        return sorted(self._translators.keys())
