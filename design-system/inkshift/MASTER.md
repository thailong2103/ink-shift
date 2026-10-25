# Design System Master File: InkShift

> **Source of Truth:** InkShift Warm Obsidian & Mascot Terracotta Design System  
> **Target Surfaces:** Extension Popup UI, Floating Mascot HUD, In-Page Reading Overlays  
> **Status:** Active & Locked by Developer (@human)  
> **Primary Rule:** When building a specific page/component, check `design-system/inkshift/pages/[page-name].md` for overrides. Otherwise, strictly adhere to this Master specification.

---

## 1. Brand Identity & Art Direction

- **Project:** InkShift (Manga AI Translator & Zen Reader)
- **Visual Style:** Modern Bento Grid + Warm OLED Dark (Anthropic Claude Aesthetic Parity)
- **Mascot Identity:** Pixel-Art Inky Pet (Derived from `clawd-master` on a 15×16 coordinate grid)
- **Atmosphere:** Warm, cozy, eye-friendly, distraction-free night reading, premium tactile micro-interactions.
- **Design Dials:**
  - **Density:** `8/10` (Dense / Dashboard — optimized for 400×420px Extension Popup constraints)
  - **Variance:** `7/10` (Bento Box modularity — structured cards with clear hierarchy)
  - **Motion:** `4/10` (Smooth micro-transitions 150–250ms, zero layout thrashing)

---

## 2. Three-Layer Token Architecture (Warm Obsidian & Mascot Terracotta)

All components MUST use these CSS custom properties. Never hardcode raw hex colors in component CSS.

### Layer 1: Primitives (Base Values)
- Stone neutrals: `--primitive-stone-900` (`#12100E`), `--primitive-stone-850` (`#1C1917`), `--primitive-stone-800` (`#231F1C`), `--primitive-stone-750` (`#2A2421`), `--primitive-stone-700` (`#2E2825`), `--primitive-stone-100` (`#FAF5F0`).
- Mascot Terracotta: `--primitive-terracotta-500` (`#DE886D`), `--primitive-terracotta-400` (`#E89D84`).
- Semantic feedback: `--primitive-emerald-500` (`#10B981`), `--primitive-rose-500` (`#E11D48`), `--primitive-amber-500` (`#F59E0B`), `--primitive-sky-500` (`#0EA5E9`).
- Spacing: `--primitive-space-2xs` (2px) through `--primitive-space-2xl` (24px).
- Radii: `--primitive-radius-xs` (4px) through `--primitive-radius-full` (9999px).

### Layer 2: Semantics (Purpose Aliases)
- Canvas & Cards: `--inkshift-bg`, `--inkshift-card`, `--inkshift-card-hover`, `--inkshift-muted-surface`.
- Text & Content: `--inkshift-text-primary` (Contrast 16.2:1), `--inkshift-text-secondary` (6.5:1), `--inkshift-text-dim`, `--inkshift-text-inverse`.
- Brand & Focus: `--inkshift-brand`, `--inkshift-brand-hover`, `--inkshift-brand-muted`, `--inkshift-brand-glow`.
- Reading Overlays: `--inkshift-manga-bubble-light`, `--inkshift-manga-bubble-dark`, `--inkshift-manga-text-light`, `--inkshift-manga-text-dark`.

### Layer 3: Component Tokens (Component-Scoped Bindings)
- Buttons: `--btn-primary-bg`, `--btn-primary-bg-hover`, `--btn-primary-text`, `--btn-secondary-bg`, `--btn-icon-size`.
- Inputs: `--input-bg`, `--input-bg-focus`, `--input-border`, `--input-border-focus`, `--input-ring`, `--input-radius`.
- Bento Box: `--bento-bg`, `--bento-border`, `--bento-radius`, `--bento-well-bg`, `--bento-pad`.
- Switches: `--toggle-track-off`, `--toggle-track-on`, `--toggle-thumb`, `--toggle-width`, `--toggle-height`.
- Status Badges: `--badge-online-bg`, `--badge-online-text`, `--badge-offline-bg`, `--badge-offline-text`.
- Mascot HUD: `--hud-bg`, `--hud-border`, `--hud-shadow`, `--hud-radius`, `--hud-backdrop-blur`.

---

## 3. Typography Hierarchy

### A. Interface & System UI
- **Primary UI Font:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- **Header Branding Font:** `"Plus Jakarta Sans", "Outfit", sans-serif`
- **Monospace (Coordinates, Models, Keys):** `ui-monospace, "SF Mono", Menlo, Consolas, monospace`

### B. Authentic Manga Speech Bubble Fonts (Packaged in `assets/fonts/`)
- **Default Manga Comic:** `'Itim', cursive, sans-serif` (Balanced, natural dialogue)
- **Shouting / Impact Balloons:** `'Bangers', cursive, sans-serif` (Exclamations, SFX)
- **Handwritten / Intimate:** `'Patrick Hand', cursive, sans-serif` (Whispering, inner monologue)
- **Classic Scanlation:** `'Anime Ace 3', cursive, sans-serif` (Traditional scanlation feel)

---

## 4. Spacing Scale (Density 8/10 — Compact Dashboard)

| Token | Pixels | Rem | Usage |
|---|---|---|---|
| `--space-2xs` | `2px` | `0.125rem` | Micro-badge padding, tight tag borders |
| `--space-xs` | `4px` | `0.25rem` | Icon-to-text gap, compact button padding |
| `--space-sm` | `6px` | `0.375rem` | Inline item spacing, compact card padding |
| `--space-md` | `8px` | `0.5rem` | Standard Bento cell gap, button horizontal padding |
| `--space-lg` | `12px` | `0.75rem` | Bento Card internal padding |
| `--space-xl` | `16px` | `1.0rem` | Section headers, main container padding |
| `--space-2xl` | `24px` | `1.5rem` | Viewport bounds, modal margins |

---

## 5. Mascot Entity Specification (The Inky Mascot)

- **Canvas Size:** `viewBox="0 0 15 16"` (15 columns × 16 rows integer pixel grid)
- **Anatomy Anchors:**
  - `ground-shadow`: `x=3 y=15 w=9 h=1`, fill: `#000000`, opacity: `0.4`
  - `torso`: `x=2 y=6 w=11 h=7`, fill: `var(--inkshift-brand, #DE886D)`
  - `left-arm`: `x=0 y=9 w=2 h=2`
  - `right-arm`: `x=13 y=9 w=2 h=2`
  - `legs`: 4 legs of `1×2px` at `x=3, 5, 9, 11`, `y=13`
  - `eyes`: `1×2px` at `x=4 y=8` and `x=10 y=8`, fill: `#000000` (5px inter-pupil distance)
- **Render Scale on Readers:** Prominent `150px × 160px` badge container and pixel-art sprite with free 2D draggable physics, velocity-tilt dangles (`--drag-tilt: -14deg .. +14deg`), and squishy settle landing bounce (`mascot-settle`, 460ms).
- **Floating HUD Popover:** Directly embeds `popup.html?embedded=1` inside an isolated iframe (Single Source of Truth, 382px × 592px) for 100% feature parity with the extension popup.
- **State Machine Matrix:**
  1. `idle`: Natural breathing (`scale(1.02, 0.98)` loop 3.2s) + intermittent blinking (`idle.svg`).
  2. `reading`: Holding manga booklet (`#FAF5F0`), head nod loop (`reading.svg`).
  3. `scanning`: Magnifying lens / radar visor, YOLO detection pulse (`scanning.svg`).
  4. `translating`: Typing paws on micro-keyboard or glowing thought bubble (`translating.svg`).
  5. `success`: Double-jump celebration, 1-shot transition to `reading` (`success.svg`).
  6. `error`: Alert badge / exclamation mark, recumbent posture (`error.svg`).
  7. `sleeping`: Zzz particles emitting upward, eyes closed (`scaleY(0.1)`, `sleeping.svg`).

---

## 6. Component Guidelines

### A. Bento Cards
- Border radius: `10px` or `12px`
- Border: `1px solid var(--inkshift-border-subtle)`
- Background: `var(--inkshift-card)`
- Hover: Border transitions to `var(--inkshift-border-brand)` in 180ms ease.

### B. Interactive Controls
- **Toggle Switches:** Pill shape (`36×20px`), background `#2A2421` when OFF, `#DE886D` when ON. Thumb `#FAF5F0`.
- **Buttons (CTA):** Background `var(--inkshift-brand)` `#DE886D`, text `#12100E` font-weight 700. Hover `#E89D84`.
- **Segmented Tabs:** Background `#12100E`, active tab pill `#2A2421` with text `#FAF5F0` and subtle 1px border.

---

## 7. Pre-Delivery Quality Checklist

- [ ] **Zero-Emoji:** All UI icons must be SVG (Lucide / Heroicons).
- [ ] **Cursor:** `cursor: pointer` on all clickable interactive items.
- [ ] **Contrast:** Minimum 4.5:1 text contrast verified against `#12100E` and `#1C1917`.
- [ ] **Reduced Motion:** When `@media (prefers-reduced-motion: reduce)` is active, turn off continuous breathing/typing loops and render clean static sprites.
- [ ] **Bounds:** Extension Popup maximum width `400px`, height $\le 560px$, zero unnecessary horizontal scroll.
