"""Google AI Studio Gemini Vision Provider implementation using Set-of-Marks."""

from __future__ import annotations

import asyncio
import base64
import json
import random
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

logger = get_logger("cloud.gemini")



class GeminiProvider:
    """Provider integrating Google AI Studio's Gemini multimodal models with Set-of-Marks."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        timeout_seconds: float = 15.0,
        detector: Any = None,  # Deprecated in Option G1; detection is performed at Gateway
    ) -> None:
        settings = Settings()
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model = model if model is not None else settings.gemini_model
        self._base_url = (
            base_url if base_url is not None else settings.gemini_base_url
        ).rstrip("/")
        self._client = http_client
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "gemini"

    @property
    def default_model(self) -> str:
        """Configured default model identifier."""
        return self._model

    async def is_available(self) -> bool:
        """Check whether Gemini API key is configured."""
        return bool(self._api_key and self._api_key.strip())

    async def translate_page(
        self,
        image_base64: str,
        target_lang: str = "vi",
        model: str | None = None,
        bubbles: list[DetectedBubble] | None = None,
    ) -> list[TranslatedBlock]:
        """Execute single-pass vision translation via Gemini generateContent REST API using Set-of-Marks."""
        if not await self.is_available():
            raise UpstreamAuthenticationError(
                "Gemini API key is not configured. Set GEMINI_API_KEY environment variable."
            )

        if not bubbles:
            return []

        work_items = prepare_local_work_items(bubbles)

        target_model = model or self._model
        _mime_type, raw_b64 = self._extract_mime_and_base64(image_base64)
        endpoint = f"{self._base_url}/models/{target_model}:generateContent"

        logger.info(
            format_logfmt(
                "UpstreamDispatch",
                provider="gemini",
                model=target_model,
                bubbles=len(bubbles),
                work_items=len(work_items),
                target_lang=target_lang,
            )
        )

        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

        image_bytes = base64.b64decode(raw_b64)
        marked_bytes = create_marked_image_bytes(image_bytes, bubbles, work_items=work_items)
        marked_b64 = base64.b64encode(marked_bytes).decode("utf-8")

        prompt_text = get_som_system_prompt(target_lang)
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt_text},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": marked_b64,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
            },
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
        """Execute HTTP POST request to Gemini API with exponential backoff on 429 and 503."""
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
                        provider="gemini",
                        timeout_s=self._timeout_seconds,
                    )
                )
                raise UpstreamTimeoutError(f"Gemini API timed out after {self._timeout_seconds}s.") from exc
            except httpx.NetworkError as exc:
                logger.error(
                    format_logfmt(
                        "UpstreamError",
                        provider="gemini",
                        error=str(exc),
                    )
                )
                raise UpstreamExecutionError(f"Network error connecting to Gemini API: {exc}") from exc

            if response.status_code == 200:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                logger.info(
                    format_logfmt(
                        "UpstreamSuccess",
                        provider="gemini",
                        model=self._model,
                        elapsed_ms=elapsed_ms,
                    )
                )
                return self._parse_som_response(response.json(), bubbles, work_items=work_items)

            if response.status_code in (429, 503):
                attempt += 1
                if attempt > self._max_retries:
                    if response.status_code == 429:
                        logger.error(
                            format_logfmt(
                                "UpstreamRateLimited",
                                provider="gemini",
                                status_code=429,
                                attempts=attempt,
                            )
                        )
                        raise RateLimitExceededError("Google AI Studio rate limit exceeded. Max retries exhausted.")
                    logger.error(
                        format_logfmt(
                            "UpstreamUnavailable",
                            provider="gemini",
                            status_code=503,
                            attempts=attempt,
                        )
                    )
                    raise UpstreamExecutionError(
                        f"Google AI Studio temporarily unavailable (HTTP 503): {response.text}"
                    )
                backoff = (2**attempt) + random.uniform(0.1, 0.5)
                logger.warning(
                    format_logfmt(
                        "UpstreamRetry",
                        provider="gemini",
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
                        provider="gemini",
                        status_code=response.status_code,
                    )
                )
                raise UpstreamAuthenticationError(
                    f"Gemini API authentication failed (HTTP {response.status_code}): {response.text}"
                )

            logger.error(
                format_logfmt(
                    "UpstreamHttpError",
                    provider="gemini",
                    status_code=response.status_code,
                    body=response.text[:200],
                )
            )
            raise UpstreamExecutionError(
                f"Gemini API returned error HTTP {response.status_code}: {response.text}"
            )

    def _parse_som_response(
        self,
        data: dict[str, Any],
        bubbles: list[DetectedBubble],
        work_items: list[BubbleWorkItem] | None = None,
    ) -> list[TranslatedBlock]:
        """Parse flat JSON dictionary response mapping badge ID to translation."""
        prompt_feedback = data.get("promptFeedback")
        if isinstance(prompt_feedback, dict):
            block_reason = prompt_feedback.get("blockReason")
            if block_reason in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
                raise ContentSafetyBlockedError(
                    f"Manga image prompt blocked by Google AI Studio (reason: {block_reason})."
                )

        candidates = data.get("candidates")
        if not candidates or not isinstance(candidates, list):
            raise UpstreamExecutionError("Google AI Studio response contains no candidates.")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        if finish_reason in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise ContentSafetyBlockedError(
                f"Manga image content was blocked by Google AI safety filter (finishReason: {finish_reason})."
            )

        parts = candidate.get("content", {}).get("parts", [])
        if not parts or not isinstance(parts, list):
            if finish_reason == "STOP":
                return []
            raise UpstreamExecutionError(
                f"Candidate contains no content parts (finishReason: {finish_reason})."
            )

        text_content = parts[0].get("text", "").strip()
        if not text_content:
            return []

        try:
            parsed = json.loads(text_content)
        except json.JSONDecodeError as exc:
            raise UpstreamExecutionError(
                f"Failed to decode JSON from Gemini output: {text_content[:200]}"
            ) from exc

        translation_map: dict[str, str] = {}
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                clean_k = str(k).strip("[] ")
                translation_map[clean_k] = str(v)
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    raw_id = str(item.get("id", "")).strip("[] ")
                    trans = str(item.get("translated_text", ""))
                    if raw_id:
                        translation_map[raw_id] = trans

        return assemble_translated_blocks(
            bubbles=bubbles,
            translations=translation_map,
            work_items=work_items,
        )


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
