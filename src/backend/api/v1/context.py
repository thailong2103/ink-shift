"""FastAPI router endpoints for Manga Context Graph management."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.backend.context.schemas import (
    ChapterContextReport,
    ChapterPagesResponse,
    ContextReportResponse,
    ProgressUpdateRequest,
    ProgressUpdateResponse,
)
from src.backend.context.store import ContextStore
from src.backend.logging import format_logfmt, get_logger
from src.backend.schemas.contract import APIErrorDetail, APIErrorResponse

logger = get_logger("api.context")

router = APIRouter(prefix="/context", tags=["Context"])


@router.post(
    "/report",
    response_model=ContextReportResponse,
    status_code=200,
    responses={
        200: {"model": ContextReportResponse, "description": "Context manifest registered successfully"},
        500: {"model": APIErrorResponse, "description": "Database write error"},
    },
)
async def report_chapter_context(
    request: Request,
    report: ChapterContextReport,
) -> ContextReportResponse | JSONResponse:
    """Register manga series, chapter, and page manifest in the Context Graph."""
    logger.info(
        format_logfmt(
            "ContextReportReceived",
            series_id=report.series_id,
            chapter_id=report.chapter_id,
            pages=len(report.pages),
        )
    )
    store: ContextStore = request.app.state.context_store
    try:
        await store.report_context(report)
        return ContextReportResponse(
            success=True,
            chapter_id=report.chapter_id,
            series_id=report.series_id,
            pages_registered=len(report.pages),
        )
    except Exception as exc:
        logger.exception(format_logfmt("ContextStoreFailed", chapter_id=report.chapter_id))
        return JSONResponse(
            status_code=500,
            content=APIErrorResponse(
                success=False,
                error=APIErrorDetail(
                    code="CONTEXT_STORAGE_ERROR",
                    message="Failed to persist chapter manifest context",
                    details={"error": str(exc)},
                ),
            ).model_dump(),
        )


@router.patch(
    "/progress",
    response_model=ProgressUpdateResponse,
    responses={
        200: {"model": ProgressUpdateResponse, "description": "Reading progress updated"},
        404: {"model": APIErrorResponse, "description": "Chapter not found"},
    },
)
async def update_reading_progress(
    request: Request,
    update: ProgressUpdateRequest,
) -> ProgressUpdateResponse | JSONResponse:
    """Update active reading page for a given chapter."""
    logger.debug(
        format_logfmt(
            "ReadingProgressUpdate",
            chapter_id=update.chapter_id,
            page=update.page_number,
        )
    )
    store: ContextStore = request.app.state.context_store
    updated = await store.update_reading_progress(update.chapter_id, update.page_number)
    if not updated:
        return JSONResponse(
            status_code=404,
            content=APIErrorResponse(
                success=False,
                error=APIErrorDetail(
                    code="CHAPTER_NOT_FOUND",
                    message=f"Chapter '{update.chapter_id}' not found in context graph",
                    details={"chapter_id": update.chapter_id},
                ),
            ).model_dump(),
        )

    details = await store.get_chapter_details(update.chapter_id)
    status = details.status if details else "reading"

    return ProgressUpdateResponse(
        success=True,
        chapter_id=update.chapter_id,
        last_read_page=update.page_number,
        status=status,
    )


@router.get(
    "/chapters/{chapter_id}/pages",
    response_model=ChapterPagesResponse,
    responses={
        200: {"model": ChapterPagesResponse, "description": "Chapter pages and status list"},
        404: {"model": APIErrorResponse, "description": "Chapter not found"},
    },
)
async def get_chapter_pages(
    request: Request,
    chapter_id: str,
) -> ChapterPagesResponse | JSONResponse:
    """Retrieve ordered list of chapter pages and their translation statuses."""
    logger.debug(format_logfmt("FetchingChapterPages", chapter_id=chapter_id))
    store: ContextStore = request.app.state.context_store
    details = await store.get_chapter_details(chapter_id)
    if details is None:
        return JSONResponse(
            status_code=404,
            content=APIErrorResponse(
                success=False,
                error=APIErrorDetail(
                    code="CHAPTER_NOT_FOUND",
                    message=f"Chapter '{chapter_id}' not found in context graph",
                    details={"chapter_id": chapter_id},
                ),
            ).model_dump(),
        )

    return details
