# ADR-016: UI Restructuring, Modular Components & Anti-Slop Design System

- **Status:** Accepted
- **Date:** 2026-10-25
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement
With the completion of Phase 29 (Unified Bento Popup & Dynamic Floating Mascot HUD), InkShift's UI grew significantly in capabilities but accumulated architectural debt and visual inconsistencies:
1. **God-File & DRY Violations:** `src/extension/content/mascot_hud.ts` grew to 2,434 lines, embedding duplicated HTML templates, 400 lines of inline CSS, and duplicated business controllers (domain filter management, API keys, AI engine selection, aesthetic sliders) that mirror `src/extension/popup/popup.ts`.
2. **Incomplete Token Architecture:** `src/extension/shared/tokens.css` lacked Layer 3 (Component Tokens), forcing inline styles and hardcoded color values (`rgba(...)`) across components. `mascot_hud.ts` declared mismatched local variables (`--brand`, `--bg-obsidian`) breaking token continuity.
3. **Taste & Anti-Slop Deficiencies:** In-app controls mixed vector SVG icons with raw Unicode emojis (`🟢`, `🔴`, `⚙️`, `⚠️`, `🇯🇵`), creating an amateur look. Inner cards had heavy border clutter (`border-subtle` wireframing) instead of quiet, tactile resting states.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option A (Accepted): Comprehensive 3-Pillar UI Restructuring** | - Full 3-layer design tokens.<br>- Modular shared UI components (`src/extension/ui/`).<br>- Eliminates 1,000+ lines of duplicate code in `mascot_hud.ts`.<br>- 100% SVG icon standard and quiet anti-slop aesthetic. | - Touches multiple extension files. | **Recommended** |
| **Option B: CSS & Token First Only** | - Improves visual tokens without refactoring TypeScript logic. | - Retains 2,434-line god-file `mascot_hud.ts` and code duplication. | Temporary only |
| **Option C: Status Quo with Minimal Token Additions** | - Zero regression risk. | - Fails to address visual clutter, emoji mixing, and architectural debt. | Not recommended |

---

## 3. Decision & Rationale
The human developer selected **Option A**.
Key architectural decisions:
1. **3-Layer Token Architecture:** `src/extension/shared/tokens.css` implements Primitive $\rightarrow$ Semantic $\rightarrow$ Component tokens. All components strictly consume component/semantic tokens.
2. **Modular UI Controllers (`src/extension/ui/`):** Shared logic between Extension Popup and In-Page Mascot HUD is decomposed into focused controllers (`domain_manager_ui.ts`, `aesthetics_controls_ui.ts`, `engine_selector_ui.ts`, `settings_drawer_ui.ts`).
3. **Embedded Popup Iframe Architecture (Single Source of Truth):** To eliminate duplicated DOM code and prevent desynchronization between popup and in-page HUD, `mascot_hud.ts` directly embeds `popup/popup.html?embedded=1` inside an isolated iframe within the Shadow DOM popover. All settings, 2-view navigation, and controls are 100% unified from a single source.
4. **Prominent 150px × 160px Mascot Scale:** Restores and locks the prominent `150px × 160px` badge and sprite dimensions with free 2D draggable physics and squishy settle bounce, avoiding undersized characters on high-resolution manga readers.
5. **Zero-Emoji Vector Standard:** All UI glyphs are unified under `src/extension/shared/icons.ts` with consistent 16px geometric vector SVG definitions.
6. **Anti-Slop / Quiet Bento Aesthetic:** Inner row borders are replaced with subtle hover wells, enhanced typography hierarchy, and smooth tactile micro-interactions.

---

## 4. Consequences
- **Positive Impact:** Drastic reduction in duplicate code (`mascot_hud.ts` reduced from 2,434 lines to 438 lines, production bundle size for `content_script.js` reduced from 99 kB to 69 kB), guaranteed 100% feature parity between popup and floating HUD, prominent 150x160px mascot appearance, and clean isolation.
- **Trade-offs / Negatives:** Requires declaring `popup/*` and `chunks/*` in `web_accessible_resources` in `manifest.json`.
- **Follow-up Tasks:** Executed in Phase 30 (`tasks/plan.md` & `tasks/todo.md`).
