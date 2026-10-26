# Implementation Plan: Zero-Friction 1-Click Launch & Out-of-the-Box User Experience (Phase 31)

## Overview
Transform the repository setup and launch experience into a true, deterministic "1-click out-of-the-box" pipeline for any new user downloading a fresh clone. Eliminate false-positive dependency checks, environment priority inversions, unhandled network failures, port socket collisions, and the strict requirement for Node.js by providing robust launchers, portable extension bundling, zero-cost initial defaults, and browser-assisted onboarding.

---

## Architecture Decisions & Governing Standards

1. **Virtual Environment Priority & Deep Dependency Probe:**
   - Always prioritize `.venv\Scripts\python.exe` over host system Python.
   - Replace shallow `import fastapi, uvicorn` with a deep multi-subsystem probe (`fastapi`, `uvicorn`, `aiosqlite`, `onnxruntime`, `cv2`, `deep_translator`).
   - If any core dependency is missing, automatically trigger `pip install -r requirements.txt`.

2. **Zero-Cost Out-of-the-Box Default Configuration (`.env.example`):**
   - Configure default engine out of the box to `local` (`INKSHIFT_DEFAULT_ENGINE=local`) and translator to `google-free` (`INKSHIFT_LOCAL_DEFAULT_TRANSLATOR=google-free`).
   - Allow new users to immediately translate manga without demanding cloud API keys (Gemini/OpenAI) on first run.

3. **Portable Extension Packaging for Zero-Node.js Users:**
   - Create a Python packaging utility (`scripts/package_extension.py`) to bundle `dist/` into a portable, versioned zip (`inkshift-extension.zip`).
   - If a new user does not have Node.js/npm installed, `start.bat` will detect and extract `inkshift-extension.zip` if available, ensuring a working extension without requiring Node.js.

4. **Port 8000 Collision Guard & Downloader Error Bounding:**
   - Add pre-flight socket inspection in `start.bat` to detect lingering Python processes on port 8000 and prevent `[Errno 10048] address already in use`.
   - Add explicit `if errorlevel 1` checks to `scripts\download_models.py` with retry suggestions.

5. **Browser Auto-Onboarding:**
   - Upon gateway launch, trigger browser to open setup instructions or the API docs, and present clear Chrome extension loading coordinates (`chrome://extensions/`).

---

## Task List

### Phase 1: Launcher Hardening (`start.bat`) & Dependency Integrity
- [x] Task 31.1: Fix environment priority inversion & deep dependency verification in `start.bat`
- [x] Task 31.2: Add port 8000 pre-flight guard & strict model download error bounding in `start.bat`

### Checkpoint: Launcher Hardened
- [x] `start.bat` prioritizes `.venv` and verifies all AI dependencies.
- [x] Socket collision and network download failures are gracefully trapped.

### Phase 2: Frictionless Default Configuration & Portable Extension Packaging
- [x] Task 31.3: Update `.env.example` with zero-friction local/free defaults
- [x] Task 31.4: Implement `scripts/package_extension.py` and zip extraction fallback in `start.bat`

### Checkpoint: Portable Distribution Ready
- [x] New user can run offline without API keys.
- [x] Users without Node.js can unpack pre-built extension cleanly.

### Phase 3: Onboarding Automation & End-to-End Verification
- [x] Task 31.5: Add browser auto-onboarding launcher trigger and friendly instructions in `start.bat`
- [x] Task 31.6: Run complete verification suite (Extension Vitest 250/250, Typecheck, Python tests)

### Checkpoint: Complete Out-of-the-Box Parity
- [x] All unit and contract tests pass.
- [x] Extension freshly built and validated in `dist/`.
- [x] Ready for human sign-off.

---

## Implementation Plan: OCR Pipeline Consolidation & DirectML RapidOCR Standardization (Phase 32)

### Overview
Consolidate the local OCR pipeline around `RapidOCR` (PP-OCRv4 ONNX) running natively on Microsoft DirectML across AMD Radeon 780M, Intel, and NVIDIA GPUs. Formally deprecate and remove the non-functional `MangaOCRAdapter` stub (which previously caused HTTP 500 crashes whenever Japanese `source_lang="ja"` was selected in the browser extension), update architecture decision records (authoring ADR-017 and amending ADR-006), update the Living Spec (`SPEC-local-engine.md`), and modernize the unit test suite to guarantee 100% reliable, sub-second Japanese manga translation.

---

### Architecture Decisions & Governing Standards

1. **Hardware-Aligned DirectML OCR (ADR-017):**
   - Standardize on `rapidocr-onnxruntime` with DirectML GPU acceleration (`DmlExecutionProvider`) for all languages (`ja`, `en`, `ko`, `zh`, and `auto`).
   - Eliminate CPU-bound PyTorch MangaOCR execution (~25s/page latency and >1.5GB RAM usage) in favor of sub-second (~500ms) DirectML full-page recognition.

2. **ADR Lifecycle & Living Spec Synchronization:**
   - Preserve historical integrity of ADR-006 by marking `Status: Accepted (Amended by ADR-008, ADR-017)`.
   - Author sequential decision record `docs/decisions/ADR-017-ocr-consolidation-and-directml-rapidocr.md`.
   - Synchronize `docs/specs/SPEC-local-engine.md` and `docs/PROJECT_STATE.md`.

3. **Deterministic Language Routing:**
   - Map `ja`, `japanese`, `manga-ocr`, `en`, `ko`, `zh`, and `auto` directly to `RapidOCRAdapter`.
   - Support both single-pass full-page recognition and bubble crop fallback.
   - Guarantee `source_lang="ja"` from the browser extension succeeds with HTTP 200 without raising `ENGINE_EXECUTION_FAILED`.

4. **Zero Dead Code & Clean Configuration:**
   - Remove `src/backend/engines/local/ocr/manga_ocr.py`.
   - Remove obsolete setting `inkshift_local_manga_ocr_model_path` in `src/backend/config.py`.
   - Clean up scratch test scripts and obsolete mocks in unit tests.

---

### Task List for Phase 32

#### Phase 1: Documentation & Architectural Governance
- [x] Task 32.1: Author `docs/decisions/ADR-017-ocr-consolidation-and-directml-rapidocr.md` and amend `ADR-006`
- [x] Task 32.2: Update Living Spec `docs/specs/SPEC-local-engine.md` and `docs/PROJECT_STATE.md`

#### Checkpoint: Documentation Synchronized
- [x] ADR-017 authored and indexed.
- [x] SPEC-local-engine.md reflects active architecture.

#### Phase 2: Backend Core Engine & Router Refactoring
- [x] Task 32.3: Refactor `OCRRouter` (`src/backend/engines/local/ocr/router.py`) to consolidate to RapidOCR
- [x] Task 32.4: Clean up dead code, configurations, and package exports (`manga_ocr.py`, `config.py`, `__init__.py`)

#### Checkpoint: Core Engine Consolidated
- [x] Router maps `ja` and all languages cleanly to RapidOCR.
- [x] Dead code and obsolete config settings removed.

#### Phase 3: Test Suite Modernization & Verification Gates
- [x] Task 32.5: Modernize unit tests in `tests/backend/engines/local/` and add Japanese regression test
- [x] Task 32.6: Run full verification suite (Pytest, Extension Vitest 250/250, Typecheck)

#### Checkpoint: Full Verification Passed
- [x] 100% unit and integration tests passing.
- [x] Zero regressions across extension and backend.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| DirectML unsupported on older GPUs / VMs | Medium | Local engine auto-falls back to `CPUExecutionProvider` if `DmlExecutionProvider` fails. |
| Node.js missing on user system | High | Provide pre-packaged zip and script `scripts/package_extension.py` with fallback unzipper. |
| Port 8000 occupied by previous zombie process | Medium | Check port via PowerShell `Get-NetTCPConnection` / `netstat` and prompt user to kill or restart. |
| RapidOCR reading vertical Japanese text | Low | RapidOCR PP-OCRv4 detects Japanese Kanji/Kana reliably; bubble-scoped bounding box association in `router.py` groups vertical lines correctly. |

