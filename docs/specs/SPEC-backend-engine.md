# Spec: Backend Runtime, Pluggable Engine Coordinator, and Cache (`backend-engine`)

> **Module ID:** `backend-engine`  
> **Module ID:** `backend-engine`  
> **Source ADR:** [ADR-003-backend-engine-architecture.md](../decisions/ADR-003-backend-engine-architecture.md) & [ADR-008-consolidated-engine-architecture-and-shared-detection.md](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md)  
> **Parent Map:** [CAPABILITY_MAP.md](CAPABILITY_MAP.md)  
> **Contract Spec:** [SPEC-api-contract.md](SPEC-api-contract.md)  
> **Status:** Approved by Solo Developer (@human)  
> **Phase:** Module 2 Execution Runtime & Phase 15 Engine Restructure  
> **Language Policy:** Official English document tracked in Git. Parallel Vietnamese copy at [docs/vi/specs/SPEC-backend-engine.md](../vi/specs/SPEC-backend-engine.md).

---

## 1. Objective

Provide a robust, high-performance, and secure local backend runtime (`backend-engine`) running on `127.0.0.1:8000`. The server acts as the central coordinator between client interfaces (Chromium Extension and Zen Web Reader) and pluggable translation engines (`cloud`, `local`, and `mock`).

### Core Capabilities:
1. **API Contract Enforcement:** Host FastAPI endpoints (`POST /api/v1/translate`, `GET /api/v1/cache/{image_hash}`, `GET /api/v1/health`) strictly adhering to Pydantic schemas defined in Module 1 (`api-contract`).
2. **Shared Gateway Detection (Option G1):** Execute the shared YOLO11 detector once at the API gateway layer (`translate.py`) for un-cached requests, passing pre-sorted bubbles into `engine.translate()`.
3. **High-Speed SQLite Caching:** Store and retrieve page-level translations indexed by `(image_hash, target_lang, engine_used)` composite key using `aiosqlite` in WAL mode with sub-5ms lookup latency.
4. **Consolidated Engine Abstraction:** Provide an extensible `BaseTranslationEngine` interface and `EngineRegistry` factory hosting exactly 3 canonical engines: `"local"`, `"cloud"`, and `"mock"`. Dynamic sub-delegation is handled via `ProviderRegistry` (Cloud) and `TranslatorRegistry` (Local).
5. **Localhost Boundary Defense:** Enforce loopback binding (`127.0.0.1`), CORS origin whitelisting, custom client header verification (`X-InkShift-Client`), and payload size caps.

---

## 2. Tech Stack & Commands

### 2.1 Dependencies
- **Runtime:** Python 3.11+
- **Web Framework:** `fastapi >= 0.110.0`, `uvicorn[standard] >= 0.28.0`
- **Database Driver:** `aiosqlite >= 0.20.0`
- **Async HTTP Client:** `httpx >= 0.27.0`
- **Data Validation:** `pydantic >= 2.6.0` (from Module 1)
- **Computer Vision & Inference:** `onnxruntime-directml`, `opencv-python-headless`, `pillow`
- **Testing & Quality:** `pytest >= 8.0.0`, `pytest-asyncio >= 0.23.0`, `mypy >= 1.9.0`, `ruff >= 0.3.0`

### 2.2 Commands
```bash
# Development Server (Loopback on port 8000)
uvicorn src.backend.app:app --host 127.0.0.1 --port 8000 --reload

# Fast Quality Checks (Floor Guard + Strict Types + Lint)
python scripts/check.py --fast

# Test Suite with Coverage (Must satisfy >= 80% per CONSTRAINTS.md)
python scripts/check.py --full
```

---

## 3. Project Structure

```
src/backend/
├── __init__.py
├── app.py                      # FastAPI application factory, lifespan, CORS, middleware
├── config.py                   # Environment settings (DB path, host, port, active engine)
├── api/
│   ├── __init__.py
│   └── v1/
│       ├── __init__.py
│       ├── router.py           # v1 APIRouter aggregating all endpoints
│       ├── translate.py        # POST /api/v1/translate endpoint handler (Option G1 Detection)
│       ├── cache.py            # GET /api/v1/cache/{image_hash} endpoint handler
│       └── health.py           # GET /api/v1/health status endpoint handler
├── cache/
│   ├── __init__.py
│   └── sqlite_cache.py         # Async SQLite cache manager (composite key, aiosqlite + WAL)
├── detection/                  # Shared YOLO11 bubble segmentation & layout sorting
│   ├── __init__.py
│   ├── base.py                 # DetectedBubble, DetectedText, BaseBubbleDetector
│   ├── yolo11_detector.py      # ONNX Runtime DirectML YOLO11s-seg detector
│   ├── postprocess.py          # Dual-head prototype mask decoding & RDP polygon compression
│   └── sorter.py               # 2-tier Japanese reading order geometric sorter
├── engines/
│   ├── __init__.py
│   ├── base.py                 # BaseTranslationEngine (Abstract Base Class)
│   ├── registry.py             # EngineRegistry factory and fallback orchestrator
│   ├── mock.py                 # MockTranslationEngine for testing and contract parity
│   ├── cloud/                  # Cloud Multimodal Engine (Set-of-Marks, ProviderRegistry)
│   └── local/                  # Local OCR & Translation Engine (TranslatorRegistry)
├── schemas/                    # (Module 1 Canonical Contracts)
│   ├── __init__.py
│   └── contract.py
└── security/
    ├── __init__.py
    └── middleware.py           # Header validation, payload caps, and security guards

tests/backend/
├── __init__.py
├── conftest.py                 # Async test fixtures, test database setup, mock engines
├── test_cache.py               # Unit tests for aiosqlite cache get/set/miss/isolation
├── test_engines.py             # Unit tests for EngineRegistry, BaseTranslationEngine, Mock
├── test_endpoints.py           # Integration tests for /translate, /cache/{hash}, /health
└── test_security.py            # Security tests: CORS, missing client header, 413 payload cap
```

---

## 4. Code Style & Architecture Snippets

### 4.1 Pluggable Engine Abstraction (`src/backend/engines/base.py`)
All engines must inherit from `BaseTranslationEngine` and satisfy strict mypy typing:

```python
import abc
from src.backend.detection.base import DetectedBubble
from src.backend.schemas.contract import TranslationRequest, TranslationResponse


class BaseTranslationEngine(abc.ABC):
    """Abstract base class for all translation engines (Cloud, Local, Mock)."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for this engine ('local', 'cloud', 'mock')."""
        pass

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """Check if engine prerequisites are satisfied (API keys configured, weights loaded)."""
        pass

    @abc.abstractmethod
    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
    ) -> TranslationResponse:
        """Execute text translation for the requested manga page using pre-detected bubbles."""
        pass
```

### 4.2 SQLite Cache Layer (`src/backend/cache/sqlite_cache.py`)
Uses `aiosqlite` with WAL mode and composite key isolation:

```python
import time
import aiosqlite
from src.backend.schemas.contract import TranslationResponse


class TranslationCache:
    """High-performance SQLite cache with WAL mode and composite engine key isolation."""

    def __init__(self, db_path: str = "./data/cache.db") -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        """Initialize database schema and set WAL pragmas."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_cache (
                    image_hash TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    engine_used TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (image_hash, target_lang, engine_used)
                );
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_composite ON translation_cache(image_hash, target_lang, engine_used);"
            )
            await db.commit()

    async def get(self, image_hash: str, target_lang: str, engine_used: str) -> TranslationResponse | None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT response_json FROM translation_cache WHERE image_hash = ? AND target_lang = ? AND engine_used = ?",
                (image_hash, target_lang, engine_used),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                data = TranslationResponse.model_validate_json(row[0])
                return data.model_copy(update={"from_cache": True})

    async def set(self, image_hash: str, target_lang: str, engine_used: str, response: TranslationResponse) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO translation_cache 
                (image_hash, target_lang, engine_used, response_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    image_hash,
                    target_lang,
                    engine_used,
                    response.model_dump_json(),
                    int(time.time()),
                ),
            )
            await db.commit()
```

### 4.3 Lifespan Management (`src/backend/app.py`)
Modern FastAPI `@asynccontextmanager` managing database pool and HTTP client lifecycle:

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
import httpx
from src.backend.cache.sqlite_cache import TranslationCache
from src.backend.engines.registry import EngineRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: Initialize DB, setup client session, register engines
    cache = TranslationCache()
    await cache.initialize()
    app.state.cache = cache
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    app.state.registry = EngineRegistry()

    yield

    # Shutdown: Cleanly close client connections
    await app.state.http_client.aclose()
```

---

## 5. Security & Boundary Controls

1. **Loopback Binding Guard:** Server launcher binds strictly to `127.0.0.1` (never `0.0.0.0`).
2. **CORS Origins Whitelist:** Only permits `chrome-extension://*`, `http://localhost:8000`, `http://127.0.0.1:8000`. Rejects wildcards (`*`).
3. **Client Header Verification:** Requests to `/api/v1/translate` must include `X-InkShift-Client: extension` or `X-InkShift-Client: reader`. Rejects drive-by browser scripts with HTTP 403.
4. **Payload Size Guard:** Middleware validates `Content-Length <= 20_000_000` bytes before parsing request body, returning `413 PAYLOAD_TOO_LARGE` if exceeded.
5. **No Stack Trace Leakage:** Exception handlers transform unexpected errors into `APIErrorResponse` with code `ENGINE_EXECUTION_FAILED`, keeping raw internal tracebacks out of API responses.

---

## 6. Testing Strategy

1. **Unit Testing (`pytest`):**
   - Cache unit tests: Verify store, retrieve, overwrite, missing keys, and WAL journal mode.
   - Registry unit tests: Verify engine registration, default selection, and unknown engine fallback.
   - Mock engine tests: Verify deterministic response generation and coordinate constraint adherence `[0, 1000]`.
2. **Integration Testing (`httpx.AsyncClient` + `app`):**
   - `POST /api/v1/translate`: Test full end-to-end request with cache hit vs cache miss.
   - `GET /api/v1/cache/{image_hash}`: Test cache hit returning 200 with `"from_cache": true`, and cache miss returning 404 with structured error.
   - `GET /api/v1/health`: Test status 200 with available engines map.
3. **Security Negative Testing:**
   - Test request lacking `X-InkShift-Client` header $\to$ Expect 403 Forbidden.
   - Test payload exceeding 20MB $\to$ Expect 413 Payload Too Large.
   - Test invalid hash parameter $\to$ Expect 422 Unprocessable Entity.
4. **Coverage Enforcement:**
   - Must achieve $\ge 80\%$ test coverage on newly added files per [CONSTRAINTS.md](../../CONSTRAINTS.md).

---

## 7. Boundaries

- **Always:** Use `async/await` with `aiosqlite` and `httpx`; validate request/response against `src/backend/schemas/contract.py`; return structured `APIErrorResponse`; bind strictly to `127.0.0.1`.
- **Ask First:** Introducing external database engines (PostgreSQL, Redis); changing the SQLite schema columns; modifying default port `8000`.
- **Never:** Suppress type errors with `# type: ignore` or `# noqa`; block the FastAPI event loop with synchronous sleeps or synchronous heavy compute; commit secrets or API keys.

---

## 8. Success Criteria

- [ ] **SC-1:** FastAPI server boots cleanly and `/api/v1/health` responds with HTTP 200 containing server status and engine availability.
- [ ] **SC-2:** `POST /api/v1/translate` successfully processes valid manga requests through `MockTranslationEngine`, returning valid blocks matching `TranslationResponse`.
- [ ] **SC-3:** Subsequent requests with the same `image_hash` return from the SQLite cache in $<5$ ms with `"from_cache": true`.
- [ ] **SC-4:** `GET /api/v1/cache/{image_hash}` returns HTTP 200 for cached pages and HTTP 404 with structured `CACHE_MISS` for uncached pages.
- [ ] **SC-5:** Requests lacking the `X-InkShift-Client` header or with payloads $>15$MB are rejected with HTTP 403 and HTTP 413 respectively.
- [ ] **SC-6:** Zero type errors under `mypy src/backend --strict`.
- [ ] **SC-7:** Zero lint violations under `ruff check src/backend`.
- [ ] **SC-8:** Backend test suite passes with $\ge 80\%$ test coverage.

---

## 9. Resolved Design Decisions

1. **Database Path Location:** Retained at repository local `./data/cache.db` (git-ignored, self-contained, easily inspectable). The initialization code must invoke `os.makedirs(os.path.dirname(self.db_path), exist_ok=True)` and support override via `INKSHIFT_DB_PATH`.
2. **Cache Eviction Policy:** Indefinite retention for MVP Week 2. Cache eviction policies (LRU / TTL) will be benchmarked and evaluated during Week 4 Hardening.

---

## 10. Addendum: Shared Block Assembly & Safe-Zone Text Fitting (`assembler.py`)

> **Approved by:** Solo Developer (@human)  
> **Date:** 2026-10-18  
> **Reference Decision:** [ADR-008 Addendum](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md#addendum-fine-grained-set-of-marks-grounding-for-multi-child-bubbles-option-a)

### 10.1 Shared Module Extraction
To eliminate duplicated code and guarantee exact parity between `local` and `cloud` engines, block assembly and safe-zone polygon expansion are centralized in `src/backend/detection/assembler.py`:
- `prepare_local_work_items(bubbles: list[DetectedBubble]) -> list[BubbleWorkItem]`:
  Calculates `render_box` safe-zones within curved speech balloon polygons via `expand_child_text_boxes_in_polygon`. Distinguishes single bubbles, complex polygons, and multi-child bubbles.
- `assemble_translated_blocks(...) -> list[TranslatedBlock]`:
  Symmetrically converts translations from both engines into uniform `TranslatedBlock` models.
  - **Local Format:** Ordered list of translated strings matching `BubbleWorkItem`s.
  - **Cloud Format:** Dictionary mapping sequential badge indices (`"1"`, `"2"`, ...) to translated strings.
  - **Parent-Child Linking:** Multi-child bubbles automatically populate `parent_bubble_id=bubble.id`, `parent_box=bubble.box_2d`, and `polygon=bubble.polygon`, allowing client overlays to group them under one parent contour mask.

