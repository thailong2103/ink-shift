"""Manga page translation endpoint."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from PIL import Image

if TYPE_CHECKING:
    from src.backend.detection.base import DetectedBubble
from src.backend.cache.sqlite_cache import TranslationCache
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
        return None, "Invalid image format. Supported formats: JPEG, PNG, WebP."

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

    # 4. Check SQLite cache unless force_refresh is requested
    if not payload.force_refresh:
        cached_result: TranslationResponse | None = await cache.get(
            image_hash=page_hash,
            target_lang=payload.target_lang,
            engine_used=target_engine_name,
        )
        if cached_result is not None:
            logger.info(
                format_logfmt("CacheHit", hash=page_hash[:16], engine=target_engine_name)
            )
            return cached_result.model_copy(update={"from_cache": True})

    logger.info(
        format_logfmt("CacheMiss", hash=page_hash[:16], engine=target_engine_name)
    )

    # In-flight task deduplication (Singleflight pattern)
    in_flight_tasks: dict[str, asyncio.Future[TranslationResponse | JSONResponse]] = getattr(
        request.app.state, "in_flight_tasks", {}
    )
    if page_hash in in_flight_tasks:
        logger.info(
            format_logfmt(
                "InFlightHit",
                hash=page_hash[:16],
                engine=target_engine_name,
            )
        )
        return await in_flight_tasks[page_hash]

    loop = asyncio.get_running_loop()
    future: asyncio.Future[TranslationResponse | JSONResponse] = loop.create_future()
    in_flight_tasks[page_hash] = future

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
        local_sem: asyncio.Semaphore | None = getattr(request.app.state, "local_semaphore", None)

        async def _run_detection_and_inference() -> TranslationResponse:
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
            async with local_sem:
                response = await _run_detection_and_inference()
        else:
            response = await _run_detection_and_inference()

        logger.info(
            format_logfmt(
                "TranslationCompleted",
                engine=engine.name,
                blocks=len(response.blocks),
                latency_ms=response.execution_time_ms,
            )
        )

        # 6. Persist response to cache
        await cache.set(
            image_hash=page_hash,
            target_lang=payload.target_lang,
            response=response,
            engine_used=response.engine_used,
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
        in_flight_tasks.pop(page_hash, None)

