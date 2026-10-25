# Floating Mascot HUD Specification & Overrides

> **PROJECT:** InkShift  
> **Target:** `src/extension/content/` (`mascot_hud.ts`, Shadow DOM overlay integration)  
> **Master Reference:** `design-system/inkshift/MASTER.md`  
> **Architecture Reference:** `docs/decisions/ADR-016-ui-restructuring-modular-components-and-anti-slop-design-system.md`

---

## 1. Physical Anatomy & Placement

- **Container:** Injected inside the isolated InkShift **Shadow DOM v1** (`#inkshift-mascot-host`).
- **Prominent Scale:** `150px × 160px` badge container and pixel-art sprite (`width: 150px; height: 160px;`).
- **Initial Placement:** Anchored to right viewport margin (`y: 140px; right: auto; left: clamp(window.innerWidth - 162px)`).
- **Z-Index:** High isolation index (`2147483645` host, `2147483646` badge, `2147483647` popover) within Shadow DOM, ensuring visibility over reader canvasses and images.
- **Micro-Interactions:**
  - Resting hover: `translateY(-4px) scale(1.06)` with warm glow (`drop-shadow(0 0 16px rgba(222, 136, 109, 0.7))`).
  - Active grab: `scale(1.02)`.
  - In-flight drag: Dynamic horizontal velocity tilt (`--drag-tilt: -14deg .. +14deg`), `scale(1.15)`, and dangle animation.
  - Landing bounce: Squishy settle bounce animation (`mascot-settle`, 460ms).

---

## 2. Interaction Model: Free 2D Drag & Dock Physics

- **Free 2D Draggable:** Pointer down initiates capture. Moves freely in both X and Y dimensions within screen boundaries (no rigid wall snapping during or after release).
- **Viewport Clamping:** Clamped to `Math.max(8, Math.min(window.innerWidth - 162, curX))` and `Math.max(8, Math.min(window.innerHeight - 172, curY))`.
- **Persistent Coordinate:** Remembers 2D coordinates `(x, y, side)` in `chrome.storage.local` key `mascotPosition`.
- **Click to Expand:** Movement under 4px jitter is treated as a tap, toggling the **In-Place Floating Popup Card**.

---

## 3. In-Place Expanded Card: Embedded Popup Iframe (Single Source of Truth)

- **Dimensions:** Width `382px`, Height `592px`, Max Height `calc(100vh - 24px)`.
- **Single Source of Truth:** Embeds the extension's original popup via an isolated iframe:
  ```html
  <iframe class="mascot-popover-iframe" src="popup/popup.html?embedded=1&hostname=..." frameborder="0" scrolling="no"></iframe>
  ```
- **100% Feature Parity:** Provides the exact same controls as the extension popup without duplicate DOM or desynchronized settings:
  - Translation visibility toggle & Re-scan button.
  - Translation Engine (Auto / Local DirectML / Cloud Vision).
  - Searchable Model Combobox with Vision filtering.
  - Aesthetic customizer (Warm Ivory, Sepia, Dark, Pure White; Manga Comic fonts; Opacity slider).
  - Source language selector (`ja`, `ko`, `zh`, `en`, `auto`).
  - Settings View drawer (Domain Whitelist/Blacklist gating, API keys for Gemini, OpenAI, Claude, Custom endpoint, Prefetch, Visual YOLO debug).
- **Dismissal:**
  - Close button in header (posts `INKSHIFT_CLOSE_HUD` via `window.parent.postMessage`).
  - Pressing `Escape` key inside iframe or parent document.
  - Clicking outside the popover card in the parent page.

---

## 4. Live Mascot State Machine (Synchronized with Reader Pipeline)

The mascot visual sprite reflects real-time content orchestrator events:

| Mascot State | Pipeline Trigger | Visual Animation | Sprite SVG |
|---|---|---|---|
| `idle` | Page loaded, overlays rendered | Soft breathing cycle (3.2s loop) + periodic eye blinks | `idle.svg` |
| `reading` | User scrolling, reading content | Holding warm paper manga booklet, subtle head nods | `reading.svg` |
| `scanning` | IntersectionObserver detects new page | Radar visor pulse, looking back and forth | `scanning.svg` |
| `translating` | In-flight AI translation / OCR request | Fast typing on micro-keyboard / thought bubble | `translating.svg` |
| `success` | Translation batch fulfilled | Double-jump celebration, sparkles, returns to `reading` | `success.svg` |
| `error` | HTTP 500, network drop, quota exhausted | Recumbent pose with exclamation badge | `error.svg` |
| `sleeping` | Overlay visibility toggled OFF (`Z` key) | Curled up asleep with floating *Zzz* | `sleeping.svg` |
