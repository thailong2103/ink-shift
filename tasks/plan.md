# Implementation Plan: Cache Poisoning Elimination, Rescan Blob-Bypass & Purge Cache Controls (Phase 35)

## Overview
Resolve the root cause behind untranslated manga pages on MangaDex and non-functional re-scans by eliminating backend cache poisoning, resolving isolated-context `blob:` URL fetch failures in the Chromium MV3 extension, differentiating cache entries by translator/model granularity, and providing user-facing cache management controls with an explicit `DELETE /api/v1/cache` endpoint.

---

## Architecture Decisions & Governing Standards

1. **Backend Zero-Poisoning Policy (`is_fallback` Guard):**
   - When external translation services (`google-free`, `MyMemory`, or `llm-custom`) fail (e.g., HTTP 429 rate limiting, timeout, or length validation errors) and the safe fallback preserves the original untranslated text, the response contract must explicitly set `is_fallback: bool = True`.
   - The FastAPI gateway at `src/backend/api/v1/translate.py` must strictly verify that `not response.is_fallback` before writing to the SQLite cache. Untranslated fallback text must never be persisted as a successful translation.

2. **Cache Key Granularity & Backward-Compatible Migration:**
   - Extend the primary key of `translation_cache` from `(image_hash, target_lang, engine_used)` to `(image_hash, target_lang, engine_used, translator_used)` in `src/backend/cache/sqlite_cache.py`.
   - Switching between `google-free`, `llm-google`, `llm-openai`, `llm-anthropic`, and `llm-custom` (or custom models) will automatically generate unique cache entries without cross-translator collision or cache overwrites.
   - Provide an automatic, idempotent SQLite migration during `TranslationCache.initialize()` that preserves existing cached data while updating schema and composite indexes.

3. **In-Page Canvas/Manifest Blob Bypass for Chromium MV3:**
   - Chromium MV3 background service workers cannot fetch `blob:` URLs created in a webpage window context (`TypeError: Failed to fetch`).
   - In `src/extension/content/content_script.ts`, before dispatching `TRANSLATE_IMAGE`, check if `rawUrl` begins with `blob:`.
   - If `blob:` is detected, use an off-screen `<canvas>` with `canvas.toDataURL('image/jpeg', 0.92)` to serialize the element directly in the page context, or map to the canonical HTTPS CDN URL from `activeManifest.pages`.
   - Send the resolved data URL or HTTPS CDN URL in `TRANSLATE_IMAGE`, ensuring `fetchAndProcessImage()` in the background worker never fails on MangaDex reader pages.

4. **Synchronized Rescan & PrefetchScheduler Invalidation:**
   - When `RESCAN_PAGE` is dispatched, cancel in-flight prefetch tasks, purge in-memory maps (`translationCacheByUrl`, `translationCacheByPage`), and pass `forceRefresh: true` through the scheduler lookahead queue.
   - Prevent background prefetch tasks from repopulating the lookahead cache with stale or un-refreshed entries.

5. **Explicit Cache Management API & Settings Drawer UI:**
   - Implement `DELETE /api/v1/cache` in `src/backend/api/v1/cache.py` supporting scope-based invalidation (`all=true` or by `image_hash`).
   - Add a clean "Dọn dẹp bộ nhớ đệm (Clear Translation Cache)" trigger in the Extension Popup Settings Drawer with cache size reporting and confirmation safety.

---

## Task List

### Phase 1: Backend Zero-Poisoning Policy & Cache Key Granularity
- [ ] Task 35.1: Extend `TranslationResponse` contract with `is_fallback` flag and tag fallback returns in `google_free.py` & `llm_text.py`
- [ ] Task 35.2: Upgrade `TranslationCache` schema & migration to include `translator_used` in primary key and index
- [ ] Task 35.3: Prevent saving fallback responses in `api/v1/translate.py` and implement `DELETE /api/v1/cache` endpoint

### Checkpoint: Backend Zero-Poisoning & Cache Isolation Guarded
- [ ] Untranslated fallback text is never stored in SQLite cache.
- [ ] Switching translators partitions cache cleanly under distinct keys.
- [ ] Cache deletion endpoint works reliably.

### Phase 2: Extension Core Rescan & MangaDex `blob:` URL Handler
- [ ] Task 35.4: Implement Canvas/Manifest serialization in `content_script.ts` for `blob:` URLs
- [ ] Task 35.5: Synchronize `forceRefresh` through `PrefetchScheduler` on `RESCAN_PAGE` events

### Checkpoint: Extension Rescan & Blob Translation Guarded
- [ ] MangaDex `blob:` images translate without `Failed to fetch` errors in Service Worker.
- [ ] Re-scan reliably forces backend translation bypass.

### Phase 3: Purge Cache UI & Management Controls
- [ ] Task 35.6: Implement backend gateway `deleteCache()` method and IPC message `CLEAR_CACHE`
- [ ] Task 35.7: Add "Dọn dẹp bộ nhớ đệm (Clear Cache)" button & status indicator to Extension Popup (Settings Drawer)

### Checkpoint: Purge Cache Feature Complete
- [ ] User can manually clear cache from extension popup.
- [ ] Cache size updates and confirms invalidation.

### Phase 4: Full Verification, Regression Guards & Documentation
- [ ] Task 35.8: Author backend unit & regression tests for `is_fallback`, cache isolation, and cache deletion
- [ ] Task 35.9: Author frontend Vitest unit & regression tests for blob handling and cache clearing
- [ ] Task 35.10: Run full test suite (`pytest`, `npm run test:extension`, `tsc --noEmit`) and update documentation

### Checkpoint: Complete Verification & Quality Gate
- [ ] 100% tests pass with zero suppressions or type errors.
- [ ] MangaDex re-scan flow verified end-to-end.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Canvas serialization of very large images causing CPU lag on main thread | Medium | Only invoke Canvas serialization when `rawUrl` starts with `blob:`. If `activeManifest` CDN URL is available, prioritize CDN URL first to skip canvas rendering entirely. |
| SQLite table migration breaking existing cache data on user machine | High | Write idempotent `ALTER TABLE` / table copy migration in `initialize()` with fallback and automated regression tests. |
| Accidental cache deletion by user | Medium | Require modal confirmation in UI before invoking `DELETE /api/v1/cache?all=true`. |
| Cross-origin canvas tainting | Low | MangaDex images loaded into blob URLs are created same-origin (`blob:https://mangadex.org/...`), canvas readback is allowed without CORS security errors. Fallback to manifest CDN URL if canvas read fails. |

---

## Open Questions & Decisions
- All core decisions confirmed by user selecting Option C. Ready for task-by-task implementation upon confirmation.
