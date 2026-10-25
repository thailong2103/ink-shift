"""FastAPI application factory, lifespan management, and middleware configuration."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.backend.api.v1.router import v1_router
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
    MangaOCRAdapter,
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
    app.state.local_semaphore = getattr(app.state, "local_semaphore", None) or asyncio.Semaphore(1)
    app.state.in_flight_tasks = getattr(app.state, "in_flight_tasks", None) or {}



    # 2. Initialize Shared Async HTTP Client
    http_client = (
        getattr(app.state, "http_client", None)
        or httpx.AsyncClient(timeout=settings.inkshift_cloud_timeout + 5.0)
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
    manga_ocr_adapter = MangaOCRAdapter(
        model_path=settings.inkshift_local_manga_ocr_model_path or None,
    )
    rapid_ocr_adapter = RapidOCRAdapter()
    ocr_router = OCRRouter(
        manga_ocr=manga_ocr_adapter,
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
        timeout_seconds=settings.inkshift_cloud_timeout,
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
    app_logger = setup_logging(
        log_level=settings.inkshift_log_level,
        log_dir=settings.inkshift_log_dir,
    )
    app_logger.info("InkShift Backend initialized. Default engine: %s, DB: %s", settings.inkshift_default_engine, settings.inkshift_db_path)

    yield

    # Teardown
    await app.state.http_client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="InkShift Backend Engine",
        description="Local AI-powered manga translation engine coordinator.",
        version="0.1.0",
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
