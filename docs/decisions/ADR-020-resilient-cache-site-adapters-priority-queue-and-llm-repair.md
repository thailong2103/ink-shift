# ADR-020: Resilient Cache Isolation, Modular Site Adapters, Priority Inference Queue, and Local LLM Repair (Phases 35–45)

- **Status:** Accepted (Retroactive Architecture Consolidation — Phases 35–45)
- **Date:** 2026-11-19
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent
- **Target Modules:** `api-contract`, `backend-engine`, `cloud-engine`, `local-engine`, `extension-core`, `manga-context-graph`
- **Amends:** [ADR-003](ADR-003-backend-engine-architecture.md), [ADR-004](ADR-004-cloud-engine-architecture.md), [ADR-005](ADR-005-extension-core-architecture.md), [ADR-010](ADR-010-manga-context-graph-and-sliding-window-prefetch.md), [ADR-012](ADR-012-dynamic-llm-provider-hub.md)

---

## 1. Context & Problem Statement

Between Phases 35 and 45, field testing on MangaDex (SPA carousel, `blob:` image URLs), Hitomi.la (anti-hotlink referer blocking, Anycast AVIF/WebP sharding), and local LLM inference (LM Studio / Ollama / Qwen / Gemma) exposed four cross-cutting architectural gaps not covered by earlier ADRs:

1. **SQLite Cache Poisoning & Key Collisions:** Failed `google-free` or local LLM calls returned original source text that was persisted into SQLite under a 3-column primary key `(image_hash, target_lang, engine_used)`. Switching translators (`google-free` vs `llm-custom`) or changing custom prompts returned stale/untranslated cached entries, and users lacked separate controls for clearing browser RAM cache vs persistent SQLite rows.
2. **Hardcoded Site Coupling & Anti-Hotlink Failures:** MangaDex UUID parsing, CDN fallback rules, and `blob:` workarounds were scattered inside `cors_fetcher.ts`, `page_manifest_extractor.ts`, and `content_script.ts`. Onboarding Hitomi.la required dynamic Referer header injection, Anycast AVIF-first (`a1`/`a2`) with WebP (`w1`/`w2`) failover, and multi-tier catalog thumbnail isolation.
3. **Blind FIFO Queue & Recycled DOM Locking:** Unbounded preloads starved active `P0` visible pages under `asyncio.Semaphore(1)`, disconnected client retries remained queued on FastAPI, and recycled SPA `<img>` elements dropped or mounted stale page translations when `img.src` changed mid-flight.
4. **LLM Prompt Personalization, Cloud Safety Filtering & Brittle JSON Parsing:** Users needed unbounded style/glossary prompts (`custom_prompt`), cloud safety-filter background masking (`safe_mask`), and resilient recovery when smaller local LLMs emit `<think>` reasoning blocks, unescaped inner quotes, or element count mismatches.

---

## 2. Decision & Implemented Architecture

### 2.1 Five-Column SQLite Cache & Zero-Poisoning Policy (`Phases 35 & 39`)
- **Composite Primary Key:** Upgrade `translation_cache` in `src/backend/cache/sqlite_cache.py` via idempotent `PRAGMA table_info` migration to `PRIMARY KEY (image_hash, target_lang, engine_used, translator_used, prompt_hash)`, where `prompt_hash` is the first 16 hex chars of SHA-256 of stripped `custom_prompt` (`""` when empty).
- **Zero-Poisoning Guard (`is_fallback`):** Extend `TranslationBatch` (`src/backend/engines/local/translator/base.py`), `TranslationResponse` (`src/backend/schemas/contract.py`, `src/types/contract.ts`), `google_free.py`, `llm_text.py`, and `local/engine.py` with `is_fallback`. `POST /api/v1/translate` (`src/backend/api/v1/translate.py`) strictly bypasses `cache.set()` when `response.is_fallback` is `True`.
- **Granular Cache Management:** Add `DELETE /api/v1/cache` (`src/backend/api/v1/cache.py`), `CLEAR_CACHE` IPC (`src/extension/shared/ipc_types.ts`, `service_worker.ts`, `backend_gateway.ts`), and split extension popup actions into `#clear-browser-cache-btn` (RAM/DOM rescan) and `#clear-db-cache-btn` (SQLite wipe) in `src/extension/popup/popup.ts`.

### 2.2 Modular `SiteAdapterRegistry`, `HitomiAdapter` & `blob:` Serialization (`Phases 35–39`)
- **Site Adapter Abstraction:** Introduce `SiteAdapter` (`src/extension/adapters/base.ts`) and `SiteAdapterRegistry` (`src/extension/adapters/registry.ts`, `index.ts`), encapsulating `MangaDexAdapter` (`src/extension/adapters/mangadex_adapter.ts`, re-exported at `background/adapters/mangadex_adapter.ts`) and `HitomiAdapter` (`src/extension/adapters/hitomi_adapter.ts`).
- **Anti-Hotlink DNR Rule:** Grant `declarativeNetRequest` in `src/extension/manifest.json` and register dynamic rule `1001` in `service_worker.ts` injecting `Referer: https://hitomi.la/` on `*://*.gold-usergeneratedcontent.net/*`.
- **AVIF-First Sharded Failover & `blob:` Fallback:** `HitomiAdapter` resolves chapter manifests, computes `a1`/`a2` AVIF subdomains with cyclic AVIF $\to$ WebP failover on 404/timeout (`DEFAULT_FETCH_TIMEOUT_MS = 8000` in `cors_fetcher.ts`), and enforces 3-tier thumbnail/preload exclusion across `reader_detector.ts`, `dom_scanner.ts`, and `content_script.ts`. Isolated `blob:` URLs resolve via manifest CDN URL or off-screen canvas JPEG serialization.

### 2.3 Priority Local Lock & Stale Request Preemption (`Phase 45`)
- **Priority Scheduler (`PriorityLocalLock`):** Replace raw `asyncio.Semaphore(1)` for local inference in `src/backend/api/v1/translate.py` and `src/backend/app.py` with heap-ordered `PriorityLocalLock` (`P0` active visible page wakes LIFO ahead of `P1`/`P2` FIFO; `promote_to_p0()` upgrades matching waiters).
- **Disconnect & Cancellation Pipeline:** FastAPI skips stale queued work via `request.is_disconnected()` (HTTP 499), singleflight deduplication ignores `is_fallback` errors or disconnected owners, and Extension dispatches `CANCEL_PENDING_TRANSLATIONS` (`ipc_types.ts`, `service_worker.ts`, `backend_gateway.ts`) while `content_script.ts` guards recycled `<img>` lifecycles with `imageGenerationMap` and synchronous `pendingImages`/`imagePendingUrlMap` tracking.

### 2.4 Custom Prompt, Cloud Safe-Mask & Resilient Local LLM Repair (`Phases 39 & 45`)
- **Contract Extensions:** Add optional `custom_prompt`, `safe_mask`, `reader_mode`, and `priority` to `TranslationRequest` (`src/backend/schemas/contract.py`, `src/types/contract.ts`).
- **Safe Prompt Injection & Visual Masking:** Inject `custom_prompt` inside an explicit `=== USER TRANSLATION STYLE & GLOSSARY GUIDELINES ===` block before the strict JSON formatting rule in `src/backend/engines/cloud/prompts.py` and `src/backend/engines/local/translator/llm_text.py`. Support background artwork masking (`create_masked_canvas` in `src/backend/engines/cloud/visual_grounding.py`) with automatic recovery on safety refusal (`CONTENT_SAFETY_BLOCKED`).
- **Resilient Local LLM JSON Recovery:** `LLMTextTranslator` (`llm_text.py`) strips `<think>` blocks, repairs trailing commas/Python literals/unescaped quotes (`_repair_malformed_json_array`), logs parse diagnostics (`LLMParseFailed`), retries with count enforcement, and recovers partial length mismatches via `_align_mismatched_translations()` rather than discarding valid translations.

---

## 3. Consequences

- **Positive Impact:**
  - Eliminated permanent cache corruption when offline translators or rate limits trigger fallbacks.
  - Adding new manga reader domains requires only registering a `SiteAdapter` implementation without modifying `cors_fetcher.ts` or `content_script.ts`.
  - Active page translations (`P0`) preempt background lookahead queues while abandoned navigations are aborted end-to-end.
  - Small local LLMs (`4B–7B`) achieve reliable batch throughput without retry storms or broken JSON crashes.
- **Trade-offs:**
  - Increases SQLite key dimensionality (`5` columns) and requires idempotent startup schema migration for legacy DBs.
  - `PriorityLocalLock` deliberately favors latest `P0` views over strict FIFO fairness during rapid scrolling.
