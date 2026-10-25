"""Universal OpenAI-Compatible Vision Provider (supporting xKiro, OpenRouter, Ollama) with Set-of-Marks."""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
import time
from typing import Any

import httpx

from src.backend.config import Settings
from src.backend.detection.assembler import (
    BubbleWorkItem,
    assemble_translated_blocks,
    prepare_local_work_items,
)
from src.backend.detection.base import DetectedBubble
from src.backend.engines.cloud.exceptions import (
    ContentSafetyBlockedError,
    RateLimitExceededError,
    UpstreamAuthenticationError,
    UpstreamExecutionError,
    UpstreamTimeoutError,
)
from src.backend.engines.cloud.prompts import get_som_system_prompt
from src.backend.engines.cloud.visual_grounding import create_marked_image_bytes
from src.backend.logging import format_logfmt, get_logger
from src.backend.schemas.contract import TranslatedBlock

logger = get_logger("cloud.openai")


REFUSAL_PHRASES = [
    "i cannot fulfill",
    "i cannot assist",
    "i am unable to",
    "as an ai",
    "safety policy",
    "content policy",
    "violates our",
    "xin lỗi, tôi không thể",
    "tôi không thể hỗ trợ",
    "vi phạm chính sách",
]


class OpenAICompatibleProvider:
    """Provider integrating OpenAI-compatible vision endpoints (xKiro, OpenRouter, local Ollama) using Set-of-Marks."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        name: str = "xkiro",
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        timeout_seconds: float = 15.0,
    ) -> None:
        settings = Settings()
        norm_name = name.strip().lower() if name else "xkiro"
        if norm_name in ("openai", "official-openai"):
            default_key = getattr(settings, "openai_api_key", "")
            default_model = getattr(settings, "openai_model", "gpt-4o-mini")
            default_base = getattr(settings, "openai_base_url", "https://api.openai.com/v1")
        else:
            default_key = (
                getattr(settings, "custom_api_key", "")
                or getattr(settings, "xkiro_api_key", "")
            )
            default_model = (
                getattr(settings, "custom_model", "")
                or getattr(settings, "xkiro_model", "")
            )
            default_base = (
                getattr(settings, "custom_base_url", "")
                or getattr(settings, "xkiro_base_url", "https://api.xkiro.com/v1")
            )

        self._api_key = api_key if api_key is not None else default_key
        self._model = model if model is not None else default_model
        self._base_url = (
            base_url if base_url is not None else default_base
        ).rstrip("/")
        self._name = name
        self._client = http_client
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Provider identifier."""
        return self._name

    @property
    def default_model(self) -> str:
        """Configured default model identifier."""
        return self._model

    async def is_available(self) -> bool:
        """Check whether API credentials or endpoints are available."""
        # For local endpoints like ollama, empty api_key might be valid,
        # but for default cloud xKiro, an API key is required.
        if "localhost" in self._base_url or "127.0.0.1" in self._base_url:
            return True
        return bool(self._api_key and self._api_key.strip())

    async def translate_page(
        self,
        image_base64: str,
        target_lang: str = "vi",
        model: str | None = None,
        bubbles: list[DetectedBubble] | None = None,
    ) -> list[TranslatedBlock]:
        """Execute vision translation via /chat/completions endpoint using Set-of-Marks."""
        if not await self.is_available():
            raise UpstreamAuthenticationError(
                f"{self._name.capitalize()} API key is not configured. Set API key in settings or environment."
            )

        if not bubbles:
            return []

        work_items = prepare_local_work_items(bubbles)

        target_model = model or self._model
        _mime, raw_b64 = self._extract_mime_and_base64(image_base64)
        image_bytes = base64.b64decode(raw_b64)
        marked_bytes = create_marked_image_bytes(image_bytes, bubbles, work_items=work_items)
        marked_b64 = base64.b64encode(marked_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{marked_b64}"

        endpoint = f"{self._base_url}/chat/completions"

        logger.info(
            format_logfmt(
                "UpstreamDispatch",
                provider=self._name,
                model=target_model,
                bubbles=len(bubbles),
                work_items=len(work_items),
                target_lang=target_lang,
            )
        )

        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": get_som_system_prompt(target_lang),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Translate the text in each numbered speech balloon marked in the image into natural dialogue.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                            },
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }

        timeout = httpx.Timeout(self._timeout_seconds, connect=5.0)

        if self._client is not None:
            return await self._execute_with_retry(
                self._client, endpoint, headers, payload, timeout, bubbles, work_items=work_items
            )

        async with httpx.AsyncClient(timeout=timeout) as client:
            return await self._execute_with_retry(
                client, endpoint, headers, payload, timeout, bubbles, work_items=work_items
            )

    async def _execute_with_retry(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: httpx.Timeout,
        bubbles: list[DetectedBubble],
        work_items: list[BubbleWorkItem] | None = None,
    ) -> list[TranslatedBlock]:
        """Execute request with exponential backoff on HTTP 429."""
        start_time = time.perf_counter()
        for attempt in range(self._max_retries + 1):
            try:
                resp = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                logger.error(
                    format_logfmt(
                        "UpstreamTimeout",
                        provider=self._name,
                        timeout_s=self._timeout_seconds,
                    )
                )
                raise UpstreamTimeoutError(
                    f"{self._name.capitalize()} request timed out after {self._timeout_seconds}s."
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self._max_retries:
                    logger.warning(
                        format_logfmt(
                            "UpstreamRetry",
                            provider=self._name,
                            attempt=attempt + 1,
                            max_retries=self._max_retries,
                            error=str(exc),
                        )
                    )
                    await asyncio.sleep(1.0)
                    continue
                logger.error(
                    format_logfmt(
                        "UpstreamError",
                        provider=self._name,
                        error=str(exc),
                    )
                )
                raise UpstreamExecutionError(
                    f"Network communication failed with {self._name}: {exc}"
                ) from exc

            # Rate Limit (HTTP 429) Handling
            if resp.status_code == 429:
                if attempt < self._max_retries:
                    backoff = (1.0 * (2**attempt)) + random.uniform(0.0, 0.25)
                    logger.warning(
                        format_logfmt(
                            "UpstreamRetry",
                            provider=self._name,
                            status_code=429,
                            attempt=attempt + 1,
                            max_retries=self._max_retries,
                            backoff_s=round(backoff, 2),
                        )
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error(
                    format_logfmt(
                        "UpstreamRateLimited",
                        provider=self._name,
                        status_code=429,
                    )
                )
                raise RateLimitExceededError(
                    f"{self._name.capitalize()} rate limit exceeded (HTTP 429). Please retry later."
                )

            # Authentication / Authorization Failures
            if resp.status_code in (401, 403):
                logger.error(
                    format_logfmt(
                        "UpstreamAuthFailed",
                        provider=self._name,
                        status_code=resp.status_code,
                    )
                )
                raise UpstreamAuthenticationError(
                    f"{self._name.capitalize()} rejected API key with HTTP {resp.status_code}."
                )

            # HTTP Errors
            if resp.is_error:
                logger.error(
                    format_logfmt(
                        "UpstreamHttpError",
                        provider=self._name,
                        status_code=resp.status_code,
                        body=resp.text[:200],
                    )
                )
                raise UpstreamExecutionError(
                    f"{self._name.capitalize()} returned HTTP {resp.status_code}: {resp.text}"
                )

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(
                format_logfmt(
                    "UpstreamSuccess",
                    provider=self._name,
                    model=self._model,
                    elapsed_ms=elapsed_ms,
                )
            )
            return self._parse_openai_response(resp.json(), bubbles, work_items=work_items)

        raise RateLimitExceededError(f"{self._name.capitalize()} rate limit exceeded.")

    def _parse_openai_response(
        self,
        data: dict[str, Any],
        bubbles: list[DetectedBubble],
        work_items: list[BubbleWorkItem] | None = None,
    ) -> list[TranslatedBlock]:
        """Parse, clean, and map OpenAI chat completion response to detected bubbles."""
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise UpstreamExecutionError(f"{self._name.capitalize()} response contains no choices.")

        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason in ("content_filter", "safety"):
            raise ContentSafetyBlockedError(
                f"Manga image was blocked by {self._name} content safety filters (finish_reason: {finish_reason})."
            )

        message = choice.get("message", {})
        content = message.get("content", "").strip()

        # 1. Refusal heuristic check
        lower_content = content.lower()
        if any(phrase in lower_content for phrase in REFUSAL_PHRASES) and not (
            "[" in content and "]" in content
        ):
            raise ContentSafetyBlockedError(
                f"Manga image translation was refused by model: {content[:150]}"
            )

        if not content:
            return []

        # 2. Defensive markdown code fence stripping
        cleaned_json_str = self._strip_markdown_code_fence(content)

        # 3. JSON decode
        try:
            parsed = json.loads(cleaned_json_str)
        except json.JSONDecodeError as exc:
            raise UpstreamExecutionError(
                f"Failed to parse JSON response from {self._name}: {content[:200]}"
            ) from exc

        # 4. Extract translation map {badge_id: translated_text}
        translation_map: dict[str, str] = {}
        if isinstance(parsed, dict):
            # Check potential wrapper keys
            candidate_dict = parsed
            for wrapper_key in ("translations", "blocks", "result", "data"):
                if wrapper_key in parsed and isinstance(parsed[wrapper_key], dict):
                    candidate_dict = parsed[wrapper_key]
                    break
            for k, v in candidate_dict.items():
                clean_k = str(k).strip("[] ")
                translation_map[clean_k] = str(v)
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    raw_id = str(item.get("id", "")).strip("[] ")
                    trans = str(item.get("translated_text", ""))
                    if raw_id:
                        translation_map[raw_id] = trans

        # 5. Assemble TranslatedBlock models with polygon safe-zones
        return assemble_translated_blocks(
            bubbles=bubbles,
            translations=translation_map,
            work_items=work_items,
        )


    @staticmethod
    def _strip_markdown_code_fence(text: str) -> str:
        """Extract JSON payload inside markdown code fences if present."""
        code_fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        match = re.search(code_fence_pattern, text)
        if match:
            return match.group(1).strip()
        return text.strip()

    @staticmethod
    def _extract_mime_and_base64(image_input: str) -> tuple[str, str]:
        """Separate data URL prefix and raw Base64 data."""
        if "," in image_input:
            header, b64_data = image_input.split(",", 1)
            mime = "image/jpeg"
            if "image/png" in header:
                mime = "image/png"
            elif "image/webp" in header:
                mime = "image/webp"
            return mime, b64_data.strip()
        return "image/jpeg", image_input.strip()

    @staticmethod
    def _format_data_url(image_input: str) -> str:
        """Ensure image string is formatted as a valid Data URL."""
        if image_input.startswith("data:"):
            return image_input
        return f"data:image/jpeg;base64,{image_input.strip()}"
