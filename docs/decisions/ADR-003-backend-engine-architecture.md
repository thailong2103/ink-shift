# ADR-003: Backend Engine Runtime, Pluggable Architecture, and SQLite Caching

- **Status:** Accepted
- **Date:** 2026-10-10
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent
- **Target Module:** `backend-engine` (Module 2 Execution Runtime)
- **Amended By:** [ADR-008](ADR-008-consolidated-engine-architecture-and-shared-detection.md) (Consolidated engine registration to 2 engines + mock, gateway detection, and SQLite composite cache keys)

---

## 1. Context & Problem Statement

InkShift requires a high-performance local web server (`backend-engine`) running at `127.0.0.1:8000` to serve translation requests from the Chromium Extension and the Zen Reader.

Module 1 (`api-contract`) established the canonical data schemas (`TranslationRequest`, `TranslationResponse`, `TranslatedBlock`). Now, the backend runtime must execute this contract while addressing:
1. **Caching & Persistence:** High-speed lookup of prior page translations using SHA-256 `image_hash` keys with sub-5ms latency and concurrent read safety.
2. **Pluggable Engine Abstraction:** Clean isolation between the web API layer and heterogeneous translation engines (`cloud-engine` via Gemini/OpenAI Vision vs `local-engine` via Manga-OCR/YOLO vs `mock-engine` for testing).
3. **Concurrency & Thread Safety:** Preventing CPU-bound local ML models or I/O-bound cloud network calls from stalling the FastAPI event loop.
4. **Localhost Boundary Security:** Preventing malicious web pages from executing unauthorized drive-by requests against the local HTTP server.

---

## 2. Options Considered

### A. Caching & Persistence Layer
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1A: `aiosqlite` + WAL Mode (Selected)** | - Async native context managers.<br>- Zero heavy C-extension compilation issues on Windows.<br>- WAL (Write-Ahead Logging) enables non-blocking concurrent reads.<br>- Minimal footprint for a single key-document cache table. | - Manual SQL table creation (straightforward and lightweight). | **Selected (Agent & Human Approved)** |
| **Option 1B: SQLModel / Async SQLAlchemy** | - Type-safe ORM models.<br>- Alembic migration tooling. | - Over-engineered for a single cache table.<br>- Incurs overhead and increases startup footprint. | Not recommended |
| **Option 1C: JSON File / TinyDB** | - No SQL needed. | - Susceptible to file lock race conditions.<br>- Severe lookup degradation as cache grows. | Not recommended |

---

### B. Translation Engine Architecture (Pluggable Abstraction)
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 2A: `abc.ABC` + Registry Factory Pattern (Selected)** | - Enforces strict interface compliance via Python `abc`.<br>- Static analysis (`mypy --strict`) catches missing methods at build time.<br>- Decouples route handlers from engine implementation details.<br>- Trivial to mock in unit and integration tests. | - Engines must register themselves with the central registry. | **Selected (Agent & Human Approved)** |
| **Option 2B: `typing.Protocol` (Duck Typing)** | - No explicit inheritance needed. | - Runtime verification is looser.<br>- Lifecycle hooks (init, warmup, teardown) are easy to miss. | Not recommended |
| **Option 2C: Dynamic Plugin Discovery (`importlib`)** | - Drops files in a folder to auto-load. | - Fragile path resolution across environments.<br>- Hard to debug hidden import errors. | Not recommended |

---

### C. HTTP Client Library
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 3A: `httpx` (Selected)** | - Standard async HTTP client (`httpx.AsyncClient`).<br>- Connection pooling and granular timeout handling.<br>- Seamless integration with FastAPI `lifespan` and test runners. | - Must manage client session lifecycle. | **Selected (Agent & Human Approved)** |
| **Option 3B: `requests` + ThreadPool** | - Familiar API. | - Synchronous blocking; requires thread offloading for every call. | Not recommended |
| **Option 3C: `aiohttp`** | - High performance. | - More verbose API; different semantics from standard requests. | Not recommended |

---

### D. Concurrency Model (Event Loop vs Workers)
- **Cloud Engines (I/O-bound):** Pure async execution using `httpx.AsyncClient`.
- **Local Engines (CPU/GPU-bound):** Execution offloaded to `asyncio.to_thread` or a managed worker pool so heavy tensor operations never block the FastAPI main event loop.

---

## 3. Decision & Rationale

We adopted **Options 1A (`aiosqlite` + WAL), 2A (`abc.ABC` + Registry), 3A (`httpx`), and the Hybrid Concurrency Model**:

1. **Database:** SQLite managed via `aiosqlite`. Cache table `translation_cache` indexed by `(image_hash, target_lang)`. SQLite pragmas set to `journal_mode=WAL` and `synchronous=NORMAL` during startup.
2. **Engine Abstraction:** Define `BaseTranslationEngine(abc.ABC)` requiring:
   - `name: str`
   - `is_available() -> bool`
   - `async translate(request: TranslationRequest) -> TranslationResponse`
   An `EngineRegistry` maintains available engines, default selection, and fallback chains.
3. **HTTP Client:** Centralized `httpx.AsyncClient` managed within FastAPI's `lifespan` context.
4. **Security Controls:**
   - Server binds exclusively to `127.0.0.1:8000`.
   - CORS middleware permits origins `chrome-extension://*`, `http://localhost:8000`, `http://127.0.0.1:8000`.
   - Header inspection rejects requests lacking the `X-InkShift-Client` header.
   - Max body size capped at 15MB base64 (~10MB binary) to prevent memory exhaustion bombs.

---

## 4. Consequences

- **Positive Impact:**
  - FastAPI runtime starts in $<500$ ms with near-zero idle RAM footprint.
  - Page cache hits respond in $<5$ ms directly from local SQLite.
  - New translation providers (Gemini, OpenAI, Manga-OCR, mock) can be added simply by subclassing `BaseTranslationEngine` without changing any API endpoint logic.
  - Clean boundary isolation satisfying all rules in `CONSTRAINTS.md`.
- **Trade-offs / Negatives:**
  - `aiosqlite` requires manual SQL schema migrations if the cache schema changes (mitigated by storing data as a canonical JSON string that adheres to `TranslationResponse`).
  - Offloading local models to threads adds minor serialization overhead (completely negligible compared to OCR runtime).
- **Follow-up Tasks:**
  - Author specification [docs/specs/SPEC-backend-engine.md](../specs/SPEC-backend-engine.md).
  - Create execution plan in `tasks/plan.md` and checklist in `tasks/todo.md`.
  - Implement cache layer, engine registry, mock engine, and FastAPI router.
