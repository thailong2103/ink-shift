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
) -> TranslationResponse | JSONResponse:
    """Retrieve pre-computed translation by image_hash and target_lang without re-uploading image."""
    logger.debug(
        format_logfmt(
            "CacheCheck",
            hash=image_hash[:16],
            target_lang=target_lang,
            engine=engine or "any",
        )
    )
    cache: TranslationCache = request.app.state.cache
    cached_response: TranslationResponse | None = await cache.get(
        image_hash=image_hash, target_lang=target_lang, engine_used=engine
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
