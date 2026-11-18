# ADR-013: Reader Layout Strategy, Multi-Mode Culling, and Smooth Overlay Anchoring

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision-Maker:** Solo Developer (@human)
- **Consulted:** Antigravity AI Agent
- **Related Spec:** [SPEC-reader-layout-and-smooth-overlay.md](../specs/SPEC-reader-layout-and-smooth-overlay.md)
- **Amends / Extends:** [ADR-005](ADR-005-extension-core-architecture.md), [ADR-009](ADR-009-smart-reader-detection-and-domain-filtering.md)

---

## 1. Context & Problem Statement

Live testing on complex manga readers (such as MangaDex) revealed three critical rendering and UX bugs in the Chromium extension overlay pipeline:

1. **Toggle Visibility Resurrection Flaw:**  
   When the user toggles overlay visibility off and back on in the extension popup (`overlayVisible: false` -> `true`), `updateActiveOverlaysAppearance()` unconditionally reset `host.style.display = ''` across all hosts in `activeOverlays.values()`. This blew away the spatial culling (`style.display = 'none'`) previously placed on off-screen and past-chapter images. Because single-page reader overlays sit at identical viewport coordinates, all past-page bubbles (e.g. pages 10, 11) resurrected and rendered stacked directly on top of the active page (e.g. page 12).
2. **Double-Page Spread Suppression & Flickering:**  
   `content_script.ts` hardcoded `isSinglePageReader()` to return `true` whenever `hostname.includes('mangadex.org')`. In `syncOverlaysVisibilityAndPosition()`, the culling logic assumed that any reader with `isSinglePage === true` having $>1$ visible candidate must force all candidates except the single center-most winner to `display: 'none'`. On MangaDex Double-Page spread mode, this forcefully hid the second active page and triggered high-frequency flickering between left and right pages as mouse moves or micro-scrolls shifted center distance.
3. **MangaDex Long Strip Jitter & Scroll Lag:**  
   Because MangaDex was forced to `isSinglePage: true`, scrolling in MangaDex Long Strip mode triggered identical single-page culling, killing adjacent pages. Furthermore, overlay hosts were appended as direct children of `document.body` with static `top: scrollY + imgRect.top` styles without active scroll-synchronized repositioning, causing translation bubbles to drift and jump relative to the scrolling reader container.
4. **Unbounded Long-Strip Image Dispatching:**  
   `scanAndTranslate()` dispatched all images in a long-strip chapter concurrently (`Promise.all(images.map(...))`) without viewport awareness, causing request bursts on large chapters.

We require an architectural refactoring that decouples user visibility settings from spatial culling, dynamically detects reader layout modes (`single`, `double`, `strip`), preserves multiple active candidates in double/strip layouts, and provides smooth scroll synchronization.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option A: Site-Specific Fork (`mangadex_overlay_manager.ts`)** | - Complete isolation for MangaDex quirks.<br>- Freedom to hack around MangaDex DOM classes without touching other sites. | - Duplicates $>80\%$ of overlay logic (Shadow DOM, font-fitting, SVG polygon clip-paths, status pills).<br>- High maintenance burden; divergence between MangaDex and generic sites. | Rejected |
| **Option B: Reader Layout Strategy Pattern with DOM Geometry Detection (Recommended)** | - **100% DRY reuse** of Shadow DOM, polygon masking, font fitting, and status pills.<br>- Detects layout modes dynamically (`single`, `double`, `strip`) using visual DOM geometry (`getBoundingClientRect`) with site-profile fast paths.<br>- Solves Double-Page spreads universally (MangaDex, MangaPlus, ComicWalker).<br>- Separates Global User Visibility (`.inkshift-overlay-hidden` CSS) from Spatial Culling (`style.display`).<br>- Introduces requestAnimationFrame/scroll anchoring for jitter-free scrolling. | - Requires updating `overlay_manager.ts`, `content_script.ts`, and observer bindings. | **Accepted (Recommended)** |

---

## 3. Decision & Rationale

The developer approved **Option B: Reader Layout Strategy Pattern with DOM Geometry Detection & Smooth Anchoring**:

1. **Orthogonal Visibility Separation (Decoupling):**
   - **Global Visibility (User Preference):** Governed strictly by the CSS class `.inkshift-overlay-hidden` on the host element. The Shadow DOM stylesheet enforces `:host(.inkshift-overlay-hidden) { display: none !important; }`. `updateActiveOverlaysAppearance()` will **never** mutate `host.style.display`.
   - **Spatial Culling (Viewport & Reader Mode):** Governed strictly by `syncOverlaysVisibilityAndPosition()`, which sets inline `host.style.display = 'none'` or `host.style.display = ''` based on spatial geometry.
   - When the user toggles `overlayVisible` to `true`, `syncOverlaysVisibilityAndPosition()` is automatically re-invoked to ensure off-screen and inactive hosts remain culled before the next browser frame.

2. **Reader Layout Strategy (`ReaderLayoutMode: 'single' | 'double' | 'strip'`):**
   - Eliminate hardcoded `hostname.includes('mangadex.org')` single-page assumptions.
   - Introduce `detectReaderLayoutMode(container, images)`:
     - **MangaDex Fast-Path:** Check MangaDex reader state/container classes (`.reader--mode-long-strip`, `.reader--mode-webtoon`, `.reader--mode-double`, `.reader--mode-single`).
     - **DOM Geometry Fallback:**
       - **Double-Page Spread (`double`):** Exactly two active images horizontally adjacent in the viewport (`|img1.top - img2.top| < 60px` and horizontal proximity). Both candidates are treated as active winners.
       - **Long Strip (`strip`):** Images stacked vertically (`img[1].top > img[0].top`). All candidates intersecting the viewport are preserved.
       - **Single Page (`single`):** One dominant page centered in viewport. Culls carousel transition/zero-dimension buffers.

3. **Multi-Mode Culling in `syncOverlaysVisibilityAndPosition()`:**
   - In `double` mode: If 2 candidates are adjacent in viewport, **both** receive `candidate.host.style.display = ''`.
   - In `strip` mode: All on-screen candidates receive `candidate.host.style.display = ''`.
   - In `single` mode: Only the center-most winner receives `candidate.host.style.display = ''`.

4. **Smooth Scroll Anchoring & Viewport-Aware Long Strip:**
   - Attach a throttled/requestAnimationFrame scroll listener to `window` and the reader container to keep overlay host positions locked to their target `<img>` bounding rects during scroll.
   - On Long Strip chapters with $>5$ images, prioritize translating images currently intersecting or within 1.5 viewport heights of the current scroll position, deferring distant pages until the user scrolls toward them.

---

## 4. Consequences

- **Positive Impact:**
  - Toggling overlay visibility on/off no longer resurrects stale overlays from previous pages.
  - Double-page spreads on MangaDex render both pages simultaneously without flickering.
  - Long Strip readers (MangaDex, Webtoons, NetTruyen) scroll smoothly with zero overlay jitter.
  - Retains a single unified, clean, non-spaghetti codebase.
- **Trade-offs / Accepted Complexity:**
  - `syncOverlaysVisibilityAndPosition` accepts `layoutMode: ReaderLayoutMode` option.
  - Event listeners for container scroll must be cleanly detached during `teardownContentScript()`.
- **Follow-up Tasks:**
  - Author [SPEC-reader-layout-and-smooth-overlay.md](../specs/SPEC-reader-layout-and-smooth-overlay.md).
  - Create execution tasks in `tasks/plan.md` and `tasks/todo.md` (Phase 26).
  - Update `docs/PROJECT_STATE.md`.
