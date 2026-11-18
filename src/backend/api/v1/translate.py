"""Manga page translation endpoint."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import heapq
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from PIL import Image

if TYPE_CHECKING:
    from src.backend.detection.base import DetectedBubble
from src.backend.cache.sqlite_cache import TranslationCache, compute_prompt_hash
from src.backend.config import Settings
from src.backend.engines.base import BaseTranslationEngine
from src.backend.engines.cloud.exceptions import CloudEngineError
from src.backend.engines.registry import EngineNotFoundError, EngineRegistry
from src.backend.logging import format_logfmt, get_logger
from src.backend.schemas.contract import (
    APIErrorDetail,
    APIErrorResponse,
    TranslationRequest,
    TranslationResponse,
)
from src.backend.security.middleware import validate_image_magic_bytes

logger = get_logger("api.translate")

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

ENGINE_EXECUTION_ERRORS = (
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

router = APIRouter()

_PRIORITY_RANK: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2}


class PriorityLocalLock(asyncio.Semaphore):
    """Priority-aware single-slot async lock for local ML inference.

    P0 (active on-screen page) preempts P1/P2 and wakes LIFO (newest page first).
    P1 (next page) and P2 (lookahead prefetch) wake FIFO (forward order).
    """

    def __init__(self) -> None:
        super().__init__(1)
        self._locked: bool = False
        self._seq: int = 0
        self._priority_waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._waiter_by_key: dict[str, asyncio.Future[None]] = {}

    def locked(self) -> bool:
        """Return True if the lock is currently held."""
        return self._locked

    def _wake_next_or_unlock(self) -> None:
        while self._priority_waiters:
            _, _, fut = heapq.heappop(self._priority_waiters)
            if not fut.done():
                fut.set_result(None)
                self._locked = True
                self._value = 0
                return
        self._locked = False
        self._value = 1

    def promote_to_p0(self, key: str) -> bool:
        """Promote an already-queued waiter identified by key to P0 LIFO priority."""
        fut = self._waiter_by_key.get(key)
        if fut is not None and not fut.done():
            self._seq += 1
            heapq.heappush(self._priority_waiters, (0, -self._seq, fut))
            return True
        return False

    async def acquire(self, priority: str = "P0", key: str | None = None) -> Literal[True]:
        """Acquire lock according to request priority."""
        if not self._locked:
            self._locked = True
            self._value = 0
            return True

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        self._seq += 1
        rank = _PRIORITY_RANK.get(priority, 0)
        order = -self._seq if rank == 0 else self._seq
        heapq.heappush(self._priority_waiters, (rank, order, fut))
        if key is not None:
            self._waiter_by_key[key] = fut
        try:
            await fut
        except BaseException:
            if fut.done() and not fut.cancelled():
                self._wake_next_or_unlock()
            raise
        finally:
            if key is not None and self._waiter_by_key.get(key) is fut:
                self._waiter_by_key.pop(key, None)
        self._locked = True
        self._value = 0
        return True

    def release(self) -> None:
        """Release lock and wake the highest-priority pending waiter."""
        if not self._locked:
            return
        self._wake_next_or_unlock()

    @asynccontextmanager
    async def acquire_priority(self, priority: str = "P0", key: str | None = None) -> AsyncIterator[None]:
        """Async context manager acquiring the lock with explicit priority."""
        await self.acquire(priority, key=key)
        try:
            yield
        finally:
            self.release()


def _decode_and_validate_image(image_str: str) -> tuple[bytes | None, str | None]:
    """Extract raw bytes from base64 string or data URL, verifying format and magic bytes."""
    clean_base64 = image_str
    if "," in image_str:
        clean_base64 = image_str.split(",", 1)[1]

    try:
        raw_bytes = base64.b64decode(clean_base64, validate=True)
    except (binascii.Error, ValueError):
        return None, "Malformed Base64 payload."

    if not validate_image_magic_bytes(raw_bytes):
        return None, "Invalid image format. Supported formats: JPEG, PNG, WebP, AVIF."

    return raw_bytes, None


@router.post(
    "/translate",
    response_model=TranslationResponse,
    responses={
        200: {"model": TranslationResponse, "description": "Successful translation"},
        400: {"model": APIErrorResponse, "description": "Invalid image payload"},
        500: {"model": APIErrorResponse, "description": "Translation engine execution failed"},
    },
)
async def translate_page(
    request: Request,
    payload: TranslationRequest,
) -> TranslationResponse | JSONResponse:
    """Submit a manga page image for text detection and translation."""
    image_kb = len(payload.image) / 1024
    logger.info(
        format_logfmt(
            "RequestReceived",
            engine=payload.engine,
            target=payload.target_lang,
            size_kb=round(image_kb, 1),
        )
    )

    # 1. Validate Base64 payload and image magic bytes
    raw_bytes, validation_err = _decode_and_validate_image(payload.image)
    if validation_err is not None or raw_bytes is None:
        logger.warning(
            format_logfmt("ImageValidationFailed", error=validation_err or "Invalid image payload.")
        )
        return JSONResponse(
            status_code=400,
            content=APIErrorResponse(
                success=False,
                error=APIErrorDetail(
                    code="INVALID_IMAGE_PAYLOAD",
                    message=validation_err or "Invalid image payload.",
                ),
            ).model_dump(),
        )

    # 2. Determine / compute canonical page hash
    if payload.image_hash:
        page_hash = payload.image_hash
    else:
        page_hash = hashlib.sha256(payload.image.encode("utf-8")).hexdigest()

    cache: TranslationCache = request.app.state.cache
    registry: EngineRegistry = request.app.state.registry
    settings: Settings = request.app.state.settings

    # 3. Resolve target engine
    if payload.engine == "auto":
        target_engine_name = settings.inkshift_default_engine
        if target_engine_name == "auto":
            target_engine_name = registry.get_default().name
    else:
        target_engine_name = payload.engine

    target_translator = payload.translator or "default"
    prompt_hash = compute_prompt_hash(payload.custom_prompt)
    effective_engine_cache_key = (
        f"{target_engine_name}:{payload.reader_mode}"
        if payload.reader_mode != "manga"
        else target_engine_name
    )

    # 4. Check SQLite cache unless force_refresh is requested
    if not payload.force_refresh:
        cached_result: TranslationResponse | None = await cache.get(
            image_hash=page_hash,
            target_lang=payload.target_lang,
            engine_used=effective_engine_cache_key,
            translator_used=target_translator,
            prompt_hash=prompt_hash,
        )
        if cached_result is not None:
            logger.info(
                format_logfmt(
                    "CacheHit",
                    hash=page_hash[:16],
                    engine=target_engine_name,
                    translator=target_translator,
                )
            )
            return cached_result.model_copy(update={"from_cache": True})

    logger.info(
        format_logfmt(
            "CacheMiss",
            hash=page_hash[:16],
            engine=target_engine_name,
            translator=target_translator,
        )
    )

    # In-flight task deduplication (Singleflight pattern with composite key)
    in_flight_tasks: dict[str, asyncio.Future[TranslationResponse | JSONResponse]] = getattr(
        request.app.state, "in_flight_tasks", {}
    )
    in_flight_requests: dict[str, Request] | None = getattr(
        request.app.state, "in_flight_requests", None
    )
    if in_flight_requests is None and hasattr(request.app, "state"):
        in_flight_requests = {}
        request.app.state.in_flight_requests = in_flight_requests

    local_sem: asyncio.Semaphore | None = getattr(request.app.state, "local_semaphore", None)
    flight_key = f"{page_hash}:{payload.target_lang}:{effective_engine_cache_key}:{target_translator}:{prompt_hash}"
    if flight_key in in_flight_tasks:
        existing_req = in_flight_requests.get(flight_key) if in_flight_requests is not None else None
        if existing_req is not None and await existing_req.is_disconnected():
            logger.info(
                format_logfmt(
                    "InFlightOwnerDisconnectedEvicted",
                    hash=page_hash[:16],
                    priority=payload.priority,
                )
            )
            in_flight_tasks.pop(flight_key, None)
            if in_flight_requests is not None:
                in_flight_requests.pop(flight_key, None)
        else:
            if payload.priority == "P0" and isinstance(local_sem, PriorityLocalLock):
                local_sem.promote_to_p0(flight_key)
            logger.info(
                format_logfmt(
                    "InFlightHit",
                    hash=page_hash[:16],
                    target_lang=payload.target_lang,
                    engine=target_engine_name,
                    translator=target_translator,
                )
            )
            shared_result = await in_flight_tasks[flight_key]
            if not (isinstance(shared_result, JSONResponse) and shared_result.status_code == 499):
                return shared_result

    loop = asyncio.get_running_loop()
    future: asyncio.Future[TranslationResponse | JSONResponse] = loop.create_future()
    in_flight_tasks[flight_key] = future
    if in_flight_requests is not None:
        in_flight_requests[flight_key] = request

    try:
        try:
            engine: BaseTranslationEngine = registry.get(target_engine_name)
        except EngineNotFoundError as e:
            logger.warning(
                format_logfmt("EngineNotFound", engine=target_engine_name, error=str(e))
            )
            err_res = JSONResponse(
                status_code=400,
                content=APIErrorResponse(
                    success=False,
                    error=APIErrorDetail(
                        code="ENGINE_UNAVAILABLE",
                        message=str(e),
                    ),
                ).model_dump(),
            )
            future.set_result(err_res)
            return err_res

        if not await engine.is_available():
            msg = f"Engine '{target_engine_name}' is currently unavailable."
            logger.warning(format_logfmt("EngineUnavailable", engine=target_engine_name))
            err_res = JSONResponse(
                status_code=400,
                content=APIErrorResponse(
                    success=False,
                    error=APIErrorDetail(
                        code="ENGINE_UNAVAILABLE",
                        message=msg,
                    ),
                ).model_dump(),
            )
            future.set_result(err_res)
            return err_res

        # 5. Execute Option G1 shared detection & translation via engine
        def _disconnected_response() -> JSONResponse:
            logger.info(
                format_logfmt(
                    "RequestDisconnectedSkipped",
                    hash=page_hash[:16],
                    priority=payload.priority,
                )
            )
            return JSONResponse(
                status_code=499,
                content=APIErrorResponse(
                    success=False,
                    error=APIErrorDetail(
                        code="CLIENT_DISCONNECTED",
                        message="Client disconnected before translation started.",
                    ),
                ).model_dump(),
            )

        if await request.is_disconnected():
            err_499 = _disconnected_response()
            if not future.done():
                future.set_result(err_499)
            return err_499

        async def _run_detection_and_inference() -> TranslationResponse | JSONResponse:
            if await request.is_disconnected():
                return _disconnected_response()
            bubbles: list[DetectedBubble] | None = None
            if target_engine_name in ("local", "cloud"):
                detector = getattr(request.app.state, "detector", None)
                if detector is not None:
                    try:
                        with Image.open(io.BytesIO(raw_bytes)) as pil_img:
                            w, h = pil_img.size
                    except (OSError, ValueError, TypeError):
                        w, h = 0, 0
                    bubbles = await detector.detect(raw_bytes, w, h)
                    logger.info(
                        format_logfmt("OptionG1Detection", bubbles=len(bubbles), width=w, height=h)
                    )
            return await engine.translate(payload, bubbles=bubbles)

        if target_engine_name == "local" and local_sem is not None:
            if isinstance(local_sem, PriorityLocalLock):
                async with local_sem.acquire_priority(payload.priority, key=flight_key):
                    result = await _run_detection_and_inference()
            else:
                async with local_sem:
                    result = await _run_detection_and_inference()
        else:
            result = await _run_detection_and_inference()

        if isinstance(result, JSONResponse):
            if not future.done():
                future.set_result(result)
            return result

        response = result

        logger.info(
            format_logfmt(
                "TranslationCompleted",
                engine=engine.name,
                blocks=len(response.blocks),
                latency_ms=response.execution_time_ms,
            )
        )

        # 6. Persist response to cache ONLY if not a fallback preserving untranslated text
        if not response.is_fallback:
            effective_engine_save_key = (
                f"{response.engine_used}:{payload.reader_mode}"
                if payload.reader_mode != "manga"
                else response.engine_used
            )
            await cache.set(
                image_hash=page_hash,
                target_lang=payload.target_lang,
                response=response,
                engine_used=effective_engine_save_key,
                translator_used=target_translator,
                prompt_hash=prompt_hash,
            )
        else:
            logger.warning(
                format_logfmt(
                    "CacheBypassFallback",
                    hash=page_hash[:16],
                    engine=response.engine_used,
                    translator=target_translator,
                    reason="Response is fallback preserving untranslated text",
                )
            )

        if not future.done():
            future.set_result(response)
        return response

    except CloudEngineError as exc:
        logger.error(
            format_logfmt(
                "CloudEngineFailed",
                engine=target_engine_name,
                code=exc.code,
                status_code=exc.status_code,
                error=exc.message,
            )
        )
        cloud_err_res = JSONResponse(
            status_code=exc.status_code,
            content=APIErrorResponse(
                success=False,
                error=APIErrorDetail(
                    code=exc.code,
                    message=exc.message,
                ),
            ).model_dump(),
        )
        if not future.done():
            future.set_result(cloud_err_res)
        return cloud_err_res

    except ENGINE_EXECUTION_ERRORS as exc:
        logger.exception(
            format_logfmt(
                "EngineExecutionFailed",
                engine=target_engine_name,
            )
        )
        exec_err_res = JSONResponse(
            status_code=500,
            content=APIErrorResponse(
                success=False,
                error=APIErrorDetail(
                    code="ENGINE_EXECUTION_FAILED",
                    message=f"Translation execution failed: {exc}",
                ),
            ).model_dump(),
        )
        if not future.done():
            future.set_result(exec_err_res)
        return exec_err_res

    except BaseException as exc:
        if not future.done():
            future.set_exception(exc)
        raise

    finally:
        if in_flight_tasks.get(flight_key) is future:
            in_flight_tasks.pop(flight_key, None)
        if in_flight_requests is not None and in_flight_requests.get(flight_key) is request:
            in_flight_requests.pop(flight_key, None)

