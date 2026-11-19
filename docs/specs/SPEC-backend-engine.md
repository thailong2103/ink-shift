# Spec: Backend Runtime, Pluggable Engine Coordinator, and Cache (`backend-engine`)

> **Module ID:** `backend-engine`  
> **Source ADR:** [ADR-003-backend-engine-architecture.md](../decisions/ADR-003-backend-engine-architecture.md), [ADR-008-consolidated-engine-architecture-and-shared-detection.md](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md), [ADR-019-ppocrv6-unified-hybrid-detection-and-auto-ocr.md](../decisions/ADR-019-ppocrv6-unified-hybrid-detection-and-auto-ocr.md), [ADR-020-resilient-cache-site-adapters-priority-queue-and-llm-repair.md](../decisions/ADR-020-resilient-cache-site-adapters-priority-queue-and-llm-repair.md)  
> **Parent Map:** [CAPABILITY_MAP.md](CAPABILITY_MAP.md)  
> **Contract Spec:** [SPEC-api-contract.md](SPEC-api-contract.md)  
> **Status:** Implemented (Synced through Phase 47) — Approved by Solo Developer (@human)  
> **Phase:** Module 2 Execution Runtime & Phases 15–47 Hardening  
> **Language Policy:** Official English document tracked in Git. Parallel Vietnamese copy at [docs/vi/specs/SPEC-backend-engine.md](../vi/specs/SPEC-backend-engine.md).

---

## 1. Objective

Provide a robust, high-performance, and secure local backend runtime (`backend-engine`) running on `127.0.0.1:8000`. The server acts as the central coordinator between client interfaces (Chromium Extension and Zen Web Reader) and pluggable translation engines (`cloud`, `local`, and `mock`).

### Core Capabilities:
1. **API Contract Enforcement:** Host FastAPI endpoints (`POST /api/v1/translate`, `GET /api/v1/cache/{image_hash}`, `DELETE /api/v1/cache`, `GET /api/v1/health`, `/api/v1/models/*`, `/api/v1/settings/*`, `/api/v1/context/*`, `/api/v1/telemetry/*`) strictly adhering to Pydantic schemas defined in Module 1 (`api-contract`).
2. **Shared Gateway Detection (Option G1) & Unified Layout:** Execute the shared YOLO11 detector once at the API gateway layer (`translate.py`) for un-cached requests (`detect_full_layout()` returning `PageLayoutDetections` for `local`, `detect()` for `cloud`), passing pre-sorted bubbles and layout regions into `engine.translate()`.
3. **High-Speed 5-Column SQLite Caching & Zero-Poisoning:** Store and retrieve page-level translations indexed by `(image_hash, target_lang, engine_used, translator_used, prompt_hash)` composite key using `aiosqlite` in WAL mode with idempotent schema migration, `DELETE /api/v1/cache` invalidation, and strict `is_fallback` bypass.
4. **Priority Inference Lock & Singleflight Cancellation:** Gate local ONNX/LLM execution via `PriorityLocalLock` (`P0` LIFO preemption over `P1`/`P2` FIFO) with `request.is_disconnected()` HTTP 499 skipping and singleflight deduplication.
5. **Consolidated Engine Abstraction:** Provide an extensible `BaseTranslationEngine` interface and `EngineRegistry` factory hosting 3 canonical engines (`"local"`, `"cloud"`, `"mock"`) with dynamic sub-delegation via `ProviderRegistry` and `TranslatorRegistry`.
6. **Localhost Boundary Defense:** Enforce loopback binding (`127.0.0.1`), CORS origin whitelisting, custom client header verification (`X-InkShift-Client`), and payload size caps.

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
├── app.py                      # FastAPI application factory, lifespan, PriorityLocalLock, CORS
├── config.py                   # Environment settings (.env loader, ports, model paths, timeouts)
├── logging.py                  # Structured dual-handler Logfmt logger & stage timer
├── api/
│   ├── __init__.py
│   └── v1/
│       ├── __init__.py
│       ├── router.py           # v1 APIRouter aggregating all 7 sub-routers
│       ├── translate.py        # POST /api/v1/translate (Option G1, PriorityLocalLock, 499 skip)
│       ├── cache.py            # GET /api/v1/cache/{image_hash} & DELETE /api/v1/cache
│       ├── health.py           # GET /api/v1/health status endpoint
│       ├── models.py           # POST /api/v1/models/discover live provider proxy
│       ├── settings.py         # GET/POST /api/v1/settings/providers (.env atomic persistence)
│       ├── context.py          # /api/v1/context/* (report, progress, chapter pages)
│       └── telemetry.py        # POST /api/v1/telemetry/logs extension log ingestion
├── cache/
│   ├── __init__.py
│   └── sqlite_cache.py         # 5-column composite key aiosqlite WAL cache + delete/clear/migration
├── context/                    # Relational SQLite Manga Context Graph store
│   ├── __init__.py
│   ├── models.py               # series/chapters/chapter_pages DDL & helpers
│   ├── schemas.py              # Context Pydantic contracts
│   └── store.py                # Async ContextStore CRUD
├── detection/                  # Shared YOLO11 bubble/layout segmentation & assembly
│   ├── __init__.py
│   ├── assembler.py            # BubbleWorkItem & safe-zone polygon box expansion
│   ├── base.py                 # DetectedBubble, DetectedPanel, DetectedText, PageLayoutDetections
│   ├── downloader.py           # Automated Hugging Face / ModelScope weights provisioning
│   ├── postprocess.py          # Prototype mask decoding, Chaikin smoothing, RDP compression, orphan partition
│   ├── sorter.py               # 2-tier Japanese reading order geometric sorter
│   └── yolo11_detector.py      # ONNX Runtime DirectML YOLO11s-seg detector (lazy session)
├── engines/
│   ├── __init__.py
│   ├── base.py                 # BaseTranslationEngine (Abstract Base Class)
│   ├── registry.py             # EngineRegistry factory and orchestrator
│   ├── mock.py                 # MockTranslationEngine for testing and contract parity
│   ├── cloud/                  # Cloud Multimodal Engine (Set-of-Marks, ProviderRegistry)
│   └── local/                  # Local OCR & Translation Engine (PP-OCRv6_medium, TranslatorRegistry)
├── schemas/
│   ├── __init__.py
│   ├── contract.py             # TranslationRequest, TranslationResponse, TranslatedBlock, APIError*
│   └── models.py               # Discovery & provider settings schemas
└── security/
    ├── __init__.py
    ├── env_manager.py          # Atomic .env update & API key masking
    └── middleware.py           # Header validation, payload caps, magic-byte validation, security headers

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
All engines inherit from `BaseTranslationEngine` and satisfy strict mypy typing (with `LocalTranslationEngine.translate()` additionally accepting optional `layout: PageLayoutDetections | None = None` passed selectively by `translate.py` via `inspect.signature`):

```python
import abc
from src.backend.detection.base import DetectedBubble
from src.backend.schemas.contract import TranslationRequest, TranslationResponse


class BaseTranslationEngine(abc.ABC):
    """Abstract interface for all translation providers (Cloud, Local, Mock)."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier of the translation engine."""

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """Check whether engine dependencies and credentials are ready."""

    @abc.abstractmethod
    async def translate(
        self,
        request: TranslationRequest,
        bubbles: list[DetectedBubble] | None = None,
    ) -> TranslationResponse:
        """Process manga page image and return structured translated blocks."""
```

### 4.2 5-Column SQLite Cache Layer (`src/backend/cache/sqlite_cache.py`)
Uses `aiosqlite` with WAL mode, idempotent `PRAGMA table_info` schema migration, 5-column composite key isolation, and `delete()`/`clear()` invalidation:

```python
def compute_prompt_hash(custom_prompt: str | None) -> str:
    if not custom_prompt or not custom_prompt.strip():
        return ""
    return hashlib.sha256(custom_prompt.strip().encode("utf-8")).hexdigest()[:16]


class TranslationCache:
    """Async SQLite cache storing and retrieving translation responses with engine isolation."""

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_cache (
                    image_hash TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    engine_used TEXT NOT NULL,
                    translator_used TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL DEFAULT '',
                    response_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (image_hash, target_lang, engine_used, translator_used, prompt_hash)
                );
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cache_hash_lang_engine_trans_prompt
                ON translation_cache(image_hash, target_lang, engine_used, translator_used, prompt_hash);
                """
            )
            await db.commit()
```

Note: `POST /api/v1/translate` bypasses `cache.set()` whenever `response.is_fallback` is `True`.

### 4.3 Lifespan Management (`src/backend/app.py`)
FastAPI `@asynccontextmanager` initializes SQLite `TranslationCache` & `ContextStore`, `PriorityLocalLock` (`app.state.local_semaphore`), shared `httpx.AsyncClient`, shared lazy `YOLO11Detector`, `EngineRegistry`, `ProviderRegistry`, and `TranslatorRegistry`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    cache = getattr(app.state, "cache", None) or TranslationCache(db_path=settings.inkshift_db_path)
    await cache.initialize()
    app.state.cache = cache

    context_store = getattr(app.state, "context_store", None) or ContextStore(db_path=settings.inkshift_db_path)
    await context_store.initialize()
    app.state.context_store = context_store

    app.state.local_semaphore = getattr(app.state, "local_semaphore", None) or PriorityLocalLock()
    app.state.in_flight_tasks = getattr(app.state, "in_flight_tasks", None) or {}
    yield
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

- [x] **SC-1:** FastAPI server boots cleanly and `/api/v1/health` responds with HTTP 200 containing server status and engine availability.
- [x] **SC-2:** `POST /api/v1/translate` successfully processes valid manga requests through `MockTranslationEngine`, returning valid blocks matching `TranslationResponse`.
- [x] **SC-3:** Subsequent requests with the same `image_hash` return from the SQLite cache in $<5$ ms with `"from_cache": true`.
- [x] **SC-4:** `GET /api/v1/cache/{image_hash}` returns HTTP 200 for cached pages and HTTP 404 with structured `CACHE_MISS` for uncached pages.
- [x] **SC-5:** Requests lacking the `X-InkShift-Client` header or with payloads $>15$MB are rejected with HTTP 403 and HTTP 413 respectively.
- [x] **SC-6:** Zero type errors under `mypy src/backend --strict`.
- [x] **SC-7:** Zero lint violations under `ruff check src/backend`.
- [x] **SC-8:** Backend test suite passes with $\ge 80\%$ test coverage (365/365 backend tests).

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

