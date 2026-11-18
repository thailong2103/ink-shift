"""Cache lookup endpoint for manga page translations."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.backend.cache.sqlite_cache import TranslationCache, compute_prompt_hash
from src.backend.logging import format_logfmt, get_logger
from src.backend.schemas.contract import (
    APIErrorDetail,
    APIErrorResponse,
    HashString,
    TranslationResponse,
)

logger = get_logger("api.cache")

router = APIRouter()


@router.get(
    "/cache/{image_hash}",
    response_model=TranslationResponse,
    responses={
        200: {"model": TranslationResponse, "description": "Cached translation found"},
        404: {"model": APIErrorResponse, "description": "Page not cached"},
    },
)
async def get_cached_translation(
    request: Request,
    image_hash: HashString,
    target_lang: str = Query(default="vi", description="Target language code"),
    engine: str | None = Query(default=None, description="Optional engine mode used ('local', 'cloud')"),
    translator: str | None = Query(default=None, description="Optional translator mode used"),
    prompt_hash: str | None = Query(default=None, description="Optional custom prompt hash filter"),
    custom_prompt: str | None = Query(default=None, description="Optional raw custom prompt to hash for cache lookup"),
    reader_mode: str | None = Query(default=None, description="Optional reader mode ('manga', 'text')"),
) -> TranslationResponse | JSONResponse:
    """Retrieve pre-computed translation by image_hash and target_lang without re-uploading image."""
    effective_engine = (
        f"{engine}:{reader_mode}"
        if engine and reader_mode and reader_mode != "manga"
        else engine
    )
    effective_prompt_hash = (
        prompt_hash
        if prompt_hash is not None
        else (compute_prompt_hash(custom_prompt) if custom_prompt else None)
    )
    logger.debug(
        format_logfmt(
            "CacheCheck",
            hash=image_hash[:16],
            target_lang=target_lang,
            engine=effective_engine or "any",
            translator=translator or "any",
            prompt_hash=effective_prompt_hash or "none",
        )
    )
    cache: TranslationCache = request.app.state.cache
    cached_response: TranslationResponse | None = await cache.get(
        image_hash=image_hash,
        target_lang=target_lang,
        engine_used=effective_engine,
        translator_used=translator,
        prompt_hash=effective_prompt_hash,
    )

    if cached_response is None:
        logger.debug(format_logfmt("CacheMiss", hash=image_hash[:16]))
        error_payload = APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code="CACHE_MISS",
                message="Page has not been translated yet",
                details={"image_hash": image_hash, "target_lang": target_lang},
            ),
        )
        return JSONResponse(status_code=404, content=error_payload.model_dump())

    logger.debug(format_logfmt("CacheHit", hash=image_hash[:16]))
    return cached_response.model_copy(update={"from_cache": True})


@router.delete(
    "/cache",
    responses={
        200: {"description": "Cache cleared successfully"},
        400: {"model": APIErrorResponse, "description": "Invalid delete parameters"},
    },
)
async def delete_cached_translation(
    request: Request,
    all: bool = Query(default=False, description="Clear entire translation cache if true"),
    image_hash: str | None = Query(default=None, description="Specific image hash to delete"),
    target_lang: str | None = Query(default=None, description="Optional target language filter"),
    engine: str | None = Query(default=None, description="Optional engine filter"),
) -> JSONResponse:
    """Delete all cached translations or specific entry by image_hash."""
    cache: TranslationCache = request.app.state.cache
    if all:
        deleted_count = await cache.clear()
        logger.info(format_logfmt("CacheWiped", count=deleted_count))
        return JSONResponse(
            status_code=200,
            content={"success": True, "deleted": deleted_count, "scope": "all"},
        )

    if image_hash:
        deleted_count = await cache.delete(
            image_hash=image_hash,
            target_lang=target_lang,
            engine_used=engine,
        )
        logger.info(format_logfmt("CacheEntryDeleted", hash=image_hash[:16], count=deleted_count))
        return JSONResponse(
            status_code=200,
            content={"success": True, "deleted": deleted_count, "scope": "single"},
        )

    return JSONResponse(
        status_code=400,
        content=APIErrorResponse(
            success=False,
            error=APIErrorDetail(
                code="INVALID_CACHE_DELETE_REQUEST",
                message="Either 'all=true' or 'image_hash' must be provided",
            ),
        ).model_dump(),
    )
