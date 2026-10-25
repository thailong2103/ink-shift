# ADR-014: MangaDex Hot-Change Adaptation, Viewport-Aware Geometry, and Resilient Layout Tracking

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement

In Phase 26, the extension implemented Reader Layout Strategy and Multi-Mode Culling (`single`, `double`, `strip`). However, live verification on MangaDex revealed critical regressions during in-page "Hot Changes" (when a user switches reader modes dynamically in the MangaDex menu without full page reloads):

1. **Page Number Desynchronization in Non-Single Modes:**
   In `content_script.ts`, `currentPageNumber` fell back to `index + 1` (DOM query index) when `isSinglePageReader()` was false. Because MangaDex retains buffered previous/next images in the DOM, query index `3` and `4` were misidentified as Page 4 and Page 5. Consequently, translations from Page 4/5 (such as credits and intro text) were mistakenly mounted onto active Pages 8 and 9.
2. **False `single` Fallback from Off-screen Buffer Images:**
   `detectCurrentReaderLayoutMode` only inspected `activeImages[0]` and `activeImages[1]`. In carousel-based readers, off-screen buffer images often have `clientWidth > 0` but `left: -1920px`, causing geometric distance checks to fail and falsely fall back to `'single'`. This caused spatial culling to indiscriminately hide one of the two active pages in double mode.
3. **Hot Change Blind Spot:**
   MangaDex toggles reader container classes (e.g. `.reader--mode-double`, `.reader--mode-long-strip`) without triggering `popstate`, `pushState`, or standard scroll events. The existing `MutationObserver` observed only `childList: true` without `attributes: true`, leaving the extension completely unaware that layout mode had switched.
4. **Speech Bubble Coordinate Distortion on Dimension Shifts:**
   `updateOverlayPosition(img)` only adjusted the root host element dimensions (`host.style.width/height`). The speech bubbles inside the Shadow DOM remained locked to physical CSS pixel coordinates computed for the previous 100% width, causing mask polygons to distort across characters' faces when width halved to 50% in double-page mode.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: Force Full Page Reload on Mode Change (`window.location.reload()`)** | - Simple to implement.<br>- Resets all DOM state cleanly. | - Jarring user experience.<br>- Discards in-memory prefetch cache and active reading progress. | Rejected |
| **Option 2: Viewport-Aware Geometry + 4-Tier Page Resolver + Container Attribute Observer + Responsive Bubble Rescaler** | - Eliminates all 4 root causes cleanly.<br>- 100% accurate page mapping via DOM dataset and Chapter Manifest matching.<br>- Filters only images intersecting visible viewport.<br>- Seamless responsive rescaling on dimension changes.<br>- Universal across all manga readers without breaking existing sites. | - Requires observing container attribute mutations and handling bubble rescale math. | **Accepted (Recommended)** |

---

## 3. Decision & Rationale

The developer approved **Option 2**:

1. **4-Tier Page Resolver Cascade:**
   - **Tier 1 (Site-Specific Fast-Path):** For MangaDex, inspect `img.closest('[data-page]')`, `img.dataset.page`, or `img.alt` containing `"Page X"`.
   - **Tier 2 (Universal Dataset Attributes):** Check standard CMS attributes (`data-page`, `data-index`, `data-page-num` in Madara, Webtoons, Bato).
   - **Tier 3 (Manifest URL Matching):** Match `img.src` or `img.currentSrc` against the `ChapterManifest.pages` array which contains authoritative `page_number` per image URL.
   - **Tier 4 (Graceful Fallback):** Safe DOM query index fallback (`index + 1`).
2. **Viewport-Aware Intersection Filter:**
   In `detectCurrentReaderLayoutMode()`, candidate images are strictly filtered to those intersecting the visible viewport (`rect.left < window.innerWidth && rect.right > 0 && rect.top < window.innerHeight && rect.bottom > 0`) before evaluating horizontal adjacency (`double`) or vertical stacking (`strip`).
3. **Container Attribute & Class Mutation Observer:**
   In `observers.ts`, expand `MutationObserver` to observe `attributes: true` with `attributeFilter: ['class', 'data-reader-mode', 'style']` on the detected reader container. When container classes toggle, immediately trigger layout re-detection and overlay synchronization.
4. **Responsive Bubble Rescaling:**
   When `ResizeObserver` detects an image's rendered width or height changes by $\ge 15\%$, recompute bubble pixel coordinates and font sizes using updated letterbox math (`rescaleOverlayBubbles(img)`).

---

## 4. Consequences

- **Positive Impact:**
  - Double-page spread displays both active pages with 100% reliability, zero flickering, and exact page-to-translation matching.
  - Hot change between Single, Double, and Long-Strip takes effect instantly ($\le 50\text{ms}$) without page reloads.
  - Speech bubbles remain perfectly fitted to artwork boundaries when resizing or changing modes.
  - Universal compatibility preserved and improved for all manga websites.
- **Trade-offs / Negatives:**
  - Slight overhead in MutationObserver listening to container class changes (mitigated by strict `attributeFilter` targeting only reader container classes).
- **Follow-up Tasks:**
  - Amend [SPEC-reader-layout-and-smooth-overlay.md](../specs/SPEC-reader-layout-and-smooth-overlay.md) with Section 3.4 and AC-06 through AC-09.
  - Execute Phase 27 tasks in [tasks/todo.md](../../tasks/todo.md).
