# Tasks: Zero-Friction 1-Click Launch & Out-of-the-Box User Experience (Phase 31)

> **Module ID:** `zero-friction-launcher-and-onboarding`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Governing Skills:** `planning-and-task-breakdown`, `debugging-and-error-recovery`, `constraint-driven-development`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero test suppression, 100% test parity, strict error bounding)  
> **Execution Status:** **COMPLETED & VERIFIED (Phase 31 Finished, 100% Tests Pass)**

---

## Phase 1: Launcher Hardening (`start.bat`) & Dependency Integrity

### Task 31.1: Fix environment priority inversion & deep dependency verification in `start.bat`
- **Description:** Refactor `start.bat` to eliminate the Python priority inversion. Prioritize `.venv\Scripts\python.exe` first. Replace shallow check `python -c "import fastapi, uvicorn"` with a deep dependency probe checking all essential backend & AI modules (`fastapi`, `uvicorn`, `aiosqlite`, `onnxruntime`, `cv2`, `deep_translator`). If any dependency is absent, automatically route to `pip install -r requirements.txt`.
- **Acceptance criteria:**
  - [x] `.venv` environment checked before system `python` or `py`.
  - [x] Deep dependency check tests for `fastapi`, `uvicorn`, `aiosqlite`, `onnxruntime`, `cv2`, `deep_translator`.
  - [x] Missing dependency properly triggers virtual environment setup and full `pip install -r requirements.txt`.
- **Verification:**
  - [x] Test execution in a Python environment lacking `onnxruntime` to ensure it does not bypass package installation.
- **Dependencies:** None
- **Files likely touched:**
  - `start.bat`
- **Estimated scope:** Small (1 file)

---

### Task 31.2: Add port 8000 pre-flight guard & strict model download error bounding in `start.bat`
- **Description:** Add pre-flight network socket check to detect if port 8000 is already bound by an orphaned Python process, preventing crash `[Errno 10048] address already in use`. Add strict `if errorlevel 1` validation after invoking `scripts\download_models.py` with friendly error instructions if model download fails.
- **Acceptance criteria:**
  - [x] Port 8000 conflict is detected before launching Uvicorn, with a clear warning and action suggestion.
  - [x] Model weights download validates exit code and aborts gracefully if network fails or file is corrupt.
- **Verification:**
  - [x] Validate batch script control flow with simulated errors.
- **Dependencies:** Task 31.1
- **Files likely touched:**
  - `start.bat`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Launcher Hardened
- [x] Priority inversion resolved in `start.bat`
- [x] Deep dependency check active
- [x] Port socket collisions and network failure bounded
- [x] Review with human before proceeding to Phase 2

---

## Phase 2: Frictionless Default Configuration & Portable Extension Packaging

### Task 31.3: Update `.env.example` with zero-friction local/free defaults
- **Description:** Adjust default configuration settings in `.env.example` so that a newly cloned repository works immediately without requiring paid or third-party cloud API credentials. Set default engine to `local` (`INKSHIFT_DEFAULT_ENGINE=local`), OCR to `auto` (`INKSHIFT_LOCAL_DEFAULT_OCR=auto`), and translator to `google-free` (`INKSHIFT_LOCAL_DEFAULT_TRANSLATOR=google-free`).
- **Acceptance criteria:**
  - [x] `.env.example` default engine is `local`.
  - [x] Default translator is `google-free` requiring zero API keys.
  - [x] Clear comments preserved for optional Gemini/OpenAI cloud configuration.
- **Verification:**
  - [x] Inspect generated `.env` on fresh setup; verify backend starts in local engine mode.
- **Dependencies:** None
- **Files likely touched:**
  - `.env.example`
- **Estimated scope:** Small (1 file)

---

### Task 31.4: Implement `scripts/package_extension.py` and zip extraction fallback in `start.bat`
- **Description:** Create a Python utility `scripts/package_extension.py` that packages the compiled `dist/` directory into a portable zip file (`inkshift-extension.zip`). Update `start.bat` so that if `dist/manifest.json` is missing and `npm` is unavailable, it checks for `inkshift-extension.zip` and automatically extracts it using Python or PowerShell, allowing users without Node.js to run the extension.
- **Acceptance criteria:**
  - [x] `scripts/package_extension.py` creates a clean zip bundle of `dist/`.
  - [x] `start.bat` extracts pre-packaged extension if Node.js/npm is missing and `inkshift-extension.zip` exists.
- **Verification:**
  - [x] Run `python scripts/package_extension.py` and verify created zip file contents.
- **Dependencies:** Task 31.2
- **Files likely touched:**
  - `scripts/package_extension.py`
  - `start.bat`
- **Estimated scope:** Small (2 files)

---

## Checkpoint: Portable Distribution Ready
- [x] Zero-friction defaults active in `.env.example`
- [x] Extension packager and fallback extractor implemented
- [x] Review with human before proceeding to Phase 3

---

## Phase 3: Onboarding Automation & End-to-End Verification

### Task 31.5: Add browser auto-onboarding launcher trigger and friendly instructions in `start.bat`
- **Description:** Enhance user onboarding at the end of `start.bat`. Upon launching Uvicorn, display a clear, formatted guide explaining exactly how to load the unpacked extension in Chrome (`chrome://extensions/` -> Enable Developer Mode -> Load Unpacked -> select `dist`). Provide an optional prompt or command to open the browser automatically to the gateway documentation page.
- **Acceptance criteria:**
  - [x] Step-by-step Chrome extension loading instructions clearly rendered in console.
  - [x] Clear display of local server URL (`http://127.0.0.1:8000`) and OpenAPI Swagger documentation (`http://127.0.0.1:8000/docs`).
- **Verification:**
  - [x] Run launcher and verify on-screen guidance formatting.
- **Dependencies:** Task 31.4
- **Files likely touched:**
  - `start.bat`
- **Estimated scope:** Small (1 file)

---

### Task 31.6: Run complete verification suite (Extension Vitest 250/250, Typecheck, Python tests)
- **Description:** Validate full system integrity after all improvements. Rebuild the extension bundle with `npm run build:extension`, verify zero TypeScript errors with `npm run typecheck:extension`, run all 250 Vitest extension tests, and run backend pytest test suite to guarantee zero regressions.
- **Acceptance criteria:**
  - [x] `npm run build:extension` compiles without errors.
  - [x] `npm run typecheck:extension` passes with 0 errors.
  - [x] Vitest unit test suite passes 100% (250/250 tests).
  - [x] Backend pytest suite passes 100% (303/303 tests).
- **Verification:**
  - [x] Run `npm run build:extension`, `npm run typecheck:extension`, `npm run test:extension`, and `pytest`.
- **Dependencies:** Tasks 31.1 - 31.5
- **Files likely touched:**
  - `dist/`
- **Estimated scope:** Small (Verification only)

---

## Checkpoint: Phase 31 Completed & Verified
- [x] All 6 tasks completed and verified
- [x] Extension fresh build verified and bundled
- [x] Ready for human sign-off

---

# Tasks: OCR Pipeline Consolidation & DirectML RapidOCR Standardization (Phase 32)

> **Module ID:** `ocr-pipeline-consolidation`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Governing Skills:** `planning-and-task-breakdown`, `debugging-and-error-recovery`, `documentation-and-adrs`, `test-driven-development`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero regressions, sub-second latency on AMD 780M, no dead stubs)  
> **Execution Status:** **PENDING HUMAN CONFIRMATION & EXECUTION**

---

## Phase 1: Documentation & Architectural Governance

### Task 32.1: Author ADR-017 and amend ADR-006
- **Description:** Document the architectural consolidation of OCR to DirectML RapidOCR in `docs/decisions/ADR-017-ocr-consolidation-and-directml-rapidocr.md`. Amend `docs/decisions/ADR-006-local-engine-architecture.md` by marking status as `Accepted (Amended by ADR-008, ADR-017)` and adding reference banner, preserving historical context without deleting past deliberations.
- **Acceptance criteria:**
  - [x] `docs/decisions/ADR-017-ocr-consolidation-and-directml-rapidocr.md` authored following template with complete trade-off analysis.
  - [x] `docs/decisions/ADR-006-local-engine-architecture.md` status updated and references ADR-017.
- **Verification:**
  - [x] Verify both markdown files render cleanly and follow repository ADR conventions.
- **Dependencies:** None
- **Files likely touched:**
  - `docs/decisions/ADR-017-ocr-consolidation-and-directml-rapidocr.md`
  - `docs/decisions/ADR-006-local-engine-architecture.md`
- **Estimated scope:** Small (2 files)

---

### Task 32.2: Update Living Spec (`SPEC-local-engine.md`) & `docs/PROJECT_STATE.md`
- **Description:** Synchronize the Living Spec `docs/specs/SPEC-local-engine.md` to reflect that RapidOCR (PP-OCRv4 ONNX DirectML) is the sole OCR engine for all languages. Update project structure tree, remove `manga_ocr.py`, update Mermaid flow diagrams, and update `docs/PROJECT_STATE.md` Architecture Decisions Index.
- **Acceptance criteria:**
  - [x] `SPEC-local-engine.md` project tree and Mermaid diagram updated.
  - [x] `docs/PROJECT_STATE.md` includes ADR-017 in index table.
- **Verification:**
  - [x] Review Spec to ensure no lingering references to `manga_ocr.py` stub.
- **Dependencies:** Task 32.1
- **Files likely touched:**
  - `docs/specs/SPEC-local-engine.md`
  - `docs/PROJECT_STATE.md`
- **Estimated scope:** Small (2 files)

---

## Checkpoint: Documentation & Spec Synchronized
- [x] ADR-017 created and ADR-006 amended
- [x] Spec updated to reflect single-engine DirectML reality
- [x] Review before code modification

---

## Phase 2: Backend Core Engine & Router Refactoring

### Task 32.3: Refactor `OCRRouter` in `src/backend/engines/local/ocr/router.py`
- **Description:** Refactor `OCRRouter` to eliminate dependency on `MangaOCRAdapter`. Map all manual overrides (`ja`, `japanese`, `manga-ocr`, `en`, `ko`, `zh`, `rapidocr`) and auto-probed Japanese text directly to `self._rapid_ocr`. Ensure both `recognize_routed()` and `recognize_routed_full_page()` handle Japanese speech bubbles cleanly without throwing exceptions.
- **Acceptance criteria:**
  - [x] Explicit selection of `source_lang="ja"` routes to RapidOCR instead of raising `RuntimeError`.
  - [x] Router does not require or import `MangaOCRAdapter`.
  - [x] Chapter language caching continues to operate smoothly for auto mode.
- **Verification:**
  - [x] Targeted tests for `router.py` with `target_mode="ja"`.
- **Dependencies:** Task 32.2
- **Files likely touched:**
  - `src/backend/engines/local/ocr/router.py`
- **Estimated scope:** Medium (1 file)

---

### Task 32.4: Clean up dead code, configurations, and scratch test scripts
- **Description:** Delete `src/backend/engines/local/ocr/manga_ocr.py`. Update `src/backend/engines/local/ocr/__init__.py` to remove `MangaOCRAdapter` export. Remove obsolete configuration `inkshift_local_manga_ocr_model_path` in `src/backend/config.py`. Clean up `.env.example` comments. Remove scratch worker scripts `scratch/run_manga_ocr_crops.py` and `scratch/test_japanese_ocr.py`.
- **Acceptance criteria:**
  - [x] `src/backend/engines/local/ocr/manga_ocr.py` deleted.
  - [x] `src/backend/engines/local/ocr/__init__.py` cleanly exports only active OCR symbols.
  - [x] `config.py` has no unused `inkshift_local_manga_ocr_model_path`.
  - [x] Scratch directory cleaned of external-venv worker scripts.
- **Verification:**
  - [x] Verify clean imports with `python -c "import src.backend.engines.local.ocr as ocr; print(dir(ocr))"`.
- **Dependencies:** Task 32.3
- **Files likely touched:**
  - `src/backend/engines/local/ocr/manga_ocr.py` (deleted)
  - `src/backend/engines/local/ocr/__init__.py`
  - `src/backend/config.py`
  - `.env.example`
  - `scratch/`
- **Estimated scope:** Small (4 files)

---

## Checkpoint: Backend Engine Refactored & Clean
- [x] `manga_ocr.py` removed
- [x] `router.py` natively routes `ja` to RapidOCR
- [x] No dead config or orphan exports

---

## Phase 3: Test Suite Modernization & Verification Gates

### Task 32.5: Modernize unit tests in `tests/backend/engines/local/` & add Japanese regression test
- **Description:** Update `tests/backend/engines/local/test_ocr_adapters.py`, `test_ocr_router.py`, `test_local_engine.py`, and `test_protocols.py`. Remove `MockMangaOCREngine` and `StubOCR("manga-ocr")` obsolete assertions. Add an explicit regression test asserting that when `POST /api/v1/translate` is called with `source_lang="ja"`, the local engine processes Japanese text via RapidOCR and returns HTTP 200 without `ENGINE_EXECUTION_FAILED`.
- **Acceptance criteria:**
  - [x] Obsolete mock tests removed or modernized for RapidOCR Japanese handling.
  - [x] New test asserts `resolve_engine("ja")` returns `RapidOCRAdapter`.
  - [x] Regression test verifies full end-to-end `source_lang="ja"` translation succeeds with HTTP 200.
- **Verification:**
  - [x] Run `pytest tests/backend/engines/local/ -v`.
- **Dependencies:** Task 32.4
- **Files likely touched:**
  - `tests/backend/engines/local/test_ocr_adapters.py`
  - `tests/backend/engines/local/test_ocr_router.py`
  - `tests/backend/engines/local/test_local_engine.py`
  - `tests/backend/engines/local/test_protocols.py`
- **Estimated scope:** Medium (4 files)

---

### Task 32.6: Run full verification suite (Pytest, Extension Vitest 250/250, Typecheck)
- **Description:** Run full quality gates across both backend and frontend. Ensure 100% test pass rate with zero suppressions or regressions.
- **Acceptance criteria:**
  - [x] Backend pytest suite: 100% passing (301/301 tests).
  - [x] Extension Vitest test suite: 100% passing (250/250 tests).
  - [x] TypeScript check: `tsc --noEmit` 0 errors.
  - [x] Working tree clean.
- **Verification:**
  - [x] Run `pytest`, `npm run test:extension`, `npm run typecheck:extension`.
- **Dependencies:** Task 32.5
- **Files likely touched:** None (Verification only)
- **Estimated scope:** Small (Verification only)

---

## Checkpoint: Phase 32 Completed & Verified
- [x] ADR-017 active and Spec synchronized
- [x] MangaOCR stub completely purged
- [x] Extension `source_lang="ja"` translates reliably via RapidOCR DirectML
- [x] All tests green (301 backend tests, 250 extension tests, 0 TS errors)


