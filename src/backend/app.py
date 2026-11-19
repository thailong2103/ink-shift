"""FastAPI application factory, lifespan management, and middleware configuration."""

import asyncio
import gc
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.backend.api.v1.router import v1_router
from src.backend.api.v1.translate import PriorityLocalLock
from src.backend.cache.sqlite_cache import TranslationCache
from src.backend.config import Settings
from src.backend.context import ContextStore
from src.backend.detection import YOLO11Detector
from src.backend.engines.cloud import (
    AnthropicProvider,
    CloudEngineError,
    CloudTranslationEngine,
    ContentSafetyBlockedError,
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderRegistry,
    RateLimitExceededError,
    UpstreamTimeoutError,
)
from src.backend.engines.local import (
    GoogleFreeTranslator,
    LLMTextTranslator,
    LocalTranslationEngine,
    OCRRouter,
    RapidOCRAdapter,
    TranslatorRegistry,
)
from src.backend.engines.mock import MockTranslationEngine
from src.backend.engines.registry import EngineRegistry
from src.backend.logging import format_logfmt, get_logger, setup_logging
from src.backend.schemas.contract import APIErrorDetail, APIErrorResponse
from src.backend.security.middleware import (
    ALLOWED_CORS_ORIGINS,
    SecurityHeadersMiddleware,
)

logger = get_logger("inkshift.app")


def _latest_loaded_monotonic(detector: Any, rapid_ocr: Any) -> float | None:
    """Return latest last-used monotonic timestamp across loaded local ONNX components."""
    timestamps: list[float] = []
    for component in (detector, rapid_ocr):
        if component is not None and bool(getattr(component, "is_loaded", False)):
            ts = getattr(component, "last_used_monotonic", None)
            if isinstance(ts, (int, float)):
                timestamps.append(float(ts))
    return max(timestamps) if timestamps else None


def _unload_local_sessions(detector: Any, rapid_ocr: Any) -> tuple[bool, bool]:
    """Safely invoke unload methods on detector and rapid_ocr adapters."""
    det_unloaded = False
    ocr_unloaded = False
    det_unload_fn = getattr(detector, "unload_session", None)
    if callable(det_unload_fn):
        det_unloaded = bool(det_unload_fn())
    ocr_unload_fn = getattr(rapid_ocr, "unload_sessions", None)
    if callable(ocr_unload_fn):
        ocr_unloaded = bool(ocr_unload_fn())
    if det_unloaded or ocr_unloaded:
        gc.collect()
    return det_unloaded, ocr_unloaded


async def maybe_unload_idle_local_models(
    detector: Any,
    rapid_ocr: Any,
    local_lock: PriorityLocalLock,
    idle_ttl_seconds: float,
    now_monotonic: float | None = None,
) -> bool:
    """Release loaded ONNX sessions when idle past TTL without contending with active inference."""
    if idle_ttl_seconds <= 0.0:
        return False

    latest = _latest_loaded_monotonic(detector, rapid_ocr)
    if latest is None:
        return False

    check_now = time.monotonic() if now_monotonic is None else now_monotonic
    if (check_now - latest) < idle_ttl_seconds or local_lock.locked():
        return False

    async with local_lock.acquire_priority("P2"):
        recheck_latest = _latest_loaded_monotonic(detector, rapid_ocr)
        recheck_now = time.monotonic() if now_monotonic is None else now_monotonic
        if recheck_latest is None or (recheck_now - recheck_latest) < idle_ttl_seconds:
            return False

        det_unloaded, ocr_unloaded = _unload_local_sessions(detector, rapid_ocr)
        if det_unloaded or ocr_unloaded:
            logger.info(
                format_logfmt(
                    "LocalModelsIdleUnloaded",
                    idle_ttl_s=round(idle_ttl_seconds, 2),
                    detector_unloaded=det_unloaded,
                    ocr_unloaded=ocr_unloaded,
                )
            )
            return True
    return False


async def _idle_unload_loop(
    detector: Any,
    rapid_ocr: Any,
    local_lock: PriorityLocalLock,
    idle_ttl_seconds: float,
    poll_interval_seconds: float,
) -> None:
    """Periodically check local inference idleness and release ONNX sessions cleanly."""
    while True:
        await asyncio.sleep(poll_interval_seconds)
        try:
            await maybe_unload_idle_local_models(
                detector=detector,
                rapid_ocr=rapid_ocr,
                local_lock=local_lock,
                idle_ttl_seconds=idle_ttl_seconds,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning(format_logfmt("IdleUnloadLoopError", error=str(exc)))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    settings: Settings = getattr(app.state, "settings", None) or Settings()
    app.state.settings = settings

    # 0. Initialize Centralized Dual-Handler Logging (Console + Rotating File)
    setup_logging(
        log_level=settings.inkshift_log_level,
        log_dir=settings.inkshift_log_dir,
    )

    # 1. Initialize SQLite Cache
    cache = getattr(app.state, "cache", None) or TranslationCache(db_path=settings.inkshift_db_path)
    await cache.initialize()
    app.state.cache = cache

    # 1b. Initialize SQLite Manga Context Graph Store
    context_store = getattr(app.state, "context_store", None) or ContextStore(db_path=settings.inkshift_db_path)
    await context_store.initialize()
    app.state.context_store = context_store

    # 1c. Concurrency Limiters & In-Flight Lock Map
    app.state.local_semaphore = getattr(app.state, "local_semaphore", None) or PriorityLocalLock()
    app.state.in_flight_tasks = getattr(app.state, "in_flight_tasks", None) or {}



    # 2. Initialize Shared Async HTTP Client
    http_client = (
        getattr(app.state, "http_client", None)
        or httpx.AsyncClient(
            timeout=max(settings.inkshift_cloud_timeout, settings.inkshift_local_llm_timeout) + 5.0
        )
    )
    app.state.http_client = http_client

    # 3. Initialize Engine Registry & Deterministic Mock Engine
    registry = getattr(app.state, "registry", None) or EngineRegistry()
    mock_engine = MockTranslationEngine()
    is_mock_default = settings.inkshift_default_engine == "mock"
    registry.register(mock_engine, is_default=is_mock_default)

    # 4. Initialize Shared YOLO11 Speech Bubble Detector for Option G1 Gateway Detection
    detector = getattr(app.state, "detector", None) or YOLO11Detector(
        model_path=settings.inkshift_local_detector_model_path or None,
        execution_provider=settings.inkshift_local_execution_provider,
        cpu_threads=settings.inkshift_local_cpu_threads,
    )
    app.state.detector = detector

    # 5. Initialize Cloud Vision Providers & Engine
    provider_registry = getattr(app.state, "cloud_provider_registry", None) or ProviderRegistry(
        default_provider_name=settings.inkshift_cloud_provider
    )
    gemini_provider = GeminiProvider(
        api_key=settings.gemini_api_key or None,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        http_client=http_client,
        timeout_seconds=settings.inkshift_cloud_timeout,
    )
    openai_provider = OpenAICompatibleProvider(
        api_key=settings.openai_api_key or None,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
        http_client=http_client,
        timeout_seconds=settings.inkshift_cloud_timeout,
        name="openai",
    )
    anthropic_provider = AnthropicProvider(
        api_key=settings.anthropic_api_key or None,
        model=settings.anthropic_model,
        base_url=settings.anthropic_base_url,
        http_client=http_client,
        timeout_seconds=settings.inkshift_cloud_timeout,
    )
    custom_provider = OpenAICompatibleProvider(
        api_key=settings.custom_api_key or None,
        model=settings.custom_model,
        base_url=settings.custom_base_url,
        http_client=http_client,
        timeout_seconds=settings.inkshift_cloud_timeout,
        name="custom",
    )
    provider_registry.register("google", gemini_provider)
    provider_registry.register("gemini", gemini_provider)
    provider_registry.register("openai", openai_provider)
    provider_registry.register("anthropic", anthropic_provider)
    provider_registry.register("custom", custom_provider)
    provider_registry.register("xkiro", custom_provider)

    cloud_engine = CloudTranslationEngine(registry=provider_registry, name="cloud")
    is_cloud_default = settings.inkshift_default_engine == "cloud"
    registry.register(cloud_engine, is_default=is_cloud_default)

    # 6. Initialize Local On-Device Translation OCR and Translators
    rapid_ocr_adapter = getattr(app.state, "rapid_ocr", None) or RapidOCRAdapter(
        execution_provider=settings.inkshift_local_execution_provider,
        det_limit_side_len=settings.inkshift_local_ocr_det_limit_side_len,
        cpu_threads=settings.inkshift_local_cpu_threads,
    )
    app.state.rapid_ocr = rapid_ocr_adapter
    ocr_router = OCRRouter(
        rapid_ocr=rapid_ocr_adapter,
        default_model=settings.inkshift_local_default_ocr,
    )

    translator_registry = getattr(app.state, "local_translator_registry", None) or TranslatorRegistry(
        default_translator_name=settings.inkshift_local_default_translator
    )
    google_translator = GoogleFreeTranslator()
    llm_google_translator = LLMTextTranslator(
        provider="google",
        http_client=http_client,
        timeout_seconds=settings.inkshift_cloud_timeout,
        name="llm-google",
    )
    llm_openai_translator = LLMTextTranslator(
        provider="openai",
        api_key=settings.openai_api_key or None,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
        http_client=http_client,
        timeout_seconds=settings.inkshift_cloud_timeout,
        name="llm-openai",
    )
    llm_anthropic_translator = LLMTextTranslator(
        provider="anthropic",
        api_key=settings.anthropic_api_key or None,
        model=settings.anthropic_model,
        base_url=settings.anthropic_base_url,
        http_client=http_client,
        timeout_seconds=settings.inkshift_cloud_timeout,
        name="llm-anthropic",
    )
    llm_custom_translator = LLMTextTranslator(
        provider="custom",
        api_key=settings.custom_api_key or None,
        model=settings.custom_model,
        base_url=settings.custom_base_url,
        http_client=http_client,
        timeout_seconds=settings.inkshift_local_llm_timeout,
        name="llm-custom",
    )
    translator_registry.register("google-free", google_translator)
    translator_registry.register("llm-google", llm_google_translator)
    translator_registry.register("llm-openai", llm_openai_translator)
    translator_registry.register("llm-anthropic", llm_anthropic_translator)
    translator_registry.register("llm-custom", llm_custom_translator)

    # Maintain backward compatibility aliases
    translator_registry.register_alias("llm-gemini", "llm-google")
    translator_registry.register_alias("llm-qwen", "llm-custom")

    # Maintain alias for generic llm-text pointing to active cloud provider
    default_llm_target = "llm-google" if settings.inkshift_cloud_provider in ("gemini", "google") else "llm-custom"
    translator_registry.register_alias("llm-text", default_llm_target)

    local_engine = LocalTranslationEngine(
        ocr_router=ocr_router,
        translator_registry=translator_registry,
        name="local",
        default_ocr="auto",
    )
    is_local_default = settings.inkshift_default_engine == "local"
    registry.register(local_engine, is_default=is_local_default)

    app.state.registry = registry
    idle_ttl = settings.inkshift_local_idle_unload_seconds
    idle_unload_task: asyncio.Task[None] | None = None
    if idle_ttl > 0.0:
        poll_interval = min(15.0, max(0.05, idle_ttl / 4.0))
        idle_unload_task = asyncio.create_task(
            _idle_unload_loop(
                detector=detector,
                rapid_ocr=rapid_ocr_adapter,
                local_lock=app.state.local_semaphore,
                idle_ttl_seconds=idle_ttl,
                poll_interval_seconds=poll_interval,
            )
        )
    app.state.idle_unload_task = idle_unload_task

    app_logger = setup_logging(
        log_level=settings.inkshift_log_level,
        log_dir=settings.inkshift_log_dir,
    )
    app_logger.info(
        "InkShift Backend initialized. Default engine: %s, Provider: %s, DetLimit: %d, IdleUnload: %.0fs, DB: %s",
        settings.inkshift_default_engine,
        settings.inkshift_local_execution_provider,
        settings.inkshift_local_ocr_det_limit_side_len,
        idle_ttl,
        settings.inkshift_db_path,
    )

    yield

    # Teardown
    if idle_unload_task is not None:
        idle_unload_task.cancel()
        with suppress(asyncio.CancelledError):
            await idle_unload_task
    _unload_local_sessions(detector, rapid_ocr_adapter)
    await app.state.http_client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="InkShift Backend Engine",
        description="Local AI-powered manga translation engine coordinator.",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.state.settings = settings or Settings()

    # 1. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_CORS_ORIGINS,
        allow_origin_regex=r"^chrome-extension://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Localhost Security Headers Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 3. Mount API Routers
    app.include_router(v1_router)

    # 4. Standard Structured Validation Error Handler
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            format_logfmt(
                "RequestValidationFailed",
                method=request.method,
                path=request.url.path,
                errors=len(exc.errors()),
            )
        )
        error_resp = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code="VALIDATION_ERROR",
                message="Request validation failed.",
                details=exc.errors(),
            ),
        )
        return JSONResponse(status_code=422, content=error_resp.model_dump())

    # 5. Cloud Safety Policy Refusal Handler
    @app.exception_handler(ContentSafetyBlockedError)
    async def content_safety_blocked_handler(
        request: Request, exc: ContentSafetyBlockedError
    ) -> JSONResponse:
        logger.warning(
            format_logfmt(
                "ContentSafetyBlocked",
                method=request.method,
                path=request.url.path,
                code=exc.code,
                reason=exc.message,
            )
        )
        error_resp = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code=exc.code,
                message=exc.message,
            ),
        )
        return JSONResponse(status_code=422, content=error_resp.model_dump())

    # 6. Cloud Rate Limit Handler
    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_exceeded_handler(
        request: Request, exc: RateLimitExceededError
    ) -> JSONResponse:
        logger.warning(
            format_logfmt(
                "RateLimitExceeded",
                method=request.method,
                path=request.url.path,
                code=exc.code,
                reason=exc.message,
            )
        )
        error_resp = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code=exc.code,
                message=exc.message,
            ),
        )
        return JSONResponse(status_code=429, content=error_resp.model_dump())

    # 7. Cloud Upstream Timeout Handler
    @app.exception_handler(UpstreamTimeoutError)
    async def upstream_timeout_handler(
        request: Request, exc: UpstreamTimeoutError
    ) -> JSONResponse:
        logger.error(
            format_logfmt(
                "UpstreamTimeout",
                method=request.method,
                path=request.url.path,
                code=exc.code,
                reason=exc.message,
            )
        )
        error_resp = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code=exc.code,
                message=exc.message,
            ),
        )
        return JSONResponse(status_code=504, content=error_resp.model_dump())

    # 8. Generic Cloud Engine Domain Error Handler (Auth, Execution, etc.)
    @app.exception_handler(CloudEngineError)
    async def cloud_engine_exception_handler(
        request: Request, exc: CloudEngineError
    ) -> JSONResponse:
        logger.error(
            format_logfmt(
                "CloudEngineError",
                method=request.method,
                path=request.url.path,
                status_code=exc.status_code,
                code=exc.code,
                reason=exc.message,
            )
        )
        error_resp = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code=exc.code,
                message=exc.message,
            ),
        )
        return JSONResponse(status_code=exc.status_code, content=error_resp.model_dump())

    # 9. Structured HTTP Exception Handler
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "HTTP_ERROR"
        message = str(exc.detail)
        details = None
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code", "HTTP_ERROR")
            message = exc.detail.get("message", str(exc.detail))
            details = exc.detail.get("details")

        logger.warning(
            format_logfmt(
                "HTTPException",
                method=request.method,
                path=request.url.path,
                status_code=exc.status_code,
                code=code,
                reason=message,
            )
        )
        error_resp = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code=code,
                message=message,
                details=details,
            ),
        )
        return JSONResponse(status_code=exc.status_code, content=error_resp.model_dump())

    # 10. Global Unhandled Internal Exception Handler
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            format_logfmt(
                "UnhandledInternalError",
                method=request.method,
                path=request.url.path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
        )
        error_resp = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected server error occurred.",
            ),
        )
        return JSONResponse(status_code=500, content=error_resp.model_dump())

    return app


# Default singleton application for uvicorn
app = create_app()
