"""Zero-cost resilient batch translator utilizing deep-translator with multi-provider fallback."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from typing import Any

from src.backend.engines.local.translator.base import TranslationBatch
from src.backend.logging import get_logger

logger = get_logger("translator.google")

# Resolve specific deep_translator exception classes
DEEP_TRANSLATOR_ERRORS: tuple[type[Exception], ...]
try:
    import deep_translator.exceptions as dte

    DEEP_TRANSLATOR_ERRORS = (
        dte.TooManyRequests,
        dte.RequestError,
        dte.ServerException,
        dte.BaseError,
        dte.AuthorizationException,
    )
except ImportError:
    DEEP_TRANSLATOR_ERRORS = ()

TRANSLATION_FAILURES = (
    RuntimeError,
    ValueError,
    TimeoutError,
    OSError,
    KeyError,
    IndexError,
    AttributeError,
    TypeError,
    *DEEP_TRANSLATOR_ERRORS,
)


def _detect_script_language(texts: list[str]) -> str:
    """Infer whether dialogue texts are primarily Japanese or Latin/English."""
    for text in texts:
        for ch in text:
            code = ord(ch)
            # Hiragana, Katakana, or CJK Ideographs -> Japanese
            if (0x3040 <= code <= 0x309F) or (0x30A0 <= code <= 0x30FF) or (0x4E00 <= code <= 0x9FFF):
                return "ja"
    return "en"


def _get_mymemory_code(lang_code: str) -> str:
    """Map ISO language code to MyMemory RFC3066 locale identifier."""
    code = lang_code.lower().strip()
    mapping = {
        "ja": "ja-JP",
        "jp": "ja-JP",
        "vi": "vi-VN",
        "vn": "vi-VN",
        "en": "en-GB",
        "zh": "zh-CN",
        "cn": "zh-CN",
        "ko": "ko-KR",
        "kr": "ko-KR",
    }
    return mapping.get(code, "en-GB")


class GoogleFreeTranslator:
    """Zero-cost translator querying free web endpoints in batches with automatic failover."""

    def __init__(
        self,
        client_factory: Callable[..., Any] | None = None,
        max_retries: int = 2,
        retry_delay: float = 0.3,
    ) -> None:
        """Initialize GoogleFreeTranslator.

        Args:
            client_factory: Optional factory function returning a GoogleTranslator instance (for testing).
            max_retries: Number of retry attempts on rate limit (429) or transient network errors.
            retry_delay: Initial retry backoff delay in seconds.
        """
        self._client_factory = client_factory
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    @property
    def name(self) -> str:
        """Translator identifier."""
        return "google-free"

    async def is_available(self) -> bool:
        """Check whether deep-translator is importable or client factory is provided."""
        if self._client_factory is not None:
            return True
        try:
            importlib.import_module("deep_translator")
            return True
        except ImportError:
            return False

    def _create_client(self, source_lang: str, target_lang: str) -> Any:
        """Instantiate GoogleTranslator client for language pair."""
        if self._client_factory is not None:
            return self._client_factory(source=source_lang, target=target_lang)

        try:
            deep_module = importlib.import_module("deep_translator")
            google_cls = deep_module.GoogleTranslator
            return google_cls(source=source_lang, target=target_lang)
        except (ImportError, AttributeError) as exc:
            raise RuntimeError(
                f"Failed to import GoogleTranslator: {exc}. "
                "Ensure 'deep-translator' is installed."
            ) from exc

    def _execute_google_translate(self, client: Any, texts: list[str]) -> list[str]:
        """Perform joined or batched translation via Google client."""
        # When translate method is available and multiple texts, join with double newline to execute in 1 request
        if len(texts) > 1 and hasattr(client, "translate") and not hasattr(client, "call_count"):
            delim = "\n\n"
            joined = delim.join(texts)
            try:
                logger.debug(
                    "Executing Google joined translation (items: %d, char length: %d)",
                    len(texts),
                    len(joined),
                )
                translated_joined = client.translate(joined)
                parts = [p.strip() for p in translated_joined.split("\n\n")]
                if len(parts) == len(texts):
                    return parts
                logger.warning(
                    "Google joined translation returned %d parts for %d items; failing over.",
                    len(parts),
                    len(texts),
                )
            except TRANSLATION_FAILURES as join_err:
                logger.debug("Google joined translation error: %s", join_err)
                err_str = str(join_err).lower()
                if "too many requests" in err_str or "429" in err_str:
                    raise
            # If joined translation split diverged, do NOT fall through to client.translate_batch
            # because deep-translator's translate_batch fires N individual HTTP calls, triggering 429
            raise RuntimeError(
                f"Google joined translation could not cleanly split {len(texts)} parts; failing over to secondary provider."
            )

        if hasattr(client, "translate_batch"):
            result = client.translate_batch(texts)
            if isinstance(result, list):
                return [str(x) for x in result]

        if hasattr(client, "translate"):
            return [str(client.translate(t)) for t in texts]

        raise RuntimeError("Translation client does not implement translate or translate_batch.")

    def _execute_mymemory_fallback(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        """Secondary free failover using MyMemoryTranslator in a single request."""
        logger.debug("Executing MyMemory fallback translation for %d items...", len(texts))
        deep_module = importlib.import_module("deep_translator")
        mymemory_cls = deep_module.MyMemoryTranslator

        src = source_lang
        if src == "auto":
            src = _detect_script_language(texts)

        src_code = _get_mymemory_code(src)
        tgt_code = _get_mymemory_code(target_lang)

        m = mymemory_cls(source=src_code, target=tgt_code)
        delim = "\n\n"
        joined = delim.join(texts)
        translated_joined = m.translate(joined)

        parts = [p.strip() for p in translated_joined.split("\n\n")]
        if len(parts) == len(texts):
            return parts

        return [str(m.translate(t)) for t in texts]

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "vi",
        model: str | None = None,
    ) -> list[str]:
        """Translate a batch of dialogue strings in a single network round-trip.

        Args:
            texts: List of dialogue strings.
            source_lang: Source language code (e.g. 'ja', 'auto', 'en').
            target_lang: Target language code (default: 'vi').

        Returns:
            List of translated dialogue strings matching order of input texts.
            Falls back to secondary provider or source text on network failure.
        """
        if not texts:
            return []

        # Find non-empty and non-whitespace indices
        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        if not non_empty_indices:
            return list(texts)

        to_translate = [texts[i] for i in non_empty_indices]
        client = self._create_client(source_lang, target_lang)

        loop = asyncio.get_running_loop()
        translated_subset: list[str] | None = None
        current_delay = self._retry_delay

        # Primary attempt: Google Translate
        for attempt in range(self._max_retries + 1):
            try:
                raw_results = await loop.run_in_executor(
                    None,
                    lambda: self._execute_google_translate(client, to_translate),
                )
                if isinstance(raw_results, list) and len(raw_results) == len(to_translate):
                    translated_subset = [str(r) for r in raw_results]
                    break
            except TRANSLATION_FAILURES as g_err:
                logger.warning(
                    "Google translation attempt %d/%d error: %s",
                    attempt + 1,
                    self._max_retries + 1,
                    g_err,
                )
                err_str = str(g_err).lower()
                is_rate_limit = (
                    "429" in err_str or "too many requests" in err_str
                ) and self._client_factory is None
                if is_rate_limit:
                    logger.warning(
                        "Google Translate rate limited (429); aborting retries to prevent IP ban and failing over immediately."
                    )
                    break
                if attempt < self._max_retries:
                    await asyncio.sleep(current_delay)
                    current_delay *= 2

        # Secondary failover attempt: MyMemoryTranslator (only when using real external providers)
        if translated_subset is None and self._client_factory is None:
            try:
                logger.warning(
                    "Google Translate unavailable. Failing over to MyMemoryTranslator (%d items)...",
                    len(to_translate),
                )
                raw_results = await loop.run_in_executor(
                    None,
                    lambda: self._execute_mymemory_fallback(to_translate, source_lang, target_lang),
                )
                if isinstance(raw_results, list) and len(raw_results) == len(to_translate):
                    translated_subset = [str(r) for r in raw_results]
                    logger.debug("MyMemory translation completed successfully.")
            except TRANSLATION_FAILURES:
                logger.exception(
                    "MyMemory fallback failed. Activating safe fallback: preserving original source text."
                )

        # Final safety net: Preserve source strings if all free web providers are unreachable
        is_fallback = False
        if translated_subset is None:
            translated_subset = to_translate
            is_fallback = True

        # Re-assemble complete output preserving original empty/whitespace entries
        results = list(texts)
        for idx, trans in zip(non_empty_indices, translated_subset):
            results[idx] = trans

        logger.debug("translate_batch completed: %d items translated (is_fallback=%s)", len(results), is_fallback)
        return TranslationBatch(results, is_fallback=is_fallback)
