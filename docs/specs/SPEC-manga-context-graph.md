# Spec: Manga Context Graph & In-Memory Prefetch Pipeline (F2 + F3 MVP)

> **Module ID:** `manga-context-graph`  
> **Status:** Approved by Solo Developer (@human) on 2026-10-22  
> **Date:** 2026-10-22  
> **Source ADR:** [ADR-010-manga-context-graph-and-sliding-window-prefetch.md](../decisions/ADR-010-manga-context-graph-and-sliding-window-prefetch.md)  
> **Research Reports:** [RESEARCH-mangadex-api-and-prefetch.md](../research/RESEARCH-mangadex-api-and-prefetch.md), [RESEARCH-manga-context-graph.md](../research/RESEARCH-manga-context-graph.md)  
> **Quality Gate:** [CONSTRAINTS.md](../../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)

---

## 1. Objective & Scope

### 1.1 Problem Statement
In existing releases (Phases 1–21), InkShift scans images only when they appear in the DOM. On single-page SPA readers (MangaDex), only 1–2 images are mounted at once, making background prefetching blind to the rest of the chapter. Readers experience a 1.5–3.5s latency pause on every page flip. Furthermore, rapidly flipping back and forth triggers duplicate AI requests, wasting GPU/API resources.

### 1.2 Target Vision & Scope (F2 + F3 MVP)
This module establishes a **Manga Context Graph (F2)** and an **In-Memory Sliding Window Prefetch Scheduler (F3)**:
- **Zero-Wait Reading:** When a user turns the page, the translation overlay is rendered in $0\text{ms}$ directly from local cache.
- **MangaDex-First Integration:** The extension background service worker queries the MangaDex@Home API directly to harvest full 30–50 page manifests in $<100\text{ms}$.
- **Zero Disk Image Bloat:** Prefetched images exist only in volatile RAM buffers during SHA-256 hashing and inference. Zero raw image bytes are stored on disk.
- **Client & Backend Singleflight:** Deduplicate in-flight requests across both extension and backend, preventing duplicate inferences during rapid page flipping.
- **Hardware-Conscious Concurrency:** Sequential execution (`asyncio.Semaphore(1)`) for local deep learning models (YOLO11, MangaOCR) to avoid VRAM OOM, while leaving cloud API calls uncapped per developer direction.
- **Scope Boundary:** F4 (Zen Reader UI) is postponed to a subsequent phase.

---

## 2. Tech Stack & Dependencies

| Layer | Technology | Version / Configuration | Role |
|---|---|---|---|
| **Database** | SQLite via `aiosqlite` | WAL Mode, Foreign Keys ON | Lightweight relational Context Graph (`manga_series`, `manga_chapters`, `chapter_pages`) |
| **Backend Schemas** | Pydantic v2 | Strict mode, typed validation | Context report and progress update payloads |
| **Backend API** | FastAPI Router | `/api/v1/context/*` | Asynchronous CRUD endpoints for reading context |
| **Concurrency Guard** | `asyncio.Semaphore` & `asyncio.Lock` | `Semaphore(1)` for Local Engine | Hardware protection for DirectML GPU execution |
| **Extension Networking** | Chromium Service Worker `fetch()` | `host_permissions: ["<all_urls>"]` | Privileged MangaDex@Home API and image fetching |
| **Content Script** | Vanilla TypeScript + Web APIs | `IntersectionObserver`, `pushState` hooks | Zero-overhead reading position tracking |

---

## 3. Full Executable Commands

```bash
# 1. Type Checks (Fast Gate)
npm run typecheck --prefix src/extension    # Zero TS errors
python -m mypy src/                        # Zero Mypy errors (--strict)

# 2. Linting & Floor Guard
python -m ruff check src/ tests/           # Zero lint warnings
python scripts/check.py --fast             # Zero Floor Guard suppressions

# 3. Unit & Integration Testing
npm run test:extension                     # Vitest extension test suite
pytest tests/backend/test_context_*.py -v  # Backend Context Graph tests
pytest tests/ -v                           # Full backend test regression
```

---

## 4. Project Structure

```text
src/
├── backend/
│   ├── context/                          # [NEW] Manga Context Graph Module
│   │   ├── __init__.py
│   │   ├── models.py                     # SQLite table DDL & raw query helpers
│   │   ├── store.py                      # Async aiosqlite ContextStore (CRUD & status)
│   │   └── schemas.py                    # Pydantic v2 request/response schemas
│   ├── api/v1/
│   │   └── context.py                    # [NEW] FastAPI router endpoints (/api/v1/context/*)
│   └── app.py                            # Lifespan initialization of ContextStore
└── extension/
    ├── background/
    │   ├── adapters/
    │   │   └── mangadex_adapter.ts       # [NEW] MangaDex@Home API client & quality detector
    │   └── service_worker.ts             # Singleflight deduplication map & IPC routing
    ├── content/
    │   ├── page_manifest_extractor.ts    # [NEW] Hybrid manifest engine (MangaDex + DOM waterfall)
    │   ├── reading_progress_tracker.ts   # [NEW] Observer & SPA progress sync (debounce 2s)
    │   └── prefetch_scheduler.ts         # [NEW] Sliding window lookahead queue (P0/P1/P2)
    └── popup/
        ├── popup.html                    # Prefetch Master Toggle + Depth selector (3, 5, 10, all)
        └── popup.ts                      # Storage persistence for prefetch preferences
```

---

## 5. Code Style & Architectural Patterns

### 5.1 SQLite Schema (3 Normalized Tables)
```sql
CREATE TABLE IF NOT EXISTS manga_series (
    series_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    source_domain   TEXT NOT NULL,
    cover_url       TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS manga_chapters (
    chapter_id       TEXT PRIMARY KEY,
    series_id        TEXT NOT NULL REFERENCES manga_series(series_id) ON DELETE CASCADE,
    chapter_ordinal  REAL NOT NULL,
    chapter_label    TEXT NOT NULL,
    chapter_url      TEXT NOT NULL,
    total_pages      INTEGER DEFAULT 0,
    last_read_page   INTEGER DEFAULT 1,
    status           TEXT DEFAULT 'reading',
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chapter_pages (
    page_id          TEXT PRIMARY KEY,
    chapter_id       TEXT NOT NULL REFERENCES manga_chapters(chapter_id) ON DELETE CASCADE,
    page_number      INTEGER NOT NULL,
    image_url        TEXT NOT NULL,
    image_hash       TEXT,
    status           TEXT DEFAULT 'discovered', -- discovered | queued | processing | ready | failed
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    CONSTRAINT uq_chapter_page UNIQUE (chapter_id, page_number)
);
```

### 5.2 Client Singleflight Pattern (`service_worker.ts`)
```typescript
const inFlightRequests = new Map<string, Promise<TranslationResponse>>();

export async function requestTranslationWithDedupe(
  imageHash: string,
  payload: TranslateImagePayload,
  gateway: BackendGateway
): Promise<TranslationResponse> {
  const existing = inFlightRequests.get(imageHash);
  if (existing) {
    return await existing;
  }

  const promise = gateway.requestTranslation(payload).finally(() => {
    inFlightRequests.delete(imageHash);
  });

  inFlightRequests.set(imageHash, promise);
  return await promise;
}
```

### 5.3 Backend Hardware Concurrency Guard (`app.py`)
```python
# Concurrency limiters attached to app state
app.state.local_semaphore = asyncio.Semaphore(1)  # Strictly sequential for GPU/VRAM protection
# Cloud API calls remain uncapped per developer directive
```

---

## 6. Testing Strategy

1. **Backend Context Store (`tests/backend/test_context_store.py`):**
   - Verify asynchronous table creation, Foreign Key constraints, and `ON DELETE CASCADE`.
   - Verify idempotent chapter registration and page upsert.
   - Verify progress updates (`last_read_page`) without race conditions.
2. **Backend Concurrency & Locks (`tests/backend/test_concurrency_locks.py`):**
   - Test simultaneous requests with identical `image_hash` yield single execution and shared responses.
   - Test `local_semaphore(1)` blocks concurrent local execution.
3. **MangaDex Adapter (`tests/extension/test_mangadex_adapter.test.ts`):**
   - Mock MangaDex `/at-home/server/{id}` payload with original and data-saver formats.
   - Verify URL construction and automatic quality parity selection.
   - Verify auto-retry on HTTP 403 Forbidden.
4. **Prefetch Scheduler (`tests/extension/test_prefetch_scheduler.test.ts`):**
   - Verify Priority Queue ordering: P0 preempts P1 and P2.
   - Verify sliding window bounds (depth = 3, 5, 10, all).
   - Verify `AbortController` cancellation upon chapter change.

---

## 7. Boundaries

- **Always:**
  - Free image buffers from memory (`blob = null`) immediately after sending to backend.
  - Run local engine models under `Semaphore(1)` sequential execution.
  - Check `translation_cache` before queuing background prefetch.
- **Ask First:**
  - Changing SQLite database filename or schema columns.
  - Modifying the public `/api/v1/translate` contract interface.
- **Never:**
  - Store raw image binary files on the user's hard drive or SQLite DB.
  - Swallow HTTP 403 errors on MangaDex without attempting token refresh.
  - Relax constraints in `CONSTRAINTS.md` or add `@ts-ignore` / `# type: ignore`.

---

## 8. Success Criteria (Testable Verification Gates)

- [ ] **SC-1 (MangaDex Manifest Extraction):** On any MangaDex chapter URL (`/chapter/{uuid}/1`), the extension retrieves 100% of the chapter's page URLs via the background service worker in $<150\text{ms}$.
- [ ] **SC-2 (Zero-Wait Page Flip):** When reading with prefetch enabled (depth $\ge 2$), flipping to Page $N+1$ results in a Cache HIT with overlay render latency $\le 16\text{ms}$ (0ms AI wait).
- [ ] **SC-3 (Zero Raw Image Disk Storage):** Inspection of `./data/` and local extension storage confirms $0\text{MB}$ of raw image files saved to disk during or after prefetching.
- [ ] **SC-4 (In-Flight Request Stampede Elimination):** Rapidly flipping between Page 1 and Page 2 five times in 2 seconds triggers exactly 1 translation task per page on the backend.
- [ ] **SC-5 (Local Hardware Stability):** Under continuous reading with Local Engine, VRAM usage remains flat ($\le 2048\text{MB}$) without DirectML crashes or memory leaks.
- [ ] **SC-6 (Quality Gate 100% Green):** All new TypeScript and Python test suites pass with 0 lint errors, 0 type errors, and 0 Floor Guard violations.

---

## 9. Open Questions & Approvals

All design questions have been resolved and approved by the solo developer (@human) in [ADR-010](../decisions/ADR-010-manga-context-graph-and-sliding-window-prefetch.md).

→ **Human Developer Approval Gate:** Please review this specification and confirm approval before task planning begins.
