# ADR-010: Manga Context Graph, MangaDex@Home Integration, and In-Memory Sliding Window Prefetch

- **Status:** Accepted
- **Date:** 2026-10-22
- **Decision-Maker:** Solo Developer (@human)
- **Consulted:** Antigravity AI Agent
- **Related Spec:** [SPEC-manga-context-graph.md](../specs/SPEC-manga-context-graph.md)
- **Research Sources:** [RESEARCH-mangadex-api-and-prefetch.md](../research/RESEARCH-mangadex-api-and-prefetch.md), [RESEARCH-manga-context-graph.md](../research/RESEARCH-manga-context-graph.md)

---

## 1. Context & Problem Statement

In previous phases (Phases 1–21), InkShift operated strictly on individual images mounted in the DOM. This flat model produced three critical user-experience bottlenecks:
1. **Single-Page SPA Blindness (MangaDex):** Modern single-page readers only mount 1–2 `<img>` tags in the DOM at any given time. Traditional DOM scanning misses 95% of chapter pages, making background prefetching impossible.
2. **Page-Flip Latency Stutter:** On every page flip, readers must wait 1.5 to 3.5 seconds (fetch image $\to$ compute hash $\to$ YOLO detection $\to$ OCR/Cloud Vision $\to$ translate $\to$ render overlay), disrupting reading immersion.
3. **In-Flight Request Stampede (Thundering Herd):** Rapidly flipping back and forth between pages dispatches duplicate concurrent requests for the exact same image hash, wasting local GPU compute and cloud API quota while racing on SQLite writes.
4. **Local Hardware Contention vs. Uncapped Cloud:** Running multiple local deep learning models (YOLO11s-seg, MangaOCR) concurrently causes compute saturation and risks Out-Of-Memory (VRAM OOM) crashes on consumer hardware.

We require a structured Context Graph (F2) and an In-Memory Sliding Window Prefetch Scheduler (F3) to achieve zero-wait page flips without storing raw images on disk or crashing local GPU sessions.

---

## 2. Options Considered

### A. Manifest Extraction Pathways (MangaDex)

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: DOM Scraping + Pagination Clicking** | - No external API needed. | - Extremely brittle.<br>- Requires emulating user clicks.<br>- Cannot discover URLs until pages are viewed. | Rejected |
| **Option 2: Network Sniffing (`webRequest`)** | - Captures client requests passively. | - Requires high-risk permissions (`debugger` / `webRequestBlocking`).<br>- Misses cached pages. | Rejected |
| **Option 3: Direct Background Service Worker API** | - Accesses official MangaDex v5 REST API (`/at-home/server/{id}`).<br>- Bypasses CORS via MV3 `host_permissions: ["<all_urls>"]`.<br>- Fast ($<100\text{ms}$) and resilient to web UI redesigns. | - Requires managing 15-minute `baseUrl` token lifecycle. | **Accepted (Recommended)** |

### B. Raw Image Prefetch Storage Strategy

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: Save All 50 Raw Images to Disk** | - Offline access to full chapter. | - Consumes 50–100MB per chapter (5–10GB for 100 chapters).<br>- Copyright concerns with local image scraping. | Rejected |
| **Option 2: In-Memory Ephemeral Buffer (0MB on Disk)** | - **Zero disk bloat**.<br>- Pure in-memory processing (`Blob` $\to$ SHA-256 $\to$ inference $\to$ GC).<br>- Only lightweight translation JSON stored in SQLite ($<150\text{KB}$/chap). | - Requires auto-refreshing node `baseUrl` on HTTP 403 if reading session exceeds 15 minutes. | **Accepted (Recommended)** |

---

## 3. Decision & Rationale

The solo developer (@human) has decided to implement **F2 (Manga Context Graph) and F3 (In-Memory Prefetch Pipeline)** with the following architectural choices:

1. **Scope & Prioritization (MVP):**
   - Focus exclusively on F2 + F3. Postpone F4 (Zen Reader UI) to a later phase.
   - Optimize MangaDex-First alongside standard vertical scroll/Madara readers.
2. **MangaDex@Home Direct Integration:**
   - Chrome MV3 Service Worker queries `GET https://api.mangadex.org/at-home/server/{chapterId}` to harvest the chapter manifest in $<100\text{ms}$.
   - Reference expansion `GET /chapter/{id}?includes[]=manga` enriches series metadata in a single round-trip.
   - Quality matching: Automatically detect whether on-screen DOM uses `/data-saver/` or `/data/` to match SHA-256 hashes identically.
   - Auto-refresh on 403: When a node token expires after 15 minutes, re-query `/at-home/server/{id}` seamlessly in the background.
3. **In-Memory Ephemeral Image Processing:**
   - Image bytes exist solely in volatile RAM buffers during SHA-256 hashing and inference. Zero raw image bytes are saved to disk.
4. **Client-Side Singleflight Deduplication:**
   - Implement `inFlightRequests = Map<string, Promise<TranslationResponse>>` in `service_worker.ts` and an in-flight hash lock in FastAPI to ensure that rapid back-and-forth page navigation generates **exactly one** translation task per unique image hash.
5. **Priority Queue & Concurrency Controls:**
   - **P0 (On-Screen):** Active visible page has absolute preemption.
   - **P1 (Next Page):** Page $N+1$ prefetch begins immediately when P0 concludes.
   - **P2 (Lookahead):** Pages $N+2, N+3...$ based on user-configured depth.
   - **Local Engine (DirectML):** Enforce `asyncio.Semaphore(1)` to run sequential execution. Exploits the gap between human reading time ($10\text{s}$) and model inference ($1.5\text{s}$) to keep VRAM stable and GPU cool.
   - **Cloud Engine (API):** **Uncapped Concurrency** per developer instruction, maximizing parallel cloud throughput without artificial throttles.
6. **User Customization (Popup UI):**
   - Master Toggle: Enable / Disable Prefetching.
   - Prefetch Depth Selector: `3`, `5`, `10`, or `all` (entire chapter).
   - Unrestricted Cloud Policy: Prefetch runs across both Local and Cloud engines based on user toggle.
7. **Context Graph Persistence:**
   - Normalized 3-table SQLite schema (`manga_series`, `manga_chapters`, `chapter_pages`) stored indefinitely (`Option A`) with `status` tracking (`discovered`, `queued`, `processing`, `ready`, `failed`). Cleared via `ON DELETE CASCADE`.

---

## 4. Consequences

### Positive Impact
- **Zero-Wait Reading Experience:** Readers encounter immediate translation rendering ($0\text{ms}$ delay) upon turning pages on MangaDex and vertical CMS sites.
- **VRAM Stability & Zero Crash:** Sequential local execution prevents DirectML driver crashes and memory thrashing on consumer GPUs.
- **Network & Token Efficiency:** Singleflight pattern prevents duplicate calls to Gemini/OpenAI during rapid skimming or page flipping.
- **Zero Disk Bloat:** Entire series can be read without accumulating gigabytes of ephemeral image caches.

### Trade-offs / Accepted Complexity
- Requires maintaining the MangaDex At-Home node token refresh lifecycle on HTTP 403.
- Requires Service Worker background orchestration between content scripts, At-Home CDN, and FastAPI backend.

### Follow-up Tasks
- Author and approve [SPEC-manga-context-graph.md](../specs/SPEC-manga-context-graph.md).
- Update [CAPABILITY_MAP.md](../specs/CAPABILITY_MAP.md) and [PROJECT_STATE.md](../PROJECT_STATE.md).
- Break down Phase 22 TDD tasks in `tasks/plan.md` and `tasks/todo.md`.
