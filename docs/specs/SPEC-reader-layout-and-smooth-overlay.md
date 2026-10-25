# Spec: Reader Layout Strategy, Multi-Mode Culling, and Smooth Overlay Anchoring

> **Module ID:** `reader-layout-overlay`  
> **Milestone:** Phase 26  
> **Source ADR:** [docs/decisions/ADR-013-reader-layout-strategy-and-smooth-overlay-anchoring.md](../decisions/ADR-013-reader-layout-strategy-and-smooth-overlay-anchoring.md)  
> **Governing Rules:** `spec-driven-development`, `documentation-and-adrs`, `planning-and-task-breakdown`, `test-driven-development`  
> **Status:** Approved by Solo Developer (@human) on 2026-10-24  

---

## 1. Objective

Enhance the InkShift Chromium MV3 Extension overlay pipeline to eliminate spatial culling regressions, unlock rock-solid Double-Page and Long-Strip reading modes on MangaDex and universal readers, prevent overlay resurrection upon visibility toggling, and deliver smooth scroll-anchored overlay positioning without jitter.

---

## 2. Problem Statement & Root Cause Summary

1. **Visibility Toggle Stomping:**  
   `updateActiveOverlaysAppearance({ visible: true })` set `host.style.display = ''` unconditionally across all `activeOverlays`, destroying the spatial culling (`style.display = 'none'`) established on previous pages in single-page readers.
2. **Double-Page Annihilation:**  
   `isSinglePageReader()` hardcoded `hostname.includes('mangadex.org')`, forcing MangaDex to be treated as single-page even when the reader was configured for Double Page or Long Strip. In Double-Page mode, `syncOverlaysVisibilityAndPosition()` culled the layout down to a single winning image, causing continuous left/right flickering.
3. **Long-Strip Scroll Lag & Overlapping:**  
   Overlay hosts were appended as direct children of `document.body` with static absolute pixel offsets, drifting out of alignment when the reader container scrolled.

---

## 3. Architecture & Functional Requirements

### 3.1 Orthogonal Visibility Decoupling
- **Global User Visibility:**
  - Toggling `overlayVisible` (true/false) in the popup must **only** toggle `.inkshift-overlay-hidden` on each host element.
  - The Shadow DOM stylesheet `:host(.inkshift-overlay-hidden) { display: none !important; }` handles visual hiding.
  - `updateActiveOverlaysAppearance()` is strictly forbidden from setting `host.style.display = 'none'` or `host.style.display = ''`.
- **Spatial Viewport Culling:**
  - `syncOverlaysVisibilityAndPosition()` exclusively manages `host.style.display`.
  - When `overlayVisible` transitions from `false` to `true`, `syncOverlaysVisibilityAndPosition()` must be called immediately to re-cull inactive pages before rendering.

### 3.2 Reader Layout Mode Detection (`ReaderLayoutMode`)
Define `ReaderLayoutMode = 'single' | 'double' | 'strip'`:
- Implement `detectCurrentReaderLayoutMode(container?: Element, images?: HTMLImageElement[]): ReaderLayoutMode`:
  - **MangaDex Fast-Path:**
    - If `document.querySelector('.reader--mode-long-strip, .reader--mode-webtoon')` or container has vertical strip classes $\to$ `'strip'`.
    - If `document.querySelector('.reader--mode-double')` or container contains 2 horizontally adjacent active images $\to$ `'double'`.
    - If single image active $\to$ `'single'`.
  - **Generic DOM Geometry:**
    - If $\ge 2$ visible candidate images are stacked vertically (`img[1].top > img[0].top + 50`) $\to$ `'strip'`.
    - If exactly 2 visible candidate images share horizontal alignment (`|img1.top - img2.top| < 60`) with horizontal adjacency $\to$ `'double'`.
    - Otherwise $\to$ `'single'`.

### 3.3 Multi-Mode Culling Algorithm (`syncOverlaysVisibilityAndPosition`)
Update `syncOverlaysVisibilityAndPosition(options?: { layoutMode?: ReaderLayoutMode; isSinglePage?: boolean })`:
- If `layoutMode === 'double'`:
  - Preserve up to 2 active candidates that form the horizontal spread (`candidate.host.style.display = ''`).
  - Cull all other offscreen, buffer (0x0), or past-page candidates (`candidate.host.style.display = 'none'`).
- If `layoutMode === 'strip'`:
  - Preserve all candidate images intersecting the viewport (`candidate.host.style.display = ''`).
  - Cull candidates whose images are off-screen (`rect.bottom <= 10 || rect.top >= vpHeight - 10`).
- If `layoutMode === 'single'`:
  - Select the candidate closest to the horizontal center of the viewport as the sole active winner (`display = ''`).
  - Cull all other candidates (`display = 'none'`).

### 3.4 Smooth Scroll & Layout Shift Anchoring
- Attach throttled / `requestAnimationFrame` scroll listeners to `window` and the detected reader container (`activeDetection.readerContainer`).
- During scroll, call `syncOverlaysVisibilityAndPosition()` and `updateOverlayPosition()` to keep overlay hosts locked to their image bounding rects.
- Clean up listeners in `teardownContentScript()`.

### 3.5 Viewport-Aware Long-Strip Dispatching
- In `scanAndTranslate()` when `layoutMode === 'strip'` and image count $> 5$:
  - Immediately dispatch translation for images intersecting the viewport or within $1.5 \times$ viewport height lookahead.
  - As user scrolls, dispatch newly intersecting images via debounced observer.

---

## 4. Commands

```bash
# Typecheck Extension TypeScript
npm run typecheck:extension

### 3.4 Hot-Change Adaptation & Viewport Geometry Filtering (Phase 27 - ADR-014)

When user switches reading mode in-page (e.g. MangaDex reader settings menu) without full reload:
- **Viewport-Aware Intersection Filter:** `detectCurrentReaderLayoutMode()` must filter candidate images to those strictly intersecting the viewport (`rect.left < innerWidth && rect.right > 0 && rect.top < innerHeight && rect.bottom > 0`) before inspecting horizontal adjacency (`double`) or vertical stacking (`strip`).
- **4-Tier Page Resolver Cascade:** `resolveImagePageNumber(img, index)` resolves the exact chapter page number using MangaDex DOM indicators (`[data-page]`, `alt="Page X"`), universal dataset attributes, and `ChapterManifest.pages` URL mapping, preventing off-screen carousel buffer indexing from misassigning credit/intro pages.
- **Container Attribute & Class Mutation Observer:** Observe `attributes: true` with `attributeFilter: ['class', 'data-reader-mode', 'style']` on the reader container to detect mode switches dynamically and trigger immediate re-sync.
- **Responsive Bubble Rescaling:** Recompute speech bubble bounding boxes and font sizes (`rescaleOverlayBubbles(img)`) when image dimensions shift by $\ge 15\%$, avoiding polygon mask distortion across artwork.

---

## 4. Verification Plan

```powershell
# Run Extension Unit & Orchestrator Tests
npm run test:extension

# Run Focused Overlay Manager Tests
npx vitest run tests/extension/test_overlay_manager.test.ts

# Fast Project Verification (Types, Lint, Floor Guard)
python scripts/check.py --fast
```

---

## 5. Success Criteria (SC)

- [x] **SC-1 (No Resurrection on Toggle):** Toggling `overlayVisible` off and on when on page 12 leaves pages 10 and 11 hidden; only page 12 overlay is visible.
- [x] **SC-2 (Double-Page Spread Parity):** In MangaDex Double-Page mode, overlays on both the left and right pages render simultaneously without flickering or toggling off.
- [x] **SC-3 (Long-Strip Culling Parity):** In Long-Strip mode, all pages currently visible on screen render overlays; off-screen pages are culled cleanly without jumpiness.
- [x] **SC-4 (Clean Code & Separation):** `updateActiveOverlaysAppearance` never mutates `host.style.display`; uses `.inkshift-overlay-hidden`.
- [x] **SC-5 (Zero Regressions):** All 208+ TypeScript tests pass; `tsc --noEmit` reports 0 errors; Floor Guard has 0 suppressions.
- [ ] **SC-6 (Viewport-Aware Detection):** Double-page spread detection succeeds with 100% reliability regardless of off-screen carousel buffer images sitting at negative coordinates.
- [ ] **SC-7 (Page Number Parity):** Pages 8 and 9 in Double-Page mode receive translations for Pages 8 and 9; never mounts translations for Pages 4 or 5.
- [ ] **SC-8 (Hot-Change Responsiveness):** Switching modes in reader menu takes effect within $\le 50\text{ms}$ without requiring manual scrolling or page reloads.
- [ ] **SC-9 (Responsive Bubble Fitting):** Switching Single $\leftrightarrow$ Double maintains exact bubble contour hugging without mask distortion across faces.
