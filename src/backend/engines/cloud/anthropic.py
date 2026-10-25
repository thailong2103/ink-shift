"""Anthropic Claude Vision Provider implementation using Set-of-Marks."""

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

logger = get_logger("cloud.anthropic")


class AnthropicProvider:
    """Provider integrating Anthropic's Claude multimodal models (Claude 3 & 3.5) with Set-of-Marks."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        timeout_seconds: float = 15.0,
    ) -> None:
        settings = Settings()
        self._api_key = (
            api_key
            if api_key is not None
            else getattr(settings, "anthropic_api_key", "")
        )
        self._model = (
            model
            if model is not None
            else getattr(settings, "anthropic_model", "claude-3-5-sonnet-20241022")
        )
        raw_base = (
            base_url
            if base_url is not None
            else getattr(settings, "anthropic_base_url", "https://api.anthropic.com/v1")
        )
        self._base_url = raw_base.rstrip("/")
        self._client = http_client
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "anthropic"

    @property
    def default_model(self) -> str:
        """Configured default model identifier."""
        return self._model

    async def is_available(self) -> bool:
        """Check whether Anthropic API key is configured."""
        return bool(self._api_key and self._api_key.strip())

    async def translate_page(
        self,
        image_base64: str,
        target_lang: str = "vi",
        model: str | None = None,
        bubbles: list[DetectedBubble] | None = None,
    ) -> list[TranslatedBlock]:
        """Execute single-pass vision translation via Anthropic Messages API using Set-of-Marks."""
        if not await self.is_available():
            raise UpstreamAuthenticationError(
                "Anthropic API key is not configured. Set ANTHROPIC_API_KEY environment variable."
            )

        if not bubbles:
            return []

        work_items = prepare_local_work_items(bubbles)
        target_model = model or self._model
        _mime_type, raw_b64 = self._extract_mime_and_base64(image_base64)
        endpoint = f"{self._base_url}/messages"

        logger.info(
            format_logfmt(
                "UpstreamDispatch",
                provider="anthropic",
                model=target_model,
                bubbles=len(bubbles),
                work_items=len(work_items),
                target_lang=target_lang,
            )
        )

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        image_bytes = base64.b64decode(raw_b64)
        marked_bytes = create_marked_image_bytes(image_bytes, bubbles, work_items=work_items)
        marked_b64 = base64.b64encode(marked_bytes).decode("utf-8")

        prompt_text = get_som_system_prompt(target_lang)
        payload: dict[str, Any] = {
            "model": target_model,
            "max_tokens": 4096,
            "system": prompt_text,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": marked_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Translate all numbered manga speech bubbles into Vietnamese following "
                                "the requested JSON format."
                            ),
                        },
                    ],
                }
            ],
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
        """Execute HTTP POST request to Anthropic API with exponential backoff on 429 and 529."""
        attempt = 0
        start_time = time.perf_counter()
        while True:
            try:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                logger.error(
                    format_logfmt(
                        "UpstreamTimeout",
                        provider="anthropic",
                        timeout_s=self._timeout_seconds,
                    )
                )
                raise UpstreamTimeoutError(
                    f"Anthropic API timed out after {self._timeout_seconds}s."
                ) from exc
            except httpx.NetworkError as exc:
                logger.error(
                    format_logfmt(
                        "UpstreamNetworkError",
                        provider="anthropic",
                        error=str(exc),
                    )
                )
                raise UpstreamExecutionError(f"Anthropic API network error: {exc}") from exc

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            if response.status_code == 200:
                logger.info(
                    format_logfmt(
                        "UpstreamSuccess",
                        provider="anthropic",
                        status_code=200,
                        latency_ms=latency_ms,
                    )
                )
                data = response.json()
                return self._parse_som_response(data, bubbles, work_items=work_items)

            # Retryable server errors and rate limits (429, 529 Overloaded, 503)
            if response.status_code in (429, 503, 529):
                attempt += 1
                if attempt > self._max_retries:
                    if response.status_code == 429:
                        logger.error(
                            format_logfmt(
                                "UpstreamRateLimited",
                                provider="anthropic",
                                status_code=429,
                                attempts=attempt,
                            )
                        )
                        raise RateLimitExceededError("Anthropic rate limit exceeded. Max retries exhausted.")
                    logger.error(
                        format_logfmt(
                            "UpstreamOverloaded",
                            provider="anthropic",
                            status_code=response.status_code,
                            attempts=attempt,
                        )
                    )
                    raise UpstreamExecutionError(
                        f"Anthropic API temporarily overloaded (HTTP {response.status_code}): {response.text}"
                    )
                backoff = (2**attempt) + random.uniform(0.1, 0.5)
                logger.warning(
                    format_logfmt(
                        "UpstreamRetry",
                        provider="anthropic",
                        status_code=response.status_code,
                        attempt=attempt,
                        max_retries=self._max_retries,
                        backoff_s=round(backoff, 2),
                    )
                )
                await asyncio.sleep(backoff)
                continue

            if response.status_code in (401, 403):
                logger.error(
                    format_logfmt(
                        "UpstreamAuthFailed",
                        provider="anthropic",
                        status_code=response.status_code,
                    )
                )
                raise UpstreamAuthenticationError(
                    f"Anthropic API authentication failed (HTTP {response.status_code}): {response.text}"
                )

            logger.error(
                format_logfmt(
                    "UpstreamHttpError",
                    provider="anthropic",
                    status_code=response.status_code,
                    body=response.text[:200],
                )
            )
            raise UpstreamExecutionError(
                f"Anthropic API returned error HTTP {response.status_code}: {response.text}"
            )

    def _parse_som_response(
        self,
        data: dict[str, Any],
        bubbles: list[DetectedBubble],
        work_items: list[BubbleWorkItem] | None = None,
    ) -> list[TranslatedBlock]:
        """Parse flat JSON dictionary response mapping badge ID to translation."""
        stop_reason = data.get("stop_reason")
        if stop_reason == "refusal":
            raise ContentSafetyBlockedError(
                "Manga image content was refused by Anthropic safety policy."
            )

        content_list = data.get("content", [])
        if not content_list or not isinstance(content_list, list):
            raise UpstreamExecutionError("Anthropic response contains no content parts.")

        text_content = ""
        for part in content_list:
            if isinstance(part, dict) and part.get("type") == "text":
                text_content += part.get("text", "")

        text_content = text_content.strip()
        if not text_content:
            return []

        # Strip markdown fences if present
        clean_text = text_content
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL)
        if match:
            clean_text = match.group(1)
        else:
            json_match = re.search(r"(\{.*\})", clean_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(1)

        try:
            translation_map: dict[str, Any] = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            logger.error(
                format_logfmt(
                    "JSONParseFailed",
                    provider="anthropic",
                    raw_text=clean_text[:200],
                )
            )
            raise UpstreamExecutionError(
                f"Failed to parse Set-of-Marks translation JSON: {exc}"
            ) from exc

        return assemble_translated_blocks(
            bubbles=bubbles,
            translations=translation_map,
            work_items=work_items,
        )

    @staticmethod
    def _extract_mime_and_base64(image_str: str) -> tuple[str, str]:
        """Parse data URL or standard base64 string into (mime_type, clean_base64)."""
        if "," in image_str:
            prefix, b64_data = image_str.split(",", 1)
            mime_match = re.search(r"data:([^;]+);base64", prefix)
            mime_type = mime_match.group(1) if mime_match else "image/jpeg"
            return mime_type, b64_data
        return "image/jpeg", image_str
