"""Text-only LLM translator client reusing Module 3 configurations (Gemini and OpenAI/xKiro)."""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from src.backend.config import Settings
from src.backend.logging import format_logfmt, get_logger

logger = get_logger("translator.llm")


class LLMTextTranslator:
    """Text-only translation client querying LLMs without image transfer overhead."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        provider: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        retry_delay: float = 0.3,
        timeout_seconds: float = 15.0,
        name: str | None = None,
    ) -> None:
        """Initialize LLMTextTranslator with provider credentials.

        Args:
            api_key: Provider API key override.
            model: Model name override.
            base_url: Base API URL override.
            provider: Provider mode ('gemini' or 'xkiro' / 'openai').
            http_client: Optional httpx.AsyncClient instance.
            max_retries: Retry attempts on transient errors.
            retry_delay: Initial retry delay in seconds.
            timeout_seconds: HTTP request timeout.
            name: Optional translator identifier (defaults to 'llm-text').
        """
        settings = Settings()
        self._provider = provider if provider is not None else settings.inkshift_cloud_provider
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._timeout_seconds = timeout_seconds
        self._client = http_client
        self._name = name.strip() if (name is not None and name.strip()) else "llm-text"

        if self._provider in ("gemini", "google"):
            self._api_key = api_key if api_key is not None else settings.gemini_api_key
            self._model = model if model is not None else settings.gemini_model
            self._base_url = (
                base_url if base_url is not None else settings.gemini_base_url
            ).rstrip("/")
        elif self._provider == "openai":
            self._api_key = api_key if api_key is not None else settings.openai_api_key
            self._model = model if model is not None else settings.openai_model
            self._base_url = (
                base_url if base_url is not None else settings.openai_base_url
            ).rstrip("/")
        elif self._provider == "anthropic":
            self._api_key = api_key if api_key is not None else settings.anthropic_api_key
            self._model = model if model is not None else settings.anthropic_model
            self._base_url = (
                base_url if base_url is not None else settings.anthropic_base_url
            ).rstrip("/")
        else:
            self._api_key = (
                api_key
                if api_key is not None
                else (settings.custom_api_key or settings.xkiro_api_key)
            )
            self._model = (
                model
                if model is not None
                else (settings.custom_model or settings.xkiro_model)
            )
            self._base_url = (
                base_url
                if base_url is not None
                else (settings.custom_base_url or settings.xkiro_base_url)
            ).rstrip("/")

    @property
    def name(self) -> str:
        """Translator identifier."""
        return self._name

    async def is_available(self) -> bool:
        """Check whether provider API key is set."""
        return bool(self._api_key and self._api_key.strip())

    def _build_prompt(self, texts: list[str], source_lang: str, target_lang: str) -> str:
        """Build text-only translation prompt."""
        return (
            f"You are a professional manga dialogue translator.\n"
            f"Translate the following list of dialogue strings from {source_lang} to {target_lang} (Vietnamese).\n"
            f"Maintain character tone, comic nuances, and conversational style.\n"
            f"Return ONLY a valid JSON array of translated strings matching the exact order and length of the input.\n"
            f"Input:\n{json.dumps(texts, ensure_ascii=False)}"
        )

    def _parse_json_response(self, content_str: str, expected_len: int) -> list[str] | None:
        """Extract and validate JSON array of strings from LLM text response."""
        cleaned = content_str.strip()
        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned).strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                result = [str(x) for x in parsed]
                if len(result) == expected_len:
                    return result
            elif isinstance(parsed, dict):
                # Search for any list value inside dictionary
                for val in parsed.values():
                    if isinstance(val, list) and len(val) == expected_len:
                        return [str(x) for x in val]
        except json.JSONDecodeError:
            pass

        return None

    async def _query_gemini(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        expected_len: int,
        model: str | None = None,
    ) -> list[str] | None:
        """Send text request to Gemini endpoint."""
        target_model = model or self._model
        url = f"{self._base_url}/models/{target_model}:generateContent?key={self._api_key}"
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }

        resp = await client.post(url, json=payload, timeout=self._timeout_seconds)
        if resp.status_code != 200:
            return None

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            return None

        raw_text = parts[0].get("text", "")
        return self._parse_json_response(raw_text, expected_len)

    async def _query_openai(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        expected_len: int,
        model: str | None = None,
    ) -> list[str] | None:
        """Send text request to OpenAI / xKiro chat completion endpoint."""
        target_model = model or self._model
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional manga translator. Respond ONLY with a valid JSON array of translated strings.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        resp = await client.post(url, headers=headers, json=payload, timeout=self._timeout_seconds)
        if resp.status_code != 200:
            return None

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        raw_text = message.get("content", "")
        return self._parse_json_response(raw_text, expected_len)

    async def _query_anthropic(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        expected_len: int,
        model: str | None = None,
    ) -> list[str] | None:
        """Send text request to Anthropic Messages endpoint."""
        target_model = model or self._model or "claude-3-5-haiku-20241022"
        url = f"{self._base_url}/messages"
        headers = {
            "x-api-key": self._api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": target_model,
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        resp = await client.post(url, headers=headers, json=payload, timeout=self._timeout_seconds)
        if resp.status_code != 200:
            return None

        data = resp.json()
        content = data.get("content", [])
        if not content:
            return None

        raw_text = content[0].get("text", "")
        return self._parse_json_response(raw_text, expected_len)

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "vi",
        model: str | None = None,
    ) -> list[str]:
        """Translate a batch of dialogue strings using text-only LLM prompts."""
        if not texts:
            return []

        # Find non-empty and non-whitespace indices
        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        if not non_empty_indices:
            return list(texts)

        to_translate = [texts[i] for i in non_empty_indices]
        prompt = self._build_prompt(to_translate, source_lang, target_lang)

        target_model = model or self._model
        logger.debug(
            format_logfmt(
                "LLMTranslateDispatch",
                provider=self._provider,
                model=target_model,
                items=len(to_translate),
            )
        )

        current_delay = self._retry_delay
        translated_subset: list[str] | None = None

        # Manage HTTP client lifecycle
        client_to_use = self._client
        owns_client = False
        if client_to_use is None:
            client_to_use = httpx.AsyncClient()
            owns_client = True

        try:
            for attempt in range(self._max_retries + 1):
                try:
                    if self._provider in ("gemini", "google"):
                        translated_subset = await self._query_gemini(
                            client_to_use, prompt, len(to_translate), model=model
                        )
                    elif self._provider == "anthropic":
                        translated_subset = await self._query_anthropic(
                            client_to_use, prompt, len(to_translate), model=model
                        )
                    else:
                        translated_subset = await self._query_openai(
                            client_to_use, prompt, len(to_translate), model=model
                        )

                    if translated_subset is not None:
                        break
                except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError, TimeoutError):
                    translated_subset = None

                if attempt < self._max_retries:
                    logger.warning(
                        format_logfmt(
                            "LLMTranslateRetry",
                            provider=self._provider,
                            attempt=attempt + 1,
                            max_retries=self._max_retries,
                        )
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= 2
        finally:
            if owns_client and client_to_use is not None:
                await client_to_use.aclose()

        if translated_subset is None:
            translated_subset = to_translate

        # Re-assemble complete output matching original input length and positions
        results = list(texts)
        for idx, trans in zip(non_empty_indices, translated_subset):
            results[idx] = trans

        logger.debug(
            format_logfmt(
                "LLMTranslateCompleted",
                provider=self._provider,
                items=len(results),
                success=translated_subset is not None,
            )
        )

        return results
