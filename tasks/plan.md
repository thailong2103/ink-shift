# Implementation Plan: Reader Layout Strategy & Smooth Overlay Anchoring (Phase 26)

## Overview
Phase 26 resolves critical rendering and overlay positioning regressions on modern manga readers (notably MangaDex). It decouples global user visibility (`.inkshift-overlay-hidden`) from spatial viewport culling (`style.display`), dynamically detects reader layout modes (**Single Page**, **Double Page Spread**, and **Long Strip**), updates culling algorithms so Double-Page mode preserves both active pages simultaneously without flickering, and implements smooth scroll-anchored overlay positioning without jitter.

---

## Architecture Decisions
- **ADR-013: Orthogonal Visibility Decoupling:** Global visibility toggle only manipulates `.inkshift-overlay-hidden` via Shadow DOM `:host(.inkshift-overlay-hidden) { display: none !important; }`. `updateActiveOverlaysAppearance()` never mutates `host.style.display`. Spatial culling is the exclusive responsibility of `syncOverlaysVisibilityAndPosition()`.
- **ADR-013: Reader Layout Strategy:** Replaces hardcoded `mangadex.org` single-page checks with dynamic `ReaderLayoutMode: 'single' | 'double' | 'strip'`. Uses MangaDex container fast-paths and DOM geometry fallbacks (detecting horizontal spreads for double, vertical stacks for strip).
- **ADR-013: Multi-Mode Culling:** Double-page spreads allow both left and right active pages to remain visible (`style.display = ''`) without one killing the other. Long strips allow all viewport-intersecting pages to remain visible.
- **ADR-013: Smooth Scroll Anchoring:** Attaches throttled/rAF scroll listeners on `window` and reader containers to keep overlay coordinates locked to image bounding rects in real time.

---

## Task List

### Phase 1: Visibility Decoupling & Toggle Bug Fix (Foundation)
- [x] Task 26.1: Decouple Global Visibility from Spatial Culling (`src/extension/content/overlay_manager.ts`, `src/extension/content/content_script.ts`)
- [x] Task 26.2: Unit Tests for Visibility Decoupling & Stale Overlay Prevention (`tests/extension/test_overlay_manager.test.ts`)

### Checkpoint: Foundation
- [x] Toggling visibility off and on preserves `display: 'none'` on off-screen/culled hosts
- [x] Unit tests pass cleanly

### Phase 2: Reader Layout Mode Detection & Multi-Mode Culling
- [x] Task 26.3: Implement Dynamic Reader Layout Mode Detection (`src/extension/content/content_script.ts`)
- [x] Task 26.4: Update Multi-Mode Culling for Double Page & Long Strip (`src/extension/content/overlay_manager.ts`)
- [x] Task 26.5: Unit Tests for Double Page & Strip Culling (`tests/extension/test_overlay_manager.test.ts`, `tests/extension/test_content_orchestrator.test.ts`)

### Checkpoint: Multi-Mode Culling
- [x] Double-page reader preserves both active pages simultaneously
- [x] Long-strip reader preserves all intersecting pages
- [x] Single-page reader maintains center-page isolation

### Phase 3: Smooth Scroll Anchoring & Viewport-Aware Dispatching
- [x] Task 26.6: Implement Smooth Scroll Anchoring & Container Event Listeners (`src/extension/content/content_script.ts`, `src/extension/content/observers.ts`)
- [x] Task 26.7: Viewport-Aware Image Dispatching on Long Strip (`src/extension/content/content_script.ts`)

### Checkpoint: Scroll & Anchoring
- [x] Overlays track image positions smoothly during scroll without jitter
- [x] Event listeners clean up cleanly on teardown

### Phase 4: Full Verification & Quality Gate
- [x] Task 26.8: End-to-End Regression & Quality Gate (`npm run test:extension`, `npm run typecheck:extension`, `python scripts/check.py --fast`)

---

# Implementation Plan: MangaDex Hot-Change Adaptation & Resilient Layout Tracking (Phase 27)

## Overview
Phase 27 resolves in-page mode switching anomalies (Hot Change) on MangaDex and universal readers. It eliminates wrong page number mappings (where query order `index + 1` caused page 4/5 credits to mount on page 8/9), filters layout detection to strictly viewport-intersecting images, observes container class/attribute mutations during mode changes, and introduces responsive bubble rescaling on dimension shifts.

---

## Architecture Decisions
- **ADR-014: Viewport-Aware Geometry Filter:** `detectCurrentReaderLayoutMode()` strictly filters candidate images to viewport bounds before evaluating geometry, ignoring off-screen carousel buffer images.
- **ADR-014: 4-Tier Page Resolver Cascade:** Resolves exact chapter page numbers using MangaDex DOM indicators (`[data-page]`, `alt="Page X"`), universal dataset attributes, and `ChapterManifest.pages` URL mapping before falling back to DOM index.
- **ADR-014: Container Attribute Mutation Observer:** In `observers.ts`, observes `attributes: true` with `attributeFilter: ['class', 'data-reader-mode', 'style']` on reader container to detect layout switches without page reloads.
- **ADR-014: Responsive Bubble Rescaling:** Recomputes letterboxed speech bubble coordinates and font sizes inside Shadow DOM when image dimensions change by $\ge 15\%$.

---

## Task List

### Phase 1: Viewport Geometry & Accurate Page Resolver (Core)
- [x] Task 27.1: Viewport-Aware Intersection Filter in `detectCurrentReaderLayoutMode` (`src/extension/content/content_script.ts`)
- [x] Task 27.2: 4-Tier Image Page Number Resolver (`src/extension/content/content_script.ts`)
- [x] Task 27.3: Unit Tests for Viewport Filtering & Page Resolver (`tests/extension/test_overlay_manager.test.ts`, `tests/extension/test_content_orchestrator.test.ts`)

### Checkpoint: Accurate Page Association
- [x] Double-page reader identifies active pages correctly without carousel buffer confusion
- [x] Pages 8 and 9 receive translations for Pages 8 and 9 (never 4 or 5)

### Phase 2: Hot-Change Observer & Responsive Bubble Rescaling
- [x] Task 27.4: Container Class & Attribute Observer for In-Page Mode Switches (`src/extension/content/observers.ts`, `src/extension/content/content_script.ts`)
- [x] Task 27.5: Responsive Speech Bubble Rescaling on Layout Shifts (`src/extension/content/overlay_manager.ts`)
- [x] Task 27.6: Unit Tests for Hot-Change Adaptation & Rescaling (`tests/extension/test_overlay_manager.test.ts`)

### Checkpoint: Hot-Change & Rescaling
- [x] Hot change takes effect in $\le 50\text{ms}$ without page reload or manual scroll
- [x] Speech bubbles contour accurately without mask distortion across faces

### Phase 3: Full Verification & Quality Gate
- [x] Task 27.7: End-to-End Regression & Quality Gate (`npm run test:extension`, `npm run typecheck:extension`, `python scripts/check.py --fast`)

---

## Phase 28: Manga Typography & Smart Bubble Font Fitting

### Overview
Phase 28 introduces authentic manga typography, user-selectable comic fonts with complete Vietnamese Unicode diacritics, and upgrades the font fitting algorithm to Smart Bubble Typography Fitter v2. This eliminates flat single-line stretching in tall bubbles, tiny text in large shouting balloons, and clipping in micro-bubbles.

### Architecture Decisions
- **ADR-015: Manga Typography Strategy:** Package `.woff2` fonts offline under `src/extension/assets/fonts/` (CC Wild Words, Comic Neue, Bangers, Patrick Hand, System UI).
- **ADR-015: Dynamic Max/Min Bounds:** Compute `maxFontSize = Math.min(Math.max(24, Math.floor(H * 0.65)), 80)` and drop `minFontSize = 7.5` with micro-padding for $H < 28\text{px}$.
- **ADR-015: Aspect-Ratio Oval Line Balancing:** Apply native CSS `text-wrap: balance` and constrain `max-width: 82%` when $W / H \ge 1.3$ and $words \ge 4$.
- **ADR-015: Shouting Scale:** Render high-impact shouting bubbles ($words \le 3$, area $\ge 10,000\text{px}^2$) with `font-weight: 800` filling 50–70% balloon height.

### Task List

#### Phase 1: Manga Font Packaging & Configuration UI
- [x] Task 28.1: Package and register Manga font assets (`src/extension/assets/fonts/`), update `manifest.json` `web_accessible_resources`, and define `@font-face` styles in `src/extension/content/overlay_manager.ts`.
- [x] Task 28.2: Add Manga font picker to `popup.html`, wire storage persistence in `popup.ts`, and sync runtime font updates to overlays in `content_script.ts`.

#### Phase 2: Smart Bubble Typography Fitter v2
- [x] Task 28.3: Upgrade `fitFontSize()` in `src/extension/content/font_fitter.ts` with dynamic upper bound, adaptive lower bound, and aspect-ratio oval constraints.
- [x] Task 28.4: Update `overlay_manager.ts` text layers with `text-wrap: balance`, shouting detection (`font-weight: 800`), and `--inkshift-font-family`.

#### Phase 3: Testing & Quality Gate
- [x] Task 28.5: Author unit tests in `tests/extension/test_font_fitter.test.ts` and `tests/extension/test_popup.test.ts` for dynamic scaling, shouting bounds, oval balancing, and font switching.
- [x] Task 28.6: Full Regression & Quality Gate (`npm run test:extension`, `npm run typecheck:extension`, `python scripts/check.py --fast`, `npm run build:extension`).

---

# Implementation Plan: Unified UI Overhaul — Bento Popup UI & Dynamic Floating Mascot HUD (Phase 29)

## Overview
Phase 29 implements the approved [SPEC-popup-and-mascot-hud.md](../docs/specs/SPEC-popup-and-mascot-hud.md) and locked [design-system/inkshift/MASTER.md](../design-system/inkshift/MASTER.md). It delivers the Warm Obsidian & Mascot Terracotta (`#DE886D`) theme, transforms the monolithic Popup into an ultra-clean 2-View Bento Grid model (compact Main View $\le 420\text{px}$ + Settings Drawer via `⚙️`), and deploys an in-page Dynamic Floating Mascot HUD inside Shadow DOM with draggable physics, edge-snapping, live state reflection, and in-place popup expansion.

---

## Architecture Decisions
- **Unified Warm Obsidian Theme:** Establishes `src/extension/shared/tokens.css` with exact mascot body color `#DE886D` on `#12100E` obsidian background (WCAG AAA contrast 16.2:1).
- **2-View Bento Popup:** Splits reading controls (Main View) from 1-time setup (Settings View) using CSS 3D translation with zero vertical scroll on main view.
- **Isolated Shadow DOM Mascot HUD:** Mounts a draggable 44×44px floating character badge on reader pages with left/right auto-docking and in-place 360×420px expanded card.
- **Live Pipeline Mascot State Machine:** Character reactively switches sprites (`idle`, `reading`, `scanning`, `translating`, `success`, `error`, `sleeping`) based on translation lifecycle events.

---

## Task List

### Phase 1: Token Engine & Assets Foundation
- [x] Task 29.1: Create `src/extension/shared/tokens.css` with Warm Obsidian & Mascot Terracotta theme tokens (`src/extension/shared/tokens.css`).
- [x] Task 29.2: Package Mascot vector sprites into `src/extension/assets/mascot/` with customizable CSS variables (`src/extension/assets/mascot/*`, `src/extension/manifest.json`).

### Phase 2: 2-View Bento Popup UI Re-architecture
- [x] Task 29.3: Refactor `src/extension/popup/popup.html` into View A (Main Reading Dashboard $\le 420\text{px}$) and View B (Settings & Configuration Drawer via `⚙️`).
- [x] Task 29.4: Rewrite `src/extension/popup/popup.css` using Bento Grid layout, tokens.css variables, zero-emoji SVG icons, and smooth view-sliding transitions.
- [x] Task 29.5: Update `src/extension/popup/popup.ts` to manage View A $\leftrightarrow$ View B sliding transitions, gear rotation, and full regression parity.

### Phase 3: Dynamic Floating Mascot HUD Component
- [x] Task 29.6: Create `src/extension/content/mascot_hud.ts` with draggable pointer physics and left/right edge-snapping within Shadow DOM.
- [x] Task 29.7: Wire reactive mascot state transitions (`idle`, `reading`, `scanning`, `translating`, `success`, `error`, `sleeping`) from content orchestrator.
- [x] Task 29.8: Implement in-place expanded Bento card when clicking mascot, with bi-directional `chrome.storage.local` synchronization.

### Phase 4: Verification & Quality Gate
- [x] Task 29.9: Author unit tests in `tests/extension/test_popup_views.test.ts` and `tests/extension/test_mascot_hud.test.ts`.
- [x] Task 29.10: Full Regression Verification (`npm run test:extension`, `npm run typecheck:extension`, `python scripts/check.py --fast`, `npm run build:extension`).

---

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Popup height overflow on small displays | Low | Strict $\le 420\text{px}$ limit on View A; inner scroll strictly localized to View B drawer. |
| Floating mascot blocking manga speech bubbles | Medium | Auto edge-docking snaps to outer 12px margin; user can drag to any vertical position or toggle off in settings. |
| Pointer events leaking from mascot to reader page | Low | Use `event.stopPropagation()` and Shadow DOM encapsulation. |
| Existing popup unit tests breaking from DOM restructuring | Medium | Maintain identical element IDs (`engine-select`, `provider-select`, `model-search-input`, etc.) so controller logic remains fully compatible. |

---

# Implementation Plan: UI Restructuring, Modular Components & Anti-Slop Design System (Phase 30)

## Overview
Phase 30 executes the comprehensive UI architecture overhaul approved in ADR-016 according to `/design`, `/design-system`, and `/design-taste-frontend`. It establishes a strict 3-Layer Design Token hierarchy, introduces a zero-emoji vector SVG icon system, decouples UI business controllers into reusable modules in `src/extension/ui/`, decomposes the 2,434-line god-file `mascot_hud.ts`, and polishes the visual layer to eliminate border clutter with quiet, tactile Bento components.

---

## Architecture Decisions
- **ADR-016: 3-Layer Token Engine:** Formalizes Primitive $\rightarrow$ Semantic $\rightarrow$ Component tokens in `src/extension/shared/tokens.css` and `design-system/inkshift/MASTER.md`.
- **ADR-016: Reusable UI Module Architecture:** Shared UI logic for domains, engines, aesthetics, and settings drawer is housed under `src/extension/ui/` and reused across both extension popup and in-page mascot HUD.
- **ADR-016: Mascot HUD Decomposition:** Splits `mascot_hud.ts` into clean physics/state management and popover rendering, adopting shared tokens and UI controllers.
- **ADR-016: Zero-Emoji Vector Standard:** `src/extension/shared/icons.ts` provides consistent SVG vector icons, eliminating raw Unicode emojis.
- **ADR-016: Anti-Slop Quiet Styling:** Replaces inner boxed wireframes with subtle hover wells, refined spacing rhythm, and tactile micro-interactions.

---

## Task List

### Phase 1: 3-Layer Token Engine & Vector Icon System
- [x] Task 30.1: Upgrade `src/extension/shared/tokens.css` and `design-system/inkshift/MASTER.md` to complete 3-Layer Token architecture.
- [x] Task 30.2: Create `src/extension/shared/icons.ts` with crisp, zero-emoji SVG icon generators.

### Phase 2: Modular Shared UI Components
- [x] Task 30.3: Create modular UI controllers in `src/extension/ui/` (`domain_manager_ui.ts`, `aesthetics_controls_ui.ts`, `engine_selector_ui.ts`, `settings_drawer_ui.ts`).

### Phase 3: Extension Popup & Mascot HUD Refactoring
- [x] Task 30.4: Refactor `src/extension/popup/` (`popup.html`, `popup.css`, `popup.ts`) to use modular UI components, embedded close handling, and anti-slop quiet styles.
- [x] Task 30.5: Refactor `src/extension/content/mascot_hud.ts` to adopt Option 1 (Embedded Popup Iframe Single Source of Truth) and lock prominent 150px × 160px scale with full 2D dragging physics.

### Phase 4: Verification, Quality Gate & Documentation
- [x] Task 30.6: Update unit tests in `tests/extension/test_popup.test.ts` and `tests/extension/test_mascot_hud.test.ts` for modular architecture parity.
- [x] Task 30.7: Full Regression Check (`npm run test:extension`, `npm run typecheck:extension`, `python scripts/check.py --fast`, `npm run build:extension`) and update `docs/PROJECT_STATE.md`.

