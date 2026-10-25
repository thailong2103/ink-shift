# Tasks: Reader Layout Strategy & Smooth Overlay Anchoring (Phase 26)

> **Module ID:** `reader-layout-overlay`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Source Spec:** [docs/specs/SPEC-reader-layout-and-smooth-overlay.md](../docs/specs/SPEC-reader-layout-and-smooth-overlay.md)  
> **Source ADR:** [docs/decisions/ADR-013-reader-layout-strategy-and-smooth-overlay-anchoring.md](../docs/decisions/ADR-013-reader-layout-strategy-and-smooth-overlay-anchoring.md)  
> **Governing Skills:** `planning-and-task-breakdown`, `documentation-and-adrs`, `test-driven-development`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)

---

## Phase 1: Visibility Decoupling & Toggle Bug Fix (Foundation)

### Task 26.1: Decouple Global Visibility from Spatial Culling
- **Description:** In `src/extension/content/overlay_manager.ts`, update `updateActiveOverlaysAppearance()` to strictly mutate `host.classList.add/remove('inkshift-overlay-hidden')` without touching `host.style.display`. In `src/extension/content/content_script.ts`, update `storageListener` to invoke `syncOverlaysVisibilityAndPosition()` whenever `changes.overlayVisible` transitions to `true`.
- **Acceptance criteria:**
  - [x] `updateActiveOverlaysAppearance` never sets `host.style.display = 'none'` or `host.style.display = ''`.
  - [x] Hiding overlays adds `.inkshift-overlay-hidden` which triggers `:host(.inkshift-overlay-hidden) { display: none !important; }`.
  - [x] Revealing overlays removes `.inkshift-overlay-hidden` and immediately re-evaluates `syncOverlaysVisibilityAndPosition()`.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
  - [x] Unit tests pass: `npx vitest run tests/extension/test_overlay_manager.test.ts`
- **Dependencies:** None
- **Files likely touched:**
  - `src/extension/content/overlay_manager.ts`
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (2 files)

---

### Task 26.2: Unit Tests for Visibility Decoupling & Stale Overlay Prevention
- **Description:** In `tests/extension/test_overlay_manager.test.ts`, author comprehensive unit tests verifying that when multiple overlay hosts exist (where one host was culled with `display: 'none'`), toggling visibility off and on preserves `display: 'none'` on the culled host.
- **Acceptance criteria:**
  - [x] Test verifies that off-screen/culled overlay hosts remain `display: 'none'` when `updateActiveOverlaysAppearance({ visible: true })` is invoked.
  - [x] Test verifies that active overlay host receives visible display.
- **Verification:**
  - [x] Tests pass: `npx vitest run tests/extension/test_overlay_manager.test.ts`
- **Dependencies:** Task 26.1
- **Files likely touched:**
  - `tests/extension/test_overlay_manager.test.ts`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Foundation
- [x] Toggling visibility off and on preserves `display: 'none'` on off-screen/culled hosts
- [x] Unit tests pass cleanly
- [x] Review with human before proceeding to Phase 2

---

## Phase 2: Reader Layout Mode Detection & Multi-Mode Culling

### Task 26.3: Implement Dynamic Reader Layout Mode Detection
- **Description:** In `src/extension/content/content_script.ts`, implement `detectCurrentReaderLayoutMode(container?: Element, images?: HTMLImageElement[]): 'single' | 'double' | 'strip'`. Remove the hardcoded `hostname.includes('mangadex.org')` check from `isSinglePageReader()`. Support MangaDex container class inspection and DOM geometry fallback (checking horizontal adjacency for double-page spreads and vertical stacking for long strips).
- **Acceptance criteria:**
  - [x] Correctly identifies `'double'` when 2 active images share horizontal alignment.
  - [x] Correctly identifies `'strip'` on vertical long strips.
  - [x] Correctly identifies `'single'` on single-page carousels.
  - [x] Eliminates hardcoded MangaDex domain single-page assumptions.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** None
- **Files likely touched:**
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (1 file)

---

### Task 26.4: Update Multi-Mode Culling for Double Page & Long Strip
- **Description:** In `src/extension/content/overlay_manager.ts`, update `syncOverlaysVisibilityAndPosition(options?: { layoutMode?: 'single' | 'double' | 'strip'; isSinglePage?: boolean })` to support multi-mode culling. In `'double'` mode, preserve up to 2 active candidates forming the horizontal spread. In `'strip'` mode, preserve all candidates intersecting the viewport. In `'single'` mode, preserve the single center-most winner.
- **Acceptance criteria:**
  - [x] In `'double'` mode, both active pages receive `candidate.host.style.display = ''`.
  - [x] In `'strip'` mode, all on-screen images receive `candidate.host.style.display = ''`.
  - [x] In `'single'` mode, only the winning center image receives `display = ''`.
  - [x] Culled or off-screen hosts receive `display = 'none'`.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 26.3
- **Files likely touched:**
  - `src/extension/content/overlay_manager.ts`
- **Estimated scope:** Small (1 file)

---

### Task 26.5: Unit Tests for Double Page & Strip Culling
- **Description:** In `tests/extension/test_overlay_manager.test.ts`, author comprehensive unit tests verifying multi-mode culling across `'single'`, `'double'`, and `'strip'` reader modes.
- **Acceptance criteria:**
  - [x] Test verifies that 2 horizontally adjacent images in `'double'` mode both remain visible.
  - [x] Test verifies that in `'strip'` mode, all on-screen images are visible and off-screen ones are hidden.
  - [x] Test verifies backward compatibility when `options` is omitted.
- **Verification:**
  - [x] Tests pass: `npx vitest run tests/extension/test_overlay_manager.test.ts`
- **Dependencies:** Task 26.4
- **Files likely touched:**
  - `tests/extension/test_overlay_manager.test.ts`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Multi-Mode Culling
- [x] Double-page reader preserves both active pages simultaneously
- [x] Long-strip reader preserves all intersecting pages
- [x] Single-page reader maintains center-page isolation
- [x] Review with human before proceeding to Phase 3

---

## Phase 3: Smooth Scroll Anchoring & Viewport-Aware Dispatching

### Task 26.6: Implement Smooth Scroll Anchoring & Container Event Listeners
- **Description:** In `src/extension/content/content_script.ts` and `observers.ts`, attach throttled/`requestAnimationFrame` scroll listeners to `window` and the detected reader container. During scroll events, dynamically update overlay host positions and culling. Ensure all event listeners are cleanly detached in `teardownContentScript()`.
- **Acceptance criteria:**
  - [x] Listens to scroll events on reader container and window without performance regression.
  - [x] Updates overlay host bounding coordinates in real time.
  - [x] Fully cleaned up on teardown without memory leaks.
- **Verification:**
  - [x] Tests pass: `npm run test:extension -- tests/extension/test_content_orchestrator.test.ts`
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 26.4
- **Files likely touched:**
  - `src/extension/content/content_script.ts`
  - `src/extension/content/observers.ts`
- **Estimated scope:** Small (2 files)

---

### Task 26.7: Viewport-Aware Image Dispatching on Long Strip
- **Description:** In `src/extension/content/content_script.ts`, update `scanAndTranslate()` when `layoutMode === 'strip'` to prioritize translating visible images and adjacent lookahead images, deferring distant pages until the user scrolls toward them.
- **Acceptance criteria:**
  - [x] On Long Strip chapters $>5$ pages, immediately translates images in/near viewport.
  - [x] Enqueues subsequent images as user scrolls toward them.
- **Verification:**
  - [x] Tests pass: `npm run test:extension -- tests/extension/test_content_orchestrator.test.ts`
- **Dependencies:** Task 26.6
- **Files likely touched:**
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Scroll & Anchoring
- [x] Overlays track image positions smoothly during scroll without jitter
- [x] Event listeners clean up cleanly on teardown
- [x] Review with human before proceeding to Phase 4

---

## Phase 4: Full Verification & Quality Gate

### Task 26.8: End-to-End Regression & Floor Guard Verification
- **Description:** Run full project regression test suite across backend and extension. Verify strict Floor Guard compliance (0 suppressions: no `# type: ignore`, `@ts-ignore`, or `# noqa`) via `scripts/check.py --fast`.
- **Acceptance criteria:**
  - [x] All extension tests pass.
  - [x] All backend tests pass.
  - [x] Strict types pass (`mypy` and `tsc`).
  - [x] Floor Guard 100% green with 0 suppressions.
- **Verification:**
  - [x] Run `python scripts/check.py --fast`
- **Dependencies:** Tasks 26.1 - 26.7
- **Files likely touched:**
  - `docs/PROJECT_STATE.md`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Phase 26 Complete
- [x] All acceptance criteria met across all tasks
- [x] Zero suppressions bar strictly preserved
- [x] Ready for review and git commit

---

# Tasks: MangaDex Hot-Change Adaptation & Resilient Layout Tracking (Phase 27)

> **Module ID:** `reader-layout-overlay`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Source Spec:** [docs/specs/SPEC-reader-layout-and-smooth-overlay.md](../docs/specs/SPEC-reader-layout-and-smooth-overlay.md)  
> **Source ADR:** [docs/decisions/ADR-014-mangadex-hot-change-and-resilient-layout-tracking.md](../docs/decisions/ADR-014-mangadex-hot-change-and-resilient-layout-tracking.md)  
> **Governing Skills:** `planning-and-task-breakdown`, `documentation-and-adrs`, `test-driven-development`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)

---

## Phase 1: Viewport Geometry & Accurate Page Resolver (Core)

### Task 27.1: Viewport-Aware Intersection Filter in `detectCurrentReaderLayoutMode`
- **Description:** In `src/extension/content/content_script.ts`, update `detectCurrentReaderLayoutMode()` to filter candidate images to those strictly intersecting the viewport (`rect.left < innerWidth && rect.right > 0 && rect.top < innerHeight && rect.bottom > 0`) before checking horizontal/vertical alignment.
- **Acceptance criteria:**
  - [x] Only on-screen images are compared for layout mode detection.
  - [x] Carousel buffer images at `left: -1920px` or negative coordinates are excluded.
  - [x] Returns `'double'` reliably on 2 horizontally adjacent on-screen images without false fallback to `'single'`.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
  - [x] Tests pass: `npx vitest run tests/extension/test_overlay_manager.test.ts`
- **Dependencies:** None
- **Files likely touched:**
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (1 file)

---

### Task 27.2: 4-Tier Image Page Number Resolver
- **Description:** In `src/extension/content/content_script.ts`, implement `resolveImagePageNumber(img: HTMLImageElement, fallbackIndex: number): number`. Resolve page number via MangaDex DOM indicators (`[data-page]`, `img.alt = 'Page X'`), universal dataset attributes (`data-page`, `data-index`), and `ChapterManifest.pages` URL mapping before falling back to `fallbackIndex + 1`.
- **Acceptance criteria:**
  - [x] In MangaDex Double-Page mode, Page 8 resolves to 8 and Page 9 resolves to 9.
  - [x] Never defaults to `index + 1` when dataset or manifest data is available.
  - [x] Eliminates mounting earlier credits/intro pages on active chapter pages.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 27.1
- **Files likely touched:**
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (1 file)

---

### Task 27.3: Unit Tests for Viewport Filtering & Page Resolver
- **Description:** In `tests/extension/test_overlay_manager.test.ts` and `test_content_orchestrator.test.ts`, author tests verifying that `detectCurrentReaderLayoutMode` ignores off-screen carousel images and `resolveImagePageNumber` resolves true page numbers from DOM attributes and manifest mapping.
- **Acceptance criteria:**
  - [x] Test verifies that off-screen images at `left: -1000px` do not prevent `'double'` detection.
  - [x] Test verifies that `data-page="9"` resolves to 9 regardless of DOM loop index.
- **Verification:**
  - [x] Tests pass: `npx vitest run tests/extension/test_overlay_manager.test.ts`
- **Dependencies:** Tasks 27.1, 27.2
- **Files likely touched:**
  - `tests/extension/test_overlay_manager.test.ts`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Accurate Page Association
- [x] Double-page reader identifies active pages correctly without carousel buffer confusion
- [x] Pages 8 and 9 receive translations for Pages 8 and 9
- [x] Review with human before proceeding to Phase 2

---

## Phase 2: Hot-Change Observer & Responsive Bubble Rescaling

### Task 27.4: Container Class & Attribute Observer for In-Page Mode Switches
- **Description:** In `src/extension/content/observers.ts` and `content_script.ts`, update `setupObservers()` to observe `attributes: true` with `attributeFilter: ['class', 'data-reader-mode', 'style']` on the detected reader container. Trigger dynamic layout re-detection and overlay re-sync when container classes toggle.
- **Acceptance criteria:**
  - [x] Toggling container class between single/double/strip triggers immediate re-detection.
  - [x] Re-sync completes in $\le 50\text{ms}$ without requiring manual scrolling.
- **Verification:**
  - [x] Tests pass: `npm run test:extension -- tests/extension/test_content_orchestrator.test.ts`
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 27.2
- **Files likely touched:**
  - `src/extension/content/observers.ts`
  - `src/extension/content/content_script.ts`
- **Estimated scope:** Small (2 files)

---

### Task 27.5: Responsive Speech Bubble Rescaling on Layout Shifts
- **Description:** In `src/extension/content/overlay_manager.ts`, implement `rescaleOverlayBubbles(img: HTMLImageElement): void`. When image dimensions shift by $\ge 15\%$, recompute speech bubble physical pixels and font sizes using the new rendered image rect.
- **Acceptance criteria:**
  - [x] Speech bubbles contour accurately without mask distortion across faces when width shifts between 100% and 50%.
  - [x] Font size refits to the updated container dimensions.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 27.4
- **Files likely touched:**
  - `src/extension/content/overlay_manager.ts`
- **Estimated scope:** Small (1 file)

---

### Task 27.6: Unit Tests for Hot-Change Adaptation & Rescaling
- **Description:** In `tests/extension/test_overlay_manager.test.ts`, author tests verifying speech bubble rescaling when image dimensions change by $\ge 15\%$.
- **Acceptance criteria:**
  - [x] Test verifies that bubble `top`, `left`, `width`, `height` scale proportionally on image resize.
- **Verification:**
  - [x] Tests pass: `npx vitest run tests/extension/test_overlay_manager.test.ts`
- **Dependencies:** Task 27.5
- **Files likely touched:**
  - `tests/extension/test_overlay_manager.test.ts`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Hot-Change & Rescaling
- [x] Hot change takes effect in $\le 50\text{ms}$ without page reload or manual scroll
- [x] Speech bubbles contour accurately without mask distortion across faces
- [x] Review with human before proceeding to Phase 3

---

## Phase 3: Full Verification & Quality Gate

### Task 27.7: End-to-End Regression & Quality Gate
- **Description:** Run full project regression test suite across backend and extension. Verify strict Floor Guard compliance (0 suppressions: no `# type: ignore`, `@ts-ignore`, or `# noqa`) via `scripts/check.py --fast`.
- **Acceptance criteria:**
  - [x] All extension tests pass.
  - [x] All backend tests pass.
  - [x] Strict types pass (`mypy` and `tsc`).
  - [x] Floor Guard 100% green with 0 suppressions.
- **Verification:**
  - [x] Run `python scripts/check.py --fast`
- **Dependencies:** Tasks 27.1 - 27.6
- **Files likely touched:**
  - `docs/PROJECT_STATE.md`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Phase 27 Complete
- [x] All acceptance criteria met across all tasks
- [x] Zero suppressions bar strictly preserved
- [x] Ready for review and git commit

---

# Tasks: Manga Typography & Smart Bubble Font Fitting (Phase 28)

> **Module ID:** `manga-typography-fitter`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Source Spec:** [docs/specs/SPEC-extension-core.md](../docs/specs/SPEC-extension-core.md)  
> **Source ADR:** [docs/decisions/ADR-015-manga-typography-and-smart-font-fitting.md](../docs/decisions/ADR-015-manga-typography-and-smart-font-fitting.md)  
> **Governing Skills:** `planning-and-task-breakdown`, `documentation-and-adrs`, `test-driven-development`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)

---

## Phase 1: Manga Font Packaging & Configuration UI

### Task 28.1: Manga Font Assets Packaging & Manifest Registration
- **Description:** Provide and bundle font files under `src/extension/assets/fonts/` (Itim, Bangers, Patrick Hand). Register fonts in `manifest.json` `web_accessible_resources`, and author `@font-face` rules in `src/extension/content/overlay_manager.ts`.
- **Acceptance criteria:**
  - [x] Font files packaged locally; zero external network requests required.
  - [x] `@font-face` rules properly declare `font-display: swap` and link via `chrome.runtime.getURL()`.
  - [x] Default font variable `--inkshift-font-family` defaults to `'Itim', cursive, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
  - [x] Unit tests pass: `npm run test:extension -- tests/extension/test_overlay_manager.test.ts`
- **Dependencies:** None
- **Files likely touched:**
  - `src/extension/manifest.json`
  - `src/extension/content/overlay_manager.ts`
  - `src/extension/assets/fonts/*`
- **Estimated scope:** Medium (3 files + font assets)

---

### Task 28.2: Manga Font Selector in Popup UI & Storage Synchronization
- **Description:** Add "Phông chữ bóng thoại" dropdown to `src/extension/popup/popup.html`, bind change listener in `src/extension/popup/popup.ts` to `speechBubbleFont` in `chrome.storage.local`. In `src/extension/content/content_script.ts`, listen for `storageListener` changes and update `--inkshift-font-family` dynamically across all active overlays.
- **Acceptance criteria:**
  - [x] Popup UI includes 4 selectable font choices: Manga Comic (Itim - Mặc định), Bangers (Action), Patrick Hand (Viết tay), System UI.
  - [x] Changing font in popup persists to storage and applies immediately to all mounted overlays without page reload.
- **Verification:**
  - [x] Tests pass: `npm run test:extension -- tests/extension/test_popup.test.ts`
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 28.1
- **Files likely touched:**
  - `src/extension/popup/popup.html`
  - `src/extension/popup/popup.ts`
  - `src/extension/content/content_script.ts`
  - `src/extension/content/overlay_manager.ts`
- **Estimated scope:** Medium (4 files)

---

## Checkpoint: Font System
- [x] Font selector visible in popup UI and persists selection across browser restarts
- [x] Overlays update font family in real-time

---

## Phase 2: Smart Bubble Typography Fitter v2

### Task 28.3: Dynamic Max/Min Bounds & Micro-Padding in `font_fitter.ts`
- **Description:** In `src/extension/content/font_fitter.ts`, upgrade `fitFontSize()` to compute dynamic `maxFontSize = Math.min(Math.max(24, Math.floor(clientH * 0.65)), 80)` and adaptive `minFontSize = (clientH < 28 || clientW < 35) ? 7.5 : 10`. Automatically adjust padding to `1px 2px` when $H < 30\text{px}$ or $W < 40\text{px}$.
- **Acceptance criteria:**
  - [x] Large shouting bubbles allow font sizes up to 60px–80px.
  - [x] Micro-bubbles down to 20px height render short text at 7.5px without edge clipping.
  - [x] Vietnamese diacritics maintain line-height 1.25.
- **Verification:**
  - [x] Unit tests pass: `npm run test:extension -- tests/extension/test_font_fitter.test.ts`
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** None
- **Files likely touched:**
  - `src/extension/content/font_fitter.ts`
- **Estimated scope:** Small (1 file)

---

### Task 28.4: Aspect-Ratio Oval Line Balancing & Shouting Detection
- **Description:** In `src/extension/content/overlay_manager.ts`, add `text-wrap: balance` to `.inkshift-text-layer`. When bubble aspect ratio $W / H \ge 1.3$ and `wordCount >= 4`, set inner max-width to $82\%$ to contour words into a balanced oval/diamond shape. When `wordCount <= 3` and bubble area $\ge 10,000\text{px}^2$, apply `font-weight: 800`.
- **Acceptance criteria:**
  - [x] Multi-word sentences in oval bubbles wrap into 2–3 balanced lines instead of a single flat string.
  - [x] Dramatic exclamations in giant balloons render bold with heavy visual impact.
- **Verification:**
  - [x] Unit tests pass: `npm run test:extension -- tests/extension/test_overlay_manager.test.ts`
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 28.3
- **Files likely touched:**
  - `src/extension/content/overlay_manager.ts`
- **Estimated scope:** Small (1 file)

---

## Checkpoint: Typography Fitter v2
- [x] No flat single-line stretching in wide/tall bubbles
- [x] Shouting bubbles fill $\ge 50\%$ height
- [x] Micro-bubbles zero clipping

---

## Phase 3: Full Verification & Quality Gate

### Task 28.5: Unit Tests for Typography Fitter v2 & Font Switching
- **Description:** Author tests in `tests/extension/test_font_fitter.test.ts`, `tests/extension/test_overlay_manager.test.ts`, and `tests/extension/test_popup.test.ts` verifying dynamic scaling, shouting bounds, oval line wrapping, and popup font selection persistence.
- **Acceptance criteria:**
  - [x] Tests verify `fitFontSize` scales up to 60px+ on large elements.
  - [x] Tests verify micro-bubbles down to 22px height fit without overflow.
  - [x] Tests verify `speechBubbleFont` updates trigger overlay style mutations.
- **Verification:**
  - [x] Tests pass: `npm run test:extension`
- **Dependencies:** Tasks 28.1 - 28.4
- **Files likely touched:**
  - `tests/extension/test_font_fitter.test.ts`
  - `tests/extension/test_overlay_manager.test.ts`
  - `tests/extension/test_popup.test.ts`
- **Estimated scope:** Medium (3 files)

---

### Task 28.6: End-to-End Regression & Quality Gate
- **Description:** Run full project regression test suite across backend and extension. Verify strict Floor Guard compliance (0 suppressions: no `# type: ignore`, `@ts-ignore`, or `# noqa`) via `scripts/check.py --fast`.
- **Acceptance criteria:**
  - [x] All extension tests pass.
  - [x] All backend tests pass.
  - [x] Strict types pass (`mypy` and `tsc`).
  - [x] Floor Guard 100% green with 0 suppressions.
  - [x] Extension production bundle builds cleanly (`npm run build:extension`).
- **Verification:**
  - [x] Run `python scripts/check.py --fast`
  - [x] Run `npm run build:extension`
- **Dependencies:** Tasks 28.1 - 28.5
- **Files likely touched:**
  - `docs/PROJECT_STATE.md`
- **Estimated scope:** Small (1 file)

---

### Task 28.7: Smooth Bubble Contour with Chaikin's Corner Cutting & Prototype Anti-Aliasing
- **Description:** Implement `smooth_polygon_chaikin()` in `src/backend/detection/postprocess.py` and apply it in `extract_rdp_polygon()` with `epsilon_factor = 0.0035` and 2-pass corner cutting subdivision. This eliminates discrete 4-6px staircase pixel teeth produced by the 256x256 YOLO prototype mask, producing vector-smooth quadratic B-spline contours.
- **Acceptance criteria:**
  - [x] Implemented `smooth_polygon_chaikin` with closed-loop corner cutting and duplicate filtering.
  - [x] `extract_rdp_polygon` produces smooth, continuous polygon vertices (~40-80 pts).
  - [x] Fully tested in `tests/backend/engines/local/test_detector.py`.
  - [x] Zero suppressions across backend and extension.
- **Verification:**
  - [x] Pytest suite passes: `pytest tests/` (295 passed)
  - [x] Fast check passes: `python scripts/check.py --fast`
- **Dependencies:** Task 28.6
- **Files touched:**
  - `src/backend/detection/postprocess.py`
  - `src/backend/detection/__init__.py`
  - `tests/backend/engines/local/test_detector.py`
- **Estimated scope:** Small (3 files)

---

## Checkpoint: Phase 28 Complete
- [x] All acceptance criteria met across all tasks
- [x] Zero suppressions bar strictly preserved
- [x] Ready for review and git commit

---

# Tasks: Unified UI Overhaul — Bento Popup UI & Dynamic Floating Mascot HUD (Phase 29)

> **Module ID:** `extension-ui-overhaul`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Source Spec:** [docs/specs/SPEC-popup-and-mascot-hud.md](../docs/specs/SPEC-popup-and-mascot-hud.md)  
> **Source Design System:** [design-system/inkshift/MASTER.md](../design-system/inkshift/MASTER.md)  
> **Governing Skills:** `planning-and-task-breakdown`, `ui-ux-pro-max`, `design-system`, `frontend-ui-engineering`, `test-driven-development`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)

---

## Phase 1: Token Engine & Assets Foundation

### Task 29.1: Warm Obsidian & Mascot Terracotta Token Engine
- **Description:** Implement `src/extension/shared/tokens.css` declaring the complete CSS Custom Property palette from `design-system/inkshift/MASTER.md` (`--inkshift-bg`, `--inkshift-card`, `--inkshift-brand: #DE886D`, `--inkshift-text-primary: #FAF5F0`, spacing, shadows, and radii).
- **Acceptance criteria:**
  - [x] `tokens.css` contains all approved design tokens with WCAG AAA contrast compliance.
  - [x] Imported across popup and Shadow DOM overlay contexts.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** None
- **Files touched:** `src/extension/shared/tokens.css`
- **Estimated scope:** Small (1 file)

---

### Task 29.2: Mascot Vector Sprites & Theme Bindings
- **Description:** Package vector sprites (`idle`, `reading`, `scanning`, `typing`, `happy`, `error`, `sleeping`) into `src/extension/assets/mascot/`. Register in `manifest.json` `web_accessible_resources`, and author CSS-driven keyframe breathing/blinking animations.
- **Acceptance criteria:**
  - [x] 7 SVG vector sprites packaged with `var(--inkshift-brand, #DE886D)` color bindings.
  - [x] Web accessible resources registered in `manifest.json`.
- **Verification:**
  - [x] Build check: `npm run build:extension`
- **Dependencies:** Task 29.1
- **Files touched:** `src/extension/manifest.json`, `src/extension/assets/mascot/*`
- **Estimated scope:** Medium (Asset files + manifest)

---

## Phase 2: 2-View Bento Popup UI Re-architecture

### Task 29.3: Refactor `popup.html` into View A (Main) and View B (Settings)
- **Description:** Restructure `popup.html` into 2 views wrapped in `#view-main` ($\le 420\text{px}$ compact reading dashboard) and `#view-settings` (collapsible drawer accessed via `#btn-open-settings`). Preserve 100% of existing DOM element IDs to prevent controller breakage.
- **Acceptance criteria:**
  - [x] View A contains active domain card, master toggle, re-scan CTA, engine/model quick picker, and manga reading customizers.
  - [x] View B contains API keys, domain whitelist/blacklist, prefetch engine, and diagnostics.
  - [x] Zero missing element IDs compared to existing popup controller contract.
- **Verification:**
  - [x] Unit tests pass: `npm run test:extension -- tests/extension/test_popup.test.ts`
- **Dependencies:** Task 29.1
- **Files touched:** `src/extension/popup/popup.html`
- **Estimated scope:** Medium (1 file)

---

### Task 29.4: Bento Grid Styling & Zero-Emoji SVGs in `popup.css`
- **Description:** Rewrite `popup.css` using modern Bento Grid cards (`border-radius: 10px`, `background: var(--inkshift-card)`, subtle borders), custom toggle switches, range sliders, and Lucide/Heroicon SVGs replacing all emoji characters. Add 3D sliding transition between View A and View B.
- **Acceptance criteria:**
  - [x] Ultra-clean Bento cards with no vertical scroll on View A.
  - [x] Smooth slide transition ($200\text{ms}$) between View A and View B with back button.
  - [x] 100% zero emoji used as icons.
- **Verification:**
  - [x] Fast check passes: `python scripts/check.py --fast`
- **Dependencies:** Task 29.3
- **Files touched:** `src/extension/popup/popup.css`
- **Estimated scope:** Medium (1 file)

---

### Task 29.5: Update `popup.ts` for View Navigation & Parity
- **Description:** In `popup.ts`, bind `#btn-open-settings` and `#btn-close-settings` to toggle `.view-settings-active`, rotate gear icon, and maintain full backward-compatible binding for all storage events, combobox, and API keys.
- **Acceptance criteria:**
  - [x] Clicking ⚙️ opens Settings; clicking `← Quay lại` returns to Main.
  - [x] Full functionality preserved for model discovery, API key saving, and domain tagging.
- **Verification:**
  - [x] Unit tests pass: `npm run test:extension -- tests/extension/test_popup.test.ts`
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Tasks 29.3, 29.4
- **Files touched:** `src/extension/popup/popup.ts`
- **Estimated scope:** Medium (1 file)

---

## Phase 3: Dynamic Floating Mascot HUD Component

### Task 29.6: Implement Draggable Mascot HUD with Edge Snapping
- **Description:** In `src/extension/content/mascot_hud.ts`, build the `MascotHUD` component mounted in the content script Shadow DOM. Implement pointer capture dragging with threshold ($< 4\text{px}$ = click) and auto-docking edge snap to left/right 12px margin. Persist position to `chrome.storage.local`.
- **Acceptance criteria:**
  - [x] Mascot drags smoothly and snaps to nearest edge upon release.
  - [x] Remembers docked position across page reloads.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 29.2
- **Files touched:** `src/extension/content/mascot_hud.ts`, `src/extension/content/content_script.ts`
- **Estimated scope:** Medium (2 files)

---

### Task 29.7: Live Pipeline Mascot State Machine
- **Description:** Connect `MascotHUD` to the content orchestrator lifecycle: trigger `scanning` on YOLO detection, `translating` on in-flight requests, `success` on render, `error` on failure, and `sleeping` when visibility is toggled OFF.
- **Acceptance criteria:**
  - [x] Mascot dynamically switches sprite frames reflecting pipeline activity in real time.
  - [x] `success` state triggers 1-shot celebration before returning to `reading`.
- **Verification:**
  - [x] Tests pass: `npm run test:extension -- tests/extension/test_content_orchestrator.test.ts`
- **Dependencies:** Task 29.6
- **Files touched:** `src/extension/content/mascot_hud.ts`, `src/extension/content/content_script.ts`
- **Estimated scope:** Small (2 files)

---

### Task 29.8: In-Place Expanded Bento Card from Mascot
- **Description:** When the mascot is clicked, open an in-place floating Bento card ($360\times 420\text{px}$) with backdrop blur and reading controls. Synchronize bidirectional mutations with `chrome.storage.local`.
- **Acceptance criteria:**
  - [x] Clicking mascot toggles in-place card adjacent to the docked edge.
  - [x] Escape key or clicking outside dismisses the card.
  - [x] Changing settings updates overlays immediately.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Tasks 29.6, 29.7
- **Files touched:** `src/extension/content/mascot_hud.ts`
- **Estimated scope:** Medium (1 file)

---

## Phase 4: Full Verification & Quality Gate

### Task 29.9: Unit Tests for 2-View Popup & Mascot HUD
- **Description:** Author comprehensive unit tests in `tests/extension/test_popup.test.ts` and `tests/extension/test_mascot_hud.test.ts` verifying view transitions, edge snapping, drag thresholds, and mascot state machine.
- **Acceptance criteria:**
  - [x] Test verifies View A $\leftrightarrow$ View B sliding navigation.
  - [x] Test verifies Mascot HUD drag, snap, and pipeline state updates.
- **Verification:**
  - [x] Tests pass: `npm run test:extension`
- **Dependencies:** Tasks 29.1 - 29.8
- **Files touched:** `tests/extension/test_popup.test.ts`, `tests/extension/test_mascot_hud.test.ts`
- **Estimated scope:** Medium (2 files)

---

### Task 29.10: End-to-End Regression & Quality Gate
- **Description:** Run full project regression check across extension and backend. Verify strict zero-suppression bar via `scripts/check.py --fast` and production build via `npm run build:extension`.
- **Acceptance criteria:**
  - [x] All extension and backend tests pass.
  - [x] Zero suppressions across all files.
  - [x] Production extension bundle builds cleanly.
- **Verification:**
  - [x] Run `python scripts/check.py --fast`
  - [x] Run `npm run build:extension`
- **Dependencies:** Tasks 29.1 - 29.9
- **Files touched:** `docs/PROJECT_STATE.md`
- **Estimated scope:** Small (1 file)

---

### Task 29.11: Free 2D Draggable Mascot, 96x104px Scale, Collapsed Drawers & 2-View HUD Parity
- **Description:** Remove auto-expand from settings drawers (`#domain-drawer`, `#api-key-drawer`) in `popup.html` and style custom animated chevrons. Upgrade `src/extension/content/mascot_hud.ts` to `96×104px` mascot size with free 2D draggable placement across the screen without wall edge snapping. Implement 2-view slider in Mascot HUD popover for 100% feature parity with extension popup.
- **Acceptance criteria:**
  - [x] Mascot is prominently displayed at `96×104px` with clear pixel rendering and subtle hover glow.
  - [x] Mascot is freely draggable to any 2D position within screen viewport without forced edge snapping.
  - [x] Settings drawers in popup and mascot HUD start collapsed with smooth rotating chevrons (`▶` rotates to `▼`).
  - [x] Mascot HUD popover provides 100% feature parity with 2-view sliding navigation (Main Dashboard $\leftrightarrow$ Settings Drawer).
- **Verification:**
  - [x] `npm run test:extension` (all 244 tests passed)
  - [x] `npm run typecheck:extension` (zero TypeScript errors)
  - [x] `python scripts/check.py --fast` (zero suppressions, Floor Guard passed)
  - [x] `npm run build:extension` (built successfully)
- **Dependencies:** Task 29.10
- **Files touched:** `src/extension/popup/popup.html`, `src/extension/popup/popup.css`, `src/extension/content/mascot_hud.ts`, `tests/extension/test_mascot_hud.test.ts`
- **Estimated scope:** Medium (4 files)

---

# Tasks: UI Restructuring, Modular Components & Anti-Slop Design System (Phase 30)

> **Module ID:** `ui-restructuring-anti-slop`  
> **Source Plan:** [tasks/plan.md](plan.md)  
> **Source ADR:** [docs/decisions/ADR-016-ui-restructuring-modular-components-and-anti-slop-design-system.md](../docs/decisions/ADR-016-ui-restructuring-modular-components-and-anti-slop-design-system.md)  
> **Governing Skills:** `design`, `design-system`, `design-taste-frontend`, `planning-and-task-breakdown`  
> **Quality Gate:** [CONSTRAINTS.md](../CONSTRAINTS.md) (Zero suppressions, strict types, coverage $\ge 80\%$)

---

## Phase 1: 3-Layer Token Engine & Vector Icon System

### Task 30.1: Upgrade 3-Layer Token Architecture in tokens.css and MASTER.md
- **Description:** Restructure `src/extension/shared/tokens.css` into Layer 1 (Primitives: raw stone, obsidian, terracotta, scales), Layer 2 (Semantics: canvas, card, brand, text, feedback, manga bubbles), and Layer 3 (Components: button, badge, input, toggle, hud popover). Update `design-system/inkshift/MASTER.md` to reflect the 3-layer architecture.
- **Acceptance criteria:**
  - [x] `tokens.css` defines Layer 1 Primitives, Layer 2 Semantics, and Layer 3 Component tokens.
  - [x] No hardcoded color values or arbitrary pixel numbers in components without token mappings.
  - [x] Dark theme manga overlay and OLED reading contrast ratios comply with WCAG AAA ($\ge 7:1$).
- **Verification:**
  - [x] TypeScript check: `cmd.exe /c "set PATH=%PATH%;C:\Program Files\nodejs& npm run typecheck:extension"`
- **Dependencies:** None
- **Files touched:** `src/extension/shared/tokens.css`, `design-system/inkshift/MASTER.md`
- **Estimated scope:** Medium (2 files)

---

### Task 30.2: Create Zero-Emoji Vector SVG Icon System
- **Description:** Create `src/extension/shared/icons.ts` providing clean, uniform 14-16px vector SVG icons (status indicators, navigation arrows, gear, re-scan, domain shields, keys, eye toggles, chevrons). Replace raw emojis (`🟢`, `🔴`, `⚙️`, `⚠️`, `▶`, `▼`, `🇯🇵`) in markup and code.
- **Acceptance criteria:**
  - [x] `src/extension/shared/icons.ts` exports helper functions or SVG string templates for all required icons.
  - [x] Zero raw emojis in status badges or interactive elements.
  - [x] All icons scale cleanly and inherit CSS `currentColor`.
- **Verification:**
  - [x] TypeScript check: `npm run typecheck:extension`
- **Dependencies:** Task 30.1
- **Files touched:** `src/extension/shared/icons.ts`
- **Estimated scope:** Small (1 file)

---

## Phase 2: Modular Shared UI Components

### Task 30.3: Create Modular UI Controllers in src/extension/ui/
- **Description:** Extract duplicated business and DOM controllers from `popup.ts` and `mascot_hud.ts` into modular components under `src/extension/ui/`: `domain_manager_ui.ts`, `aesthetics_controls_ui.ts`, `engine_selector_ui.ts`, and `settings_drawer_ui.ts`.
- **Acceptance criteria:**
  - [x] `domain_manager_ui.ts`: Handles active domain status, whitelist/blacklist badge pills, domain additions and deletions.
  - [x] `aesthetics_controls_ui.ts`: Manages comic font dropdown (`Itim`, `Bangers`, `Patrick Hand`), speech bubble opacity slider with live percentage, and bubble color palette.
  - [x] `engine_selector_ui.ts`: Controls engine mode switching (`Auto`, `Local DirectML`, `Cloud AI`), provider dropdown, and dynamic model picker.
  - [x] `settings_drawer_ui.ts`: Manages API keys accordion, prefetch toggles, and developer diagnostic utilities.
- **Verification:**
  - [x] TypeScript check passes with zero errors.
- **Dependencies:** Task 30.1, 30.2
- **Files touched:** `src/extension/ui/domain_manager_ui.ts`, `src/extension/ui/aesthetics_controls_ui.ts`, `src/extension/ui/engine_selector_ui.ts`, `src/extension/ui/settings_drawer_ui.ts`, `src/extension/ui/index.ts`
- **Estimated scope:** Medium (5 files)

---

## Phase 3: Extension Popup & Mascot HUD Refactoring
 
 ### Task 30.4: Refactor Extension Popup UI with Anti-Slop Quiet Styling
 - **Description:** Update `src/extension/popup/popup.html`, `popup.css`, and `popup.ts` to consume the modular UI controllers and new vector icons. Remove border clutter on inner setting rows, replace with subtle hover wells, and refine typography hierarchy.
 - **Acceptance criteria:**
-  - [x] `popup.html` and `popup.ts` use modular UI controllers and vector icons.
-  - [x] Inner boxed wireframes replaced with quiet, tactile Bento components.
-  - [x] Zero functional regression across all popup features and 2-view navigation.
 - **Verification:**
-  - [x] Unit tests pass: `npm run test:extension`
 - **Dependencies:** Task 30.3
 - **Files touched:** `src/extension/popup/popup.html`, `src/extension/popup/popup.css`, `src/extension/popup/popup.ts`
 - **Estimated scope:** Medium (3 files)
 
 ---
 
 ### Task 30.5: Decompose Mascot HUD and Adopt Embedded Popup Iframe (Option 1)
 - **Description:** Refactor `src/extension/content/mascot_hud.ts` to embed `popup.html?embedded=1` inside an isolated iframe popover (Single Source of Truth), eliminating 1,000+ lines of duplicated DOM template and event wiring. Restore and lock prominent 150px × 160px mascot scale with full 2D dragging physics.
 - **Acceptance criteria:**
-  - [x] `mascot_hud.ts` embeds `popup.html?embedded=1` directly in Shadow DOM popover.
-  - [x] Restores prominent 150px × 160px mascot scale with 2D drag physics and squishy landing bounce.
-  - [x] 100% feature parity with extension popup guaranteed by single source of truth.
 - **Verification:**
-  - [x] Unit tests pass: `npm run test:extension`
 - **Dependencies:** Task 30.3, 30.4
 - **Files touched:** `src/extension/content/mascot_hud.ts`
 - **Estimated scope:** Large (1 file)
 
 ---
 
 ## Phase 4: Verification, Quality Gate & Documentation
 
 ### Task 30.6: Update Unit Tests for Modular Architecture Parity
 - **Description:** Update `tests/extension/test_popup.test.ts` and `tests/extension/test_mascot_hud.test.ts` to verify the modular UI controllers, zero-emoji icon rendering, and 2-view sliding transitions.
 - **Acceptance criteria:**
-  - [x] All unit tests pass cleanly with zero suppressions.
-  - [x] Test coverage on modified UI files satisfies $\ge 80\%$.
 - **Verification:**
-  - [x] `npm run test:extension`
 - **Dependencies:** Tasks 30.1 - 30.5
 - **Files touched:** `tests/extension/test_popup.test.ts`, `tests/extension/test_mascot_hud.test.ts`
 - **Estimated scope:** Medium (2 files)
 
 ---
 
 ### Task 30.7: Full Regression Check & Project State Living Dashboard Update
 - **Description:** Run full project regression across backend and extension. Verify zero suppressions with Floor Guard, build production extension bundle, and update `docs/PROJECT_STATE.md`.
 - **Acceptance criteria:**
-  - [x] `npm run typecheck:extension` passes with zero errors.
-  - [x] All 248+ tests pass.
-  - [x] `python scripts/check.py --fast` passes Floor Guard.
-  - [x] `npm run build:extension` succeeds.
-  - [x] `docs/PROJECT_STATE.md` updated to Milestone Phase 30 Completed.
 - **Verification:**
-  - [x] `npm run build:extension`
-  - [x] `python scripts/check.py --fast`
 - **Dependencies:** Task 30.6
 - **Files touched:** `docs/PROJECT_STATE.md`
 - **Estimated scope:** Small (1 file)

---

### Task 30.8: Z-Index Occlusion Fix & Global Alt+Z / Alt+M Keyboard Shortcuts
- **Description:** Fix the stacking context collision where manga speech bubble translation overlays occluded the Mascot HUD popover. Elevate Mascot HUD host to `z-index: 2147483647` and lower overlay hosts to `z-index: 2147483640`. Implement global keyboard shortcuts in the reader page: `Alt + Z` (toggles `overlayVisible`, syncs mascot reading/sleeping state and spatial culling) and `Alt + M` (toggles Mascot HUD on/off), guarded by `isTypingContext()` and IME composition checks to prevent misfires during text entry.
- **Acceptance criteria:**
  - [x] Mascot HUD Popover floats on top of translation overlays with `z-index: 2147483647` vs overlay host `2147483640`.
  - [x] Pressing `Alt + Z` toggles translation overlays and syncs mascot state (`reading` vs `sleeping`).
  - [x] Pressing `Alt + M` toggles Mascot HUD on/off and persists state in `chrome.storage.local`.
  - [x] Typing inside `<input>`, `<textarea>`, `contenteditable`, or IME composition ignores shortcuts.
  - [x] All 250/250 unit tests pass and production bundle builds cleanly.
- **Verification:**
  - [x] `npx vitest run tests/extension` (250 tests pass)
  - [x] `npm run typecheck:extension`
  - [x] `python scripts/check.py --fast`
  - [x] `npm run build:extension`
- **Dependencies:** Task 30.7
- **Files touched:**
  - `src/extension/content/mascot_hud.ts`
  - `src/extension/content/overlay_manager.ts`
  - `src/extension/content/content_script.ts`
  - `src/extension/popup/popup.html`
  - `tests/extension/test_content_orchestrator.test.ts`
- **Estimated scope:** Medium (5 files)




