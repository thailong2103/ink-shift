"""Text-only LLM translator client reusing Module 3 configurations (Gemini and OpenAI/xKiro)."""

from __future__ import annotations

import ast
import asyncio
import json
import random
import re
from typing import Any

import httpx

from src.backend.config import Settings
from src.backend.engines.local.translator.base import TranslationBatch
from src.backend.logging import format_logfmt, get_logger

logger = get_logger("translator.llm")


class UpstreamConcurrencyConflictError(Exception):
    """Raised when upstream API returns HTTP 409 indicating duplicate in-flight generation collision."""


_MODEL_CONCURRENCY_LOCKS: dict[str, asyncio.Lock] = {}


def _get_concurrency_lock(model_name: str) -> asyncio.Lock:
    """Retrieve or allocate an in-process asyncio.Lock for single-concurrency free-tier models."""
    if model_name not in _MODEL_CONCURRENCY_LOCKS:
        _MODEL_CONCURRENCY_LOCKS[model_name] = asyncio.Lock()
    return _MODEL_CONCURRENCY_LOCKS[model_name]


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

    def _is_single_concurrency(self, model: str) -> bool:
        """Detect whether upstream model requires single concurrency serialization (e.g. OpenRouter :free models)."""
        model_lower = model.lower()
        return ":free" in model_lower or model_lower.endswith("-free")

    def _build_system_prompt(
        self,
        target_lang: str = "vi",
        custom_prompt: str | None = None,
    ) -> str:
        """Build system-level prompt defining translator persona, rules, and JSON schema."""
        custom_guidelines = ""
        if custom_prompt and custom_prompt.strip():
            custom_guidelines = (
                f"\n=== USER TRANSLATION STYLE & GLOSSARY GUIDELINES ===\n"
                f"{custom_prompt.strip()}\n"
                f"====================================================\n\n"
            )

        lang_name = "Vietnamese" if target_lang.lower() == "vi" else target_lang
        return (
            f"You are a professional manga dialogue translator.\n"
            f"Translate all dialogue strings into natural {lang_name} while maintaining character tone, comic nuances, and conversational style.\n"
            f"{custom_guidelines}"
            f"Return ONLY a valid JSON array of translated strings matching the exact order and length of the input.\n"
            f"Do not include markdown code blocks, conversational text, or explanations. Output raw JSON array only."
        )

    def _build_user_prompt(self, texts: list[str]) -> str:
        """Build user data prompt containing pure JSON array of dialogue strings."""
        return json.dumps(texts, ensure_ascii=False)

    def _build_prompt(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "vi",
        custom_prompt: str | None = None,
    ) -> str:
        """Backward-compatible monolithic prompt builder."""
        custom_guidelines = ""
        if custom_prompt and custom_prompt.strip():
            custom_guidelines = (
                f"\n=== USER TRANSLATION STYLE & GLOSSARY GUIDELINES ===\n"
                f"{custom_prompt.strip()}\n"
                f"====================================================\n\n"
            )

        lang_name = "Vietnamese" if target_lang.lower() == "vi" else target_lang
        return (
            f"You are a professional manga dialogue translator.\n"
            f"Translate the following list of dialogue strings into natural {lang_name}.\n"
            f"Maintain character tone, comic nuances, and conversational style.\n"
            f"{custom_guidelines}"
            f"Return ONLY a valid JSON array of translated strings matching the exact order and length of the input.\n"
            f"Input:\n{self._build_user_prompt(texts)}"
        )

    def _clean_raw_response(self, content_str: str) -> str:
        """Strip reasoning tags and markdown code fences from raw LLM output."""
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", content_str, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE).strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned).strip()
        return cleaned

    def _validate_extracted_list(
        self,
        parsed_obj: Any,
        expected_len: int | None,
    ) -> list[str] | None:
        """Validate parsed JSON object as a list of strings matching optional expected length."""
        candidate_list: list[Any] | None = None
        if isinstance(parsed_obj, list):
            candidate_list = parsed_obj
        elif isinstance(parsed_obj, dict):
            if expected_len is not None:
                for val in parsed_obj.values():
                    if isinstance(val, list) and len(val) == expected_len:
                        candidate_list = val
                        break
            else:
                for val in parsed_obj.values():
                    if isinstance(val, list) and len(val) > 0:
                        candidate_list = val
                        break

        if candidate_list is None:
            return None
        result = [str(x) for x in candidate_list]
        if expected_len is not None:
            return result if len(result) == expected_len else None
        return result if len(result) > 0 else None

    def _repair_malformed_json_array(
        self,
        candidate: str,
        expected_len: int | None,
    ) -> list[str] | None:
        """Attempt targeted repair on trailing commas, Python-style quotes, or unescaped inner quotes."""
        fixed = re.sub(r",\s*\]", "]", candidate.strip())
        try:
            parsed = json.loads(fixed, strict=False)
            res = self._validate_extracted_list(parsed, expected_len)
            if res is not None:
                return res
        except json.JSONDecodeError:
            pass

        try:
            lit = ast.literal_eval(fixed)
            res = self._validate_extracted_list(lit, expected_len)
            if res is not None:
                return res
        except (ValueError, SyntaxError, MemoryError, TypeError):
            pass

        if fixed.startswith("[") and fixed.endswith("]"):
            inner = fixed[1:-1].strip()
            if inner.startswith('"') and inner.endswith('"') and len(inner) >= 2:
                parts = re.split(r'"\s*,\s*"', inner[1:-1])
                repaired = [
                    p.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
                    for p in parts
                ]
                if expected_len is not None:
                    return repaired if len(repaired) == expected_len else None
                return repaired if len(repaired) > 0 else None

        return None

    def _extract_candidates_from_text(
        self,
        content_str: str,
        expected_len: int | None,
    ) -> list[str] | None:
        """Parse and validate JSON array from LLM output, optionally requiring exact length."""
        cleaned = self._clean_raw_response(content_str)

        # Pass 1: Direct JSON parse
        try:
            parsed = json.loads(cleaned, strict=False)
            res = self._validate_extracted_list(parsed, expected_len)
            if res is not None:
                return res
        except json.JSONDecodeError:
            pass

        # Pass 2: Defensive Regex Bracket Extraction (e.g. conversational preamble/postscript)
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            candidate_json = match.group(0).strip()
            try:
                parsed = json.loads(candidate_json, strict=False)
                res = self._validate_extracted_list(parsed, expected_len)
                if res is not None:
                    return res
            except json.JSONDecodeError:
                pass

            # Pass 3: Repair trailing commas, single quotes, or unescaped double quotes
            repaired = self._repair_malformed_json_array(candidate_json, expected_len)
            if repaired is not None:
                return repaired

        return None

    def _parse_json_response(self, content_str: str, expected_len: int) -> list[str] | None:
        """Extract and validate JSON array of strings from LLM text response."""
        return self._extract_candidates_from_text(content_str, expected_len=expected_len)

    def _extract_raw_list(self, content_str: str) -> list[str] | None:
        """Extract any non-empty JSON string list regardless of element count."""
        return self._extract_candidates_from_text(content_str, expected_len=None)

    def _parse_and_collect(
        self,
        raw_text: str,
        expected_len: int,
        target_model: str,
        partial_collector: list[list[str]] | None = None,
    ) -> list[str] | None:
        """Parse exact-length list or log diagnostics and collect any partial list."""
        parsed = self._parse_json_response(raw_text, expected_len)
        if parsed is not None:
            return parsed

        logger.warning(
            format_logfmt(
                "LLMParseFailed",
                provider=self._provider,
                model=target_model,
                expected=expected_len,
                preview=raw_text[:160].replace("\n", " "),
            )
        )
        if partial_collector is not None:
            partial = self._extract_raw_list(raw_text)
            if partial:
                partial_collector.append(partial)
        return None

    def _align_mismatched_translations(
        self,
        partial: list[str],
        source_texts: list[str],
    ) -> list[str]:
        """Align a non-empty translation list whose length differs from source_texts."""
        expected = len(source_texts)
        if len(partial) == expected:
            return list(partial)
        if len(partial) > expected:
            if expected == 1:
                return [" ".join(partial)]
            aligned = list(partial[: expected - 1])
            aligned.append(" ".join(partial[expected - 1 :]))
            return aligned
        aligned = list(partial)
        aligned.extend(source_texts[len(partial) :])
        return aligned

    async def _query_gemini(
        self,
        client: httpx.AsyncClient,
        system_prompt: str,
        user_prompt: str,
        expected_len: int,
        model: str | None = None,
        partial_collector: list[list[str]] | None = None,
    ) -> list[str] | None:
        """Send text request to Gemini endpoint with native systemInstruction."""
        target_model = (model.strip() if model and model.strip() else None) or (
            self._model.strip() if self._model and self._model.strip() else None
        )
        if not target_model:
            if self._provider in ("gemini", "google"):
                target_model = "gemini-2.0-flash"
            elif self._provider == "anthropic":
                target_model = "claude-3-5-haiku-20241022"
            elif self._provider == "openai":
                target_model = "gpt-4o-mini"
            else:
                target_model = "google/gemini-2.5-flash"
        url = f"{self._base_url}/models/{target_model}:generateContent?key={self._api_key}"
        payload: dict[str, Any] = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }

        resp = await client.post(url, json=payload, timeout=self._timeout_seconds)
        if resp.status_code == 409:
            raise UpstreamConcurrencyConflictError(f"Gemini HTTP 409: {resp.text[:150]}")
        # Defensive fallback: If endpoint doesn't support systemInstruction
        if resp.status_code == 400 and "systeminstruction" in resp.text.lower():
            fallback_payload = {
                "contents": [
                    {
                        "parts": [{"text": f"{system_prompt}\n\nInput:\n{user_prompt}"}],
                    }
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.2,
                },
            }
            resp = await client.post(url, json=fallback_payload, timeout=self._timeout_seconds)

        if resp.status_code != 200:
            logger.warning(
                format_logfmt(
                    "LLMQueryFailed",
                    provider="gemini",
                    model=target_model,
                    status=resp.status_code,
                    error=resp.text[:250].replace("\n", " "),
                )
            )
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
        return self._parse_and_collect(raw_text, expected_len, target_model, partial_collector)

    async def _query_openai(
        self,
        client: httpx.AsyncClient,
        system_prompt: str,
        user_prompt: str,
        expected_len: int,
        model: str | None = None,
        partial_collector: list[list[str]] | None = None,
    ) -> list[str] | None:
        """Send text request to OpenAI / xKiro chat completion endpoint."""
        target_model = (model.strip() if model and model.strip() else None) or (
            self._model.strip() if self._model and self._model.strip() else None
        )
        if not target_model:
            target_model = "gpt-4o-mini" if self._provider == "openai" else "google/gemini-2.5-flash"
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        resp = await client.post(url, headers=headers, json=payload, timeout=self._timeout_seconds)
        if resp.status_code == 409:
            raise UpstreamConcurrencyConflictError(f"{self._provider} HTTP 409: {resp.text[:150]}")
        # Defensive fallback: If upstream rejects role 'system' with HTTP 400
        if resp.status_code == 400 and ("system" in resp.text.lower() and "role" in resp.text.lower()):
            fallback_payload = {
                "model": target_model,
                "messages": [
                    {"role": "user", "content": f"{system_prompt}\n\nInput:\n{user_prompt}"},
                ],
                "temperature": 0.2,
            }
            resp = await client.post(url, headers=headers, json=fallback_payload, timeout=self._timeout_seconds)

        if resp.status_code != 200:
            logger.warning(
                format_logfmt(
                    "LLMQueryFailed",
                    provider=self._provider,
                    model=target_model,
                    status=resp.status_code,
                    error=resp.text[:250].replace("\n", " "),
                )
            )
            return None

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        raw_text = message.get("content", "")
        return self._parse_and_collect(raw_text, expected_len, target_model, partial_collector)

    async def _query_anthropic(
        self,
        client: httpx.AsyncClient,
        system_prompt: str,
        user_prompt: str,
        expected_len: int,
        model: str | None = None,
        partial_collector: list[list[str]] | None = None,
    ) -> list[str] | None:
        """Send text request to Anthropic Messages endpoint."""
        target_model = (model.strip() if model and model.strip() else None) or (
            self._model.strip() if self._model and self._model.strip() else None
        )
        if not target_model:
            target_model = "claude-3-5-haiku-20241022"
        url = f"{self._base_url}/messages"
        headers = {
            "x-api-key": self._api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": target_model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        resp = await client.post(url, headers=headers, json=payload, timeout=self._timeout_seconds)
        if resp.status_code == 409:
            raise UpstreamConcurrencyConflictError(f"Anthropic HTTP 409: {resp.text[:150]}")
        if resp.status_code != 200:
            logger.warning(
                format_logfmt(
                    "LLMQueryFailed",
                    provider="anthropic",
                    model=target_model,
                    status=resp.status_code,
                    error=resp.text[:250].replace("\n", " "),
                )
            )
            return None

        data = resp.json()
        content = data.get("content", [])
        if not content:
            return None

        raw_text = content[0].get("text", "")
        return self._parse_and_collect(raw_text, expected_len, target_model, partial_collector)

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "vi",
        model: str | None = None,
        custom_prompt: str | None = None,
    ) -> list[str]:
        """Translate a batch of dialogue strings using text-only LLM prompts."""
        if not texts:
            return []

        # Find non-empty and non-whitespace indices
        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        if not non_empty_indices:
            return list(texts)

        to_translate = [texts[i] for i in non_empty_indices]
        system_prompt = self._build_system_prompt(target_lang, custom_prompt=custom_prompt)
        user_prompt = self._build_user_prompt(to_translate)

        target_model = (model.strip() if model and model.strip() else None) or (
            self._model.strip() if self._model and self._model.strip() else None
        )
        if not target_model:
            if self._provider in ("gemini", "google"):
                target_model = "gemini-2.0-flash"
            elif self._provider == "anthropic":
                target_model = "claude-3-5-haiku-20241022"
            elif self._provider == "openai":
                target_model = "gpt-4o-mini"
            else:
                target_model = "google/gemini-2.5-flash"
        logger.debug(
            format_logfmt(
                "LLMTranslateDispatch",
                provider=self._provider,
                model=target_model,
                items=len(to_translate),
            )
        )

        # In-process serialization lock for single-concurrency / free-tier models
        lock = _get_concurrency_lock(target_model) if self._is_single_concurrency(target_model) else None

        # Manage HTTP client lifecycle
        client_to_use = self._client
        owns_client = False
        if client_to_use is None:
            client_to_use = httpx.AsyncClient()
            owns_client = True

        partial_collector: list[list[str]] = []

        async def _dispatch_with_retries() -> list[str] | None:
            current_delay = self._retry_delay
            translated: list[str] | None = None
            for attempt in range(self._max_retries + 1):
                is_conflict_409 = False
                active_system_prompt = system_prompt
                if attempt > 0:
                    active_system_prompt = (
                        f"{system_prompt}\n"
                        f"CRITICAL CONSTRAINT: The input JSON array has EXACTLY {len(to_translate)} elements. "
                        f"You MUST return a valid JSON array containing EXACTLY {len(to_translate)} translated strings. "
                        f'Do NOT merge or split elements, and escape any inner double quotes with \\".'
                    )
                try:
                    if self._provider in ("gemini", "google"):
                        translated = await self._query_gemini(
                            client_to_use,
                            active_system_prompt,
                            user_prompt,
                            len(to_translate),
                            model=model,
                            partial_collector=partial_collector,
                        )
                    elif self._provider == "anthropic":
                        translated = await self._query_anthropic(
                            client_to_use,
                            active_system_prompt,
                            user_prompt,
                            len(to_translate),
                            model=model,
                            partial_collector=partial_collector,
                        )
                    else:
                        translated = await self._query_openai(
                            client_to_use,
                            active_system_prompt,
                            user_prompt,
                            len(to_translate),
                            model=model,
                            partial_collector=partial_collector,
                        )

                    if translated is not None:
                        break
                except UpstreamConcurrencyConflictError as exc:
                    is_conflict_409 = True
                    logger.warning(
                        format_logfmt(
                            "LLMConcurrencyConflict",
                            provider=self._provider,
                            model=target_model,
                            attempt=attempt + 1,
                            error=str(exc),
                        )
                    )
                    translated = None
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    IndexError,
                    TypeError,
                    RuntimeError,
                    OSError,
                ) as exc:
                    err_desc = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                    logger.warning(
                        format_logfmt(
                            "LLMQueryException",
                            provider=self._provider,
                            model=target_model,
                            error=err_desc,
                        )
                    )
                    translated = None
                    if isinstance(exc, httpx.TimeoutException):
                        break

                if attempt >= 1 and partial_collector and not is_conflict_409:
                    break

                if attempt < self._max_retries:
                    if is_conflict_409:
                        backoff_sleep = 2.0 * (attempt + 1) + random.uniform(0.2, 0.8)
                        logger.warning(
                            format_logfmt(
                                "LLMConflictBackoff",
                                provider=self._provider,
                                attempt=attempt + 1,
                                backoff_s=round(backoff_sleep, 2),
                            )
                        )
                        await asyncio.sleep(backoff_sleep)
                    else:
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
            return translated

        try:
            if lock is not None:
                async with lock:
                    translated_subset = await _dispatch_with_retries()
            else:
                translated_subset = await _dispatch_with_retries()
        finally:
            if owns_client and client_to_use is not None:
                await client_to_use.aclose()

        is_fallback = False
        if translated_subset is None:
            if partial_collector:
                best_partial = min(
                    reversed(partial_collector),
                    key=lambda p: abs(len(p) - len(to_translate)),
                )
                translated_subset = self._align_mismatched_translations(best_partial, to_translate)
                logger.warning(
                    format_logfmt(
                        "LLMPartialAlignmentRecovered",
                        provider=self._provider,
                        model=target_model,
                        got=len(best_partial),
                        expected=len(to_translate),
                    )
                )
            else:
                translated_subset = to_translate
                is_fallback = True

        # Re-assemble complete output matching original input length and positions
        results = list(texts)
        for idx, trans in zip(non_empty_indices, translated_subset):
            results[idx] = trans

        logger.debug(
            format_logfmt(
                "LLMTranslateCompleted",
                provider=self._provider,
                items=len(results),
                success=not is_fallback,
            )
        )

        return TranslationBatch(results, is_fallback=is_fallback)
