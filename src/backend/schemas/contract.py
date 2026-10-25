"""Contract schema models and boundary validators for InkShift.

Defines the immutable canonical data transfer objects between the Chromium
Extension (extension-core) and FastAPI backend (backend-engine).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Bounding box coordinate: integer in [0, 1000] representing normalized per-mille
Coordinate = Annotated[int, Field(ge=0, le=1000, description="Normalized coordinate [0, 1000]")]

# Normalized bounding box tuple: [ymin, xmin, ymax, xmax]
BoundingBox = tuple[Coordinate, Coordinate, Coordinate, Coordinate]

# Relative percent for polygon vertices: float in [0.0, 100.0] representing % relative to bounding box
RelativePercent = Annotated[float, Field(ge=0.0, le=100.0, description="Relative coordinate percent [0.0, 100.0]")]
PolygonPoint = tuple[RelativePercent, RelativePercent]

# SHA-256 Hex Hash: exactly 64 hexadecimal characters (prevents path traversal)
HashString = Annotated[
    str,
    Field(
        pattern=r"^[a-fA-F0-9]{64}$",
        description="SHA-256 64-character hexadecimal digest",
    ),
]


class TranslatedBlock(BaseModel):
    """Represents a single translated manga speech bubble or text block."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique identifier for the block")
    box: BoundingBox = Field(
        description="Normalized bounding box tuple [ymin, xmin, ymax, xmax] in range 0-1000"
    )
    polygon: list[PolygonPoint] | None = Field(
        default=None,
        description="18-25 vertices in 0-100% relative coordinates for clip-path mask",
    )
    parent_bubble_id: str | None = Field(
        default=None,
        description="Parent bubble identifier for merged connected speech balloons",
    )
    parent_box: BoundingBox | None = Field(
        default=None,
        description="Parent bubble bounding box [ymin, xmin, ymax, xmax] if block is a child text in a merged bubble",
    )
    source_text: str | None = Field(
        default=None,
        description="Raw OCR text extracted from manga speech bubble",
    )
    translated_text: str = Field(
        description="Translated text in target language"
    )
    direction: Literal["vertical", "horizontal"] = Field(
        default="vertical",
        description="Reading direction detected in original text",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Detection and translation confidence score in range [0.0, 1.0]",
    )

    @model_validator(mode="after")
    def validate_box_order(self) -> "TranslatedBlock":
        """Ensure bounding box min coordinates do not exceed max coordinates."""
        ymin, xmin, ymax, xmax = self.box
        if ymin > ymax:
            raise ValueError(f"ymin ({ymin}) must not be greater than ymax ({ymax})")
        if xmin > xmax:
            raise ValueError(f"xmin ({xmin}) must not be greater than xmax ({xmax})")
        if self.parent_box is not None:
            p_ymin, p_xmin, p_ymax, p_xmax = self.parent_box
            if p_ymin > p_ymax:
                raise ValueError(f"parent_box ymin ({p_ymin}) must not be greater than ymax ({p_ymax})")
            if p_xmin > p_xmax:
                raise ValueError(f"parent_box xmin ({p_xmin}) must not be greater than xmax ({p_xmax})")
        return self


class TranslationRequest(BaseModel):
    """Payload sent by Chrome Extension to request manga page translation."""

    model_config = ConfigDict(extra="forbid")

    image: str = Field(
        max_length=20_000_000,
        description="Base64 encoded image string or Data URL (capped at 20MB characters / ~15MB binary)",
    )
    image_hash: HashString | None = Field(
        default=None,
        description="Precomputed SHA-256 hex digest for caching and deduplication",
    )
    source_lang: str = Field(
        default="auto",
        description="Source manga language code (e.g. 'ja', 'auto')",
    )
    target_lang: str = Field(
        default="vi",
        description="Target translation language code (default: 'vi')",
    )
    engine: Literal[
        "local",
        "cloud",
        "mock",
        "auto",
    ] = Field(
        default="auto",
        description="Requested translation engine mode ('local', 'cloud', 'mock', 'auto')",
    )
    provider: str | None = Field(
        default=None,
        description="Optional cloud LLM provider override ('google', 'gemini', 'openai', 'anthropic', 'custom', 'xkiro', None=default)",
    )
    model: str | None = Field(
        default=None,
        description="Optional dynamic LLM model override (e.g. 'gemini-2.5-flash', 'gpt-4o', 'claude-3-5-sonnet', None=default)",
    )
    translator: str | None = Field(
        default=None,
        description="Optional local text translator override ('google-free', 'llm-gemini', 'llm-openai', 'llm-qwen', 'llm-text', None=default)",
    )
    force_refresh: bool = Field(
        default=False,
        description="If True, bypasses SQLite cache and forces fresh re-translation",
    )
    chapter_url: str | None = Field(
        default=None,
        description="Optional chapter or page URL context for chapter-level language caching",
    )

    @field_validator("engine", mode="before")
    @classmethod
    def normalize_engine(cls, v: Any) -> str:
        """Normalize legacy or empty engine strings gracefully."""
        if not v or v == "auto":
            return "auto"
        if v in ("local-manga", "local-rapid"):
            return "local"
        if v in ("cloud-gemini", "cloud-xkiro"):
            return "cloud"
        return str(v)

    @field_validator("provider", "translator", "model", mode="before")
    @classmethod
    def normalize_empty_to_none(cls, v: Any) -> Any:
        """Convert empty string override to None so defaults apply cleanly."""
        if v == "":
            return None
        return v

    @field_validator("source_lang", mode="before")
    @classmethod
    def normalize_source_lang(cls, v: Any) -> str:
        """Default empty source_lang to 'auto'."""
        if not v:
            return "auto"
        return str(v)


class TranslationResponse(BaseModel):
    """Response returned upon successful manga page translation."""

    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = True
    page_hash: HashString = Field(
        description="SHA-256 hex digest of the processed manga page"
    )
    engine_used: str = Field(
        description="Identifier of engine that performed translation"
    )
    execution_time_ms: int = Field(
        ge=0,
        description="Processing latency in milliseconds",
    )
    from_cache: bool = Field(
        default=False,
        description="Indicates whether result was served from SQLite cache",
    )
    blocks: list[TranslatedBlock] = Field(
        default_factory=list,
        description="List of detected and translated text blocks",
    )


class APIErrorDetail(BaseModel):
    """Structured machine-readable error details."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable error explanation")
    details: Any | None = Field(
        default=None,
        description="Optional additional diagnostic context",
    )


class APIErrorResponse(BaseModel):
    """Standardized error envelope returned by all API endpoints."""

    model_config = ConfigDict(extra="forbid")

    success: Literal[False] = False
    error: APIErrorDetail = Field(description="Structured error details")
