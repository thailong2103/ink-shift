# Tasks: Cache Poisoning Elimination, Rescan Blob-Bypass & Purge Cache Controls (Phase 35)

> **Module ID:** `cache-poisoning-rescan-blob-bypass-and-purge-cache`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Governing Skills:** `planning-and-task-breakdown`, `doubt-driven-development`, `performance-optimization`, `debugging-and-error-recovery`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero test suppression, 100% test parity, zero regression)  
> **Execution Status:** **READY FOR EXECUTION (Phase 35 Planned)**

---

## Phase 1: Backend Zero-Poisoning Policy & Cache Key Granularity

### Task 35.1: Extend `TranslationResponse` contract with `is_fallback` flag and tag fallback returns in `google_free.py` & `llm_text.py`
- **Description:** Add `is_fallback: bool = False` to `TranslationResponse` in `src/backend/schemas/contract.py` and `src/extension/shared/ipc_types.ts`. Update `google_free.py` so that when both Google Translate and MyMemory fail and source strings are preserved, `translate_batch()` flags that fallback occurred. Update `llm_text.py` so that when LLM generation fails or times out and original text is returned, it flags fallback. In `local_engine.py`, pass this flag to the returned `TranslationResponse`.
- **Acceptance criteria:**
  - [x] `TranslationResponse` has optional `is_fallback: bool = False` field in Pydantic schema and TypeScript contract.
  - [x] `google_free.py` returns `is_fallback=True` when web translation fails and returns source text.
  - [x] `llm_text.py` returns `is_fallback=True` when LLM API query fails and returns source text.
  - [x] `local_engine.py` sets `response.is_fallback = True` if any bubble was preserved via fallback.
- **Verification:**
  - [x] Schema, translator classes and engine updated with `TranslationBatch(is_fallback=...)`.
- **Dependencies:** None
- **Files touched:**
  - `src/backend/schemas/contract.py`
  - `src/types/contract.ts`
  - `src/backend/engines/local/translator/base.py`
  - `src/backend/engines/local/translator/google_free.py`
  - `src/backend/engines/local/translator/llm_text.py`
  - `src/backend/engines/local/engine.py`
- **Status:** **COMPLETED**

---

### Task 35.2: Upgrade `TranslationCache` schema & migration to include `translator_used` in primary key and index
- **Description:** Update `src/backend/cache/sqlite_cache.py` table schema for `translation_cache` to `PRIMARY KEY (image_hash, target_lang, engine_used, translator_used)`. In `initialize()`, detect if `translator_used` is missing from `table_info`, and perform a clean migration to the new schema copying existing rows (defaulting `translator_used` to `google-free` or `engine_used`). Update `get()` and `set()` signatures and queries to accept and filter by `translator_used`.
- **Acceptance criteria:**
  - [x] `translation_cache` schema contains `translator_used TEXT NOT NULL`.
  - [x] Primary key and index include `(image_hash, target_lang, engine_used, translator_used)`.
  - [x] `initialize()` idempotently migrates legacy 3-column primary key without data loss.
  - [x] `cache.get()` filters by `translator_used` when supplied.
- **Verification:**
  - [x] Verified schema upgrade, `delete()`, `clear()` methods and WAL checkpointing.
- **Dependencies:** Task 35.1
- **Files touched:**
  - `src/backend/cache/sqlite_cache.py`
- **Status:** **COMPLETED**

---

### Task 35.3: Prevent saving fallback responses in `api/v1/translate.py` and implement `DELETE /api/v1/cache` endpoint
- **Description:** In `src/backend/api/v1/translate.py`, guard `cache.set()` so that it is strictly bypassed if `response.is_fallback` is True or if all bubbles have `translated_text == original_text` on multi-character text. Pass `payload.translator` down to `cache.get()` and `cache.set()`. In `src/backend/api/v1/cache.py`, implement `DELETE /api/v1/cache` with optional query parameters `all: bool = False`, `image_hash: str | None = None` to delete all or specific cached translations. Implement `TranslationCache.delete()` and `TranslationCache.clear()`.
- **Acceptance criteria:**
  - [x] `translate_page` never writes to cache if `response.is_fallback` is True.
  - [x] `cache.set()` and `cache.get()` receive `payload.translator` to ensure engine + translator isolation.
  - [x] `DELETE /api/v1/cache?all=true` wipes the translation table and vacuum/wal-checkpoints.
  - [x] `DELETE /api/v1/cache?image_hash=...` deletes specific image hash.
- **Verification:**
  - [x] Verified cache skip for fallback responses and cache endpoint expansion.
- **Dependencies:** Task 35.2
- **Files touched:**
  - `src/backend/api/v1/translate.py`
  - `src/backend/api/v1/cache.py`
  - `src/backend/cache/sqlite_cache.py`
- **Status:** **COMPLETED**

---

## Checkpoint 1: Backend Zero-Poisoning & Cache Isolation Guarded
- [x] Fallback responses are never stored in cache.
- [x] Cache keys differentiate between translators (`google-free` vs `llm-custom`).
- [x] `DELETE /api/v1/cache` successfully invalidates target entries.


---

## Phase 2: Extension Core Rescan & MangaDex `blob:` URL Handler

### Task 35.4: Implement Canvas/Manifest serialization in `content_script.ts` for `blob:` URLs
- **Description:** In `src/extension/content/content_script.ts`, update `translateImageElement` to inspect `rawUrl`. If `rawUrl` starts with `blob:`, attempt to resolve the canonical HTTPS image URL from `activeManifest.pages[currentPage - 1]?.url`. If no manifest URL is available or manifest is pending, use an off-screen `<canvas>` context to serialize the image element via `canvas.toDataURL('image/jpeg', 0.92)`. Send the resolved HTTP URL or Base64 data URL in `TRANSLATE_IMAGE` payload, preventing Service Worker fetch failures on isolated blob contexts.
- **Acceptance criteria:**
  - [ ] When image URL is `blob:`, it resolves either via `activeManifest` CDN URL or off-screen Canvas Base64 conversion.
  - [ ] Service worker receives valid HTTP URL or Base64 data URI, avoiding `Failed to fetch` errors.
  - [ ] Graceful fallback to raw URL if canvas read fails.
- **Verification:**
  - [ ] Vitest unit test in `tests/extension/` verifying blob URL handling and canvas conversion fallback.
- **Dependencies:** Task 35.3
- **Files likely touched:**
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (1 file)

---

### Task 35.5: Synchronize `forceRefresh` through `PrefetchScheduler` on `RESCAN_PAGE` events
- **Description:** In `src/extension/content/prefetch_scheduler.ts`, add a method `resetForRescan(pageNumber: number)` or update `onPageChange(pageNumber, forceRefresh)` that cancels active lookahead tasks, clears in-memory caches, and schedules the immediate window with `forceRefresh: true`. In `content_script.ts` line 1163 (`RESCAN_PAGE` message handler), await `loadConfigFromStorage()`, call scheduler rescan reset, and ensure the current page is dispatched with `forceRefresh: true` through both DOM and prefetch pipelines.
- **Acceptance criteria:**
  - [ ] `RESCAN_PAGE` properly resets `PrefetchScheduler` task queue.
  - [ ] Immediate page prefetch task passes `forceRefresh: true` to background Service Worker.
  - [ ] In-memory translation caches (`translationCacheByUrl`, `translationCacheByPage`) are cleanly invalidated.
- **Verification:**
  - [ ] Vitest test simulating `RESCAN_PAGE` and verifying `forceRefresh: true` is propagated to background messages.
- **Dependencies:** Task 35.4
- **Files likely touched:**
  - `src/extension/content/prefetch_scheduler.ts`
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (2 files)

---

## Checkpoint 2: Extension Rescan & Blob Translation Guarded
- [ ] MangaDex `blob:` images are converted/resolved before reaching Service Worker.
- [ ] Re-scan propagates `forceRefresh: true` across all pipelines.
- [ ] Review with human before proceeding to Phase 3.

---

## Phase 3: Purge Cache UI & Management Controls

### Task 35.6: Implement backend gateway `deleteCache()` method and IPC message `CLEAR_CACHE`
- **Description:** In `src/extension/background/backend_gateway.ts`, add `clearCache(all: boolean = true, imageHash?: string): Promise<{ success: boolean; deleted: number }>`. In `src/extension/shared/ipc_types.ts`, add IPC message `{ type: 'CLEAR_CACHE'; payload?: { all?: boolean; imageHash?: string } }`. In `src/extension/background/service_worker.ts`, handle `CLEAR_CACHE` by calling `gateway.clearCache()` and returning typed response.
- **Acceptance criteria:**
  - [ ] `BackendGateway.clearCache()` sends `DELETE /api/v1/cache` with retry logic.
  - [ ] `CLEAR_CACHE` IPC message and response types added to `ipc_types.ts`.
  - [ ] `service_worker.ts` handles `CLEAR_CACHE` and returns deletion statistics.
- **Verification:**
  - [ ] Vitest tests for `backend_gateway.ts` and `service_worker.ts` handling `CLEAR_CACHE`.
- **Dependencies:** Task 35.5
- **Files likely touched:**
  - `src/extension/background/backend_gateway.ts`
  - `src/extension/shared/ipc_types.ts`
  - `src/extension/background/service_worker.ts`
- **Estimated scope:** Small (3 files)

---

### Task 35.7: Add "Dọn dẹp bộ nhớ đệm (Clear Cache)" button & status indicator to Extension Popup (Settings Drawer)
- **Description:** In `src/extension/popup/popup.html`, add a Cache Management row in the Settings Drawer / System Status card with a "Xóa bộ nhớ đệm (Clear Cache)" button and status text. In `src/extension/popup/popup.ts`, bind the button to prompt confirmation (via browser confirm or inline warning), send `CLEAR_CACHE` IPC to background, show success feedback with count of deleted entries, and trigger a tab re-scan if on a manga page.
- **Acceptance criteria:**
  - [ ] Clear Cache button rendered cleanly matching InkShift anti-slop dark UI aesthetics.
  - [ ] Confirmation prompt prevents accidental bulk deletion.
  - [ ] Success message displays cleared records count and updates status.
- **Verification:**
  - [ ] Vitest test for `popup.ts` verifying click handler dispatches `CLEAR_CACHE` and updates UI.
- **Dependencies:** Task 35.6
- **Files likely touched:**
  - `src/extension/popup/popup.html`
  - `src/extension/popup/popup.ts`
- **Estimated scope:** Small (2 files)

---

## Checkpoint 3: Purge Cache Feature Complete
- [ ] User can manually clear cache from extension popup.
- [ ] Gateway communicates `DELETE /api/v1/cache` smoothly.
- [ ] Review with human before proceeding to Phase 4.

---

## Phase 4: Full Verification, Regression Guards & Documentation

### Task 35.8: Author backend unit & regression tests for `is_fallback`, cache isolation, and cache deletion
- **Description:** Add comprehensive Pytest tests in `tests/backend/`:
  1. Test that `google_free.py` and `llm_text.py` return `is_fallback=True` on failure.
  2. Regression test asserting that `translate_page` does NOT write to cache when `response.is_fallback == True`.
  3. Regression test asserting that `google-free` and `llm-custom` caches are isolated in SQLite under distinct keys.
  4. Test that `DELETE /api/v1/cache` wipes table and returns HTTP 200.
- **Acceptance criteria:**
  - [ ] All new backend tests pass with 100% green status.
  - [ ] Test coverage exceeds 80% on modified lines.
- **Verification:**
  - [ ] Run `pytest tests/backend/ -v`.
- **Dependencies:** Task 35.7
- **Files likely touched:**
  - `tests/backend/api/v1/test_translate.py`
  - `tests/backend/cache/test_sqlite_cache.py`
  - `tests/backend/api/v1/test_cache.py`
- **Estimated scope:** Medium (3 files)

---

### Task 35.9: Author frontend Vitest unit & regression tests for blob handling and cache clearing
- **Description:** Add Vitest tests in `tests/extension/`:
  1. Test Canvas serialization fallback for `blob:` URLs in `content_script.test.ts`.
  2. Test `RESCAN_PAGE` message handling properly setting `forceRefresh: true` and resetting prefetch tasks.
  3. Test `CLEAR_CACHE` IPC dispatch and popup feedback rendering.
- **Acceptance criteria:**
  - [ ] All new frontend tests pass 100%.
  - [ ] Zero TypeScript errors (`npm run typecheck:extension`).
- **Verification:**
  - [ ] Run `npm run test:extension` and `npm run typecheck:extension`.
- **Dependencies:** Task 35.8
- **Files likely touched:**
  - `tests/extension/test_content_script.test.ts`
  - `tests/extension/test_backend_gateway.test.ts`
  - `tests/extension/test_popup.test.ts`
- **Estimated scope:** Medium (3 files)

---

### Task 35.10: Run full test suite (`pytest`, `npm run test:extension`, `tsc --noEmit`) and update documentation
- **Description:** Execute complete verification across entire project. Rebuild extension with `npm run build:extension`. Synchronize `docs/PROJECT_STATE.md` with Phase 35 status. Ensure zero suppressions and clean working tree.
- **Acceptance criteria:**
  - [ ] `pytest` passes 100% (all backend tests).
  - [ ] `npm run test:extension` passes 100% (all extension tests).
  - [ ] `npm run typecheck:extension` passes with 0 errors.
  - [ ] `docs/PROJECT_STATE.md` updated to document Phase 35.
- **Verification:**
  - [ ] Run `pytest`, `npm run test:extension`, `npm run typecheck:extension`, and `git status`.
- **Dependencies:** Task 35.9
- **Files likely touched:**
  - `docs/PROJECT_STATE.md`
  - `dist/`
- **Estimated scope:** Small (Verification & Documentation)

---

## Checkpoint 4: Complete Verification & Quality Gate
- [ ] 100% tests pass across backend and extension.
- [ ] Zero TypeScript errors, zero suppressions.
- [ ] Phase 35 verified and ready for human acceptance.
