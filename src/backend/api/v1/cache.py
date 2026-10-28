"""Cache lookup endpoint for manga page translations."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.backend.cache.sqlite_cache import TranslationCache
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
) -> TranslationResponse | JSONResponse:
    """Retrieve pre-computed translation by image_hash and target_lang without re-uploading image."""
    logger.debug(
        format_logfmt(
            "CacheCheck",
            hash=image_hash[:16],
            target_lang=target_lang,
            engine=engine or "any",
            translator=translator or "any",
        )
    )
    cache: TranslationCache = request.app.state.cache
    cached_response: TranslationResponse | None = await cache.get(
        image_hash=image_hash,
        target_lang=target_lang,
        engine_used=engine,
        translator_used=translator,
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
            content={"success": True, "deleted": deleted_count, "scope": "hash"},
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
