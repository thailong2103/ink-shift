"""Pydantic v2 data models and contracts for Manga Context Graph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PageStatus = Literal["discovered", "queued", "processing", "ready", "failed"]
ChapterStatus = Literal["discovered", "reading", "completed"]


class PageItem(BaseModel):
    """Manifest item representing a single page within a chapter."""

    model_config = ConfigDict(extra="ignore")

    page_number: int = Field(..., ge=1, description="1-indexed sequence position of the page.")
    image_url: str = Field(..., min_length=1, description="Ephemeral CDN or source URL.")
    image_hash: str | None = Field(default=None, description="SHA-256 content hash if known.")
    status: PageStatus = Field(default="discovered", description="Current translation readiness.")


class ChapterContextReport(BaseModel):
    """Payload sent by extension to report full chapter discovery and manifest."""

    model_config = ConfigDict(extra="ignore")

    series_id: str = Field(..., min_length=1, description="Canonical series identifier (domain:slug).")
    series_title: str = Field(..., min_length=1, description="Clean sanitized series display title.")
    source_domain: str = Field(..., min_length=1, description="Domain where chapter is hosted.")
    cover_url: str | None = Field(default=None, description="Poster or thumbnail art URL.")

    chapter_id: str = Field(..., min_length=1, description="Canonical chapter identifier.")
    chapter_ordinal: float = Field(..., ge=0.0, description="Numeric chapter sort order (e.g. 102.0, 12.5).")
    chapter_label: str = Field(..., min_length=1, description="Display label (e.g. 'Ch. 102').")
    chapter_url: str = Field(..., min_length=1, description="Direct URL of the chapter reader page.")
    total_pages: int = Field(default=0, ge=0, description="Total page count reported or extracted.")
    pages: list[PageItem] = Field(default_factory=list, description="Ordered manifest of chapter pages.")


class ProgressUpdateRequest(BaseModel):
    """Payload to record active user reading position."""

    model_config = ConfigDict(extra="ignore")

    chapter_id: str = Field(..., min_length=1, description="Target chapter identifier.")
    page_number: int = Field(..., ge=1, description="Active page index user is currently viewing.")


class PageResponse(BaseModel):
    """Normalized page record returned by context queries."""

    model_config = ConfigDict(extra="ignore")

    page_id: str
    chapter_id: str
    page_number: int
    image_url: str
    image_hash: str | None
    status: PageStatus
    created_at: int
    updated_at: int


class ChapterPagesResponse(BaseModel):
    """Response containing ordered pages for a chapter."""

    model_config = ConfigDict(extra="ignore")

    chapter_id: str
    total_pages: int
    last_read_page: int
    status: ChapterStatus
    pages: list[PageResponse]


class ContextReportResponse(BaseModel):
    """Response returned upon reporting chapter context."""

    model_config = ConfigDict(extra="ignore")

    success: bool = True
    chapter_id: str
    series_id: str
    pages_registered: int


class ProgressUpdateResponse(BaseModel):
    """Response returned upon updating reading progress."""

    model_config = ConfigDict(extra="ignore")

    success: bool = True
    chapter_id: str
    last_read_page: int
    status: ChapterStatus

