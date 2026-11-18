# Spec: Chromium Extension Core & In-Page Overlay (`extension-core`)

> **Module ID:** `extension-core`  
> **Source ADR:** [ADR-005-extension-core-architecture.md](../decisions/ADR-005-extension-core-architecture.md), [ADR-007-yolo11-manga-detection-and-visual-grounding.md](../decisions/ADR-007-yolo11-manga-detection-and-visual-grounding.md), [ADR-008-consolidated-engine-architecture-and-shared-detection.md](../decisions/ADR-008-consolidated-engine-architecture-and-shared-detection.md)  
> **Parent Map:** [CAPABILITY_MAP.md](CAPABILITY_MAP.md)  
> **Contract Spec:** [SPEC-api-contract.md](SPEC-api-contract.md)  
> **Research Foundations:** [RESEARCH-extension-manifest.md](../research/RESEARCH-extension-manifest.md), [RESEARCH-extension-sw-lifecycle.md](../research/RESEARCH-extension-sw-lifecycle.md), [RESEARCH-extension-messaging.md](../research/RESEARCH-extension-messaging.md), [RESEARCH-extension-overlay-dom.md](../research/RESEARCH-extension-overlay-dom.md)  
> **Status:** Approved by Solo Developer (@human)  
> **Phase:** Module 4 Client Interface & Phase 15 Extension Upgrade  
> **Language Policy:** Official English document tracked in Git. Parallel Vietnamese copy at [docs/vi/specs/SPEC-extension-core.md](../vi/specs/SPEC-extension-core.md).

---

## ASSUMPTIONS I'M MAKING:
1. The extension exclusively targets Chromium-based browsers (Chrome, Edge, Brave, Coc Coc) running Manifest V3.
2. The user has the local FastAPI backend engine running on `http://127.0.0.1:8000` (or `http://localhost:8000`).
3. Manga images are identified by DOM dimensions (rendered or natural width/height $\ge 300$px) and aspect ratio checks to eliminate avatars, logos, and advertising banners.
4. The extension builds with Vite and TypeScript producing unpackable output in `dist/`.

---

## 1. Objective

Deliver a high-performance, responsive Chromium Extension (`extension-core`) that provides instant, in-place Vietnamese translation overlays directly onto manga reader web pages without interrupting the user's reading experience.

### Core User Stories:
1. **Full-Auto In-Page Translation:** As a manga reader visiting a site (e.g. MangaDex, Rawkuma), when the page loads, the extension automatically scans manga pages, verifies cache, fetches translations from the local backend, and renders Vietnamese speech bubbles directly over the original Japanese/English text.
2. **100% CSS-Isolated Shadow DOM Overlay:** As a reader on heavily-styled websites, translation text formatting (fonts, padding, line-heights, accents) must never be warped or broken by host website stylesheets, and extension styles must never break the host site layout.
3. **Drift-Free Geometry Scaling:** When the browser window resizes, or when images utilize `object-fit: contain` with letterboxing, speech bubble positions scale synchronously without offset drift.
4. **Visual Progress & Status Feedback:** Each manga page displays a subtle corner status pill (🟡 processing, 🟢 translated, 🔴 error), and the extension toolbar icon displays a live badge count of translated pages (e.g., `"3/12"`).
5. **Dynamic Control Popup:** A clean popup panel allowing the user to view backend connection health, select the active translation engine (`auto`, `local`, `cloud`), dynamically select provider (`gemini`, `openai`) or translator (`google-free`, `llm-text`), toggle overlay opacity, and manually trigger a re-scan.

---

## 2. Tech Stack & Commands

### 2.1 Dependencies
- **Extension Platform:** Chromium Manifest V3 (Chrome 120+)
- **Language:** TypeScript 5.3+ (`strict: true`)
- **Bundler / Build Tool:** `vite >= 5.1.0`
- **Testing:** `vitest >= 1.3.0` + `happy-dom` (DOM simulation)
- **Styling:** Vanilla CSS via Constructable Stylesheets (`CSSStyleSheet` & `adoptedStyleSheets`)
- **Lint & Format:** Project standard (TypeScript compiler `tsc --noEmit`, biome / eslint)

### 2.2 Commands
```bash
# Build production unpackable extension to dist/
npm run build:extension

# Start Vite watch mode for development
npm run dev:extension

# Run extension unit and contract tests
npm run test:extension

# Run extension tests with code coverage (Target: >= 80% on new lines per CONSTRAINTS.md)
npm run test:extension -- --coverage

# Typecheck extension code (Zero type errors)
npm run typecheck:extension
```

---

## 3. Project Structure

```
src/extension/
├── manifest.json                  # Manifest V3 configuration
├── background/
│   ├── service_worker.ts          # Top-level event listener & coordinator
│   ├── cors_fetcher.ts            # Privileged fetch(), Web Crypto SHA-256, Base64 encoder
│   ├── backend_gateway.ts         # HTTP client calling FastAPI with bounded retry (/health, /cache, /translate)
│   └── navigation_tracker.ts      # chrome.webNavigation SPA route change listener
├── content/
│   ├── content_script.ts          # Top-level DOM scanner & lifecycle orchestrator
│   ├── dom_scanner.ts             # Image filtering (size >= 300px, naturalWidth > 0, decode() readiness)
│   ├── geometry.ts                # computeRenderedImageRect & [0, 1000] pixel scaling math
│   ├── overlay_manager.ts         # Shadow DOM host creation, styling, teardownAll(), and bubble mounting
│   ├── font_fitter.ts             # Binary search font-size fitting for speech bubbles
│   └── observers.ts               # ResizeObserver & MutationObserver drift guards
├── popup/
│   ├── popup.html                 # Minimal clean settings popup
│   ├── popup.ts                   # Popup controller (health check, engine picker, debug overlay toggle, storage sync)
│   └── popup.css                  # Popup theme styles (InkShift dark/light aesthetic)
└── shared/
    ├── storage.ts                 # chrome.storage.local typed helper wrapper
    └── badge.ts                   # chrome.action.setBadgeText & setBadgeBackgroundColor wrapper

tests/extension/
├── test_cors_fetcher.test.ts          # Tests for binary fetching, Base64 conversion, SHA-256
├── test_geometry.test.ts              # Tests for letterbox math, object-fit: contain/cover scaling
├── test_dom_scanner.test.ts           # Tests for filtering manga images, complete & decode() guards
├── test_font_fitter.test.ts           # Tests for binary search font sizing with Vietnamese accents
├── test_overlay_manager.test.ts       # Tests for Shadow DOM creation, teardownAll(), debug overlay, XSS safety
├── test_backend_gateway.test.ts       # Tests for API client error handling, bounded retry, and fallback behavior
├── test_content_orchestrator.test.ts  # Tests for top-level content script pipeline coordination
└── test_observers.test.ts             # Tests for ResizeObserver and MutationObserver lifecycle
```

---

## 4. Code Style & Architecture Boundaries

### 4.1 Strict Typing & IPC Contracts
All messages between Content Script, Service Worker, and Popup adhere strictly to typed interfaces with correlation `traceId`:

```typescript
// src/extension/shared/ipc_types.ts
import type { TranslationResponse, TranslatedBlock, APIErrorDetail } from '../../types/contract';

export interface TranslateImagePayload {
  traceId: string;
  imageIndex: number;
  imageUrl: string;
  clientWidth: number;
  clientHeight: number;
}

export type IPCMessage =
  | { type: 'CHECK_BACKEND_HEALTH'; traceId?: string }
  | { type: 'TRANSLATE_IMAGE'; payload: TranslateImagePayload }
  | { type: 'SPA_NAVIGATION_DETECTED'; payload: { url: string } }
  | { type: 'UPDATE_TAB_BADGE'; payload: { translated: number; total: number } };

export type IPCResponse<T = unknown> =
  | { success: true; traceId?: string; data: T }
  | { success: false; traceId?: string; error: APIErrorDetail };
```

### 4.2 Concurrency Policy: Direct Dispatch (No Queue / No Throttling)
Per human architectural decision (DDD-M4-001):
- The extension does **NOT** enforce artificial request queuing or concurrency semaphores.
- All detected manga images are dispatched directly to the backend concurrently to minimize total reading latency.
- Transient errors (`429`, `503`, network drops) are handled via bounded exponential backoff in `backend_gateway.ts` (max 2 retries, 10s max ceiling). Non-retryable errors fail immediately without retrying.

### 4.3 Zero HTML Injection Policy (XSS Defense) & Diagnostic Overlays
Untrusted text returned by AI models must **never** be rendered using `innerHTML`:

```typescript
// GOOD: Safe against malicious injection & format corruption
export function createSpeechBubble(block: TranslatedBlock, rect: BoundingBoxPixels): HTMLElement {
  const bubble = document.createElement('div');
  bubble.className = 'inkshift-speech-bubble';
  bubble.style.top = `${rect.top}px`;
  bubble.style.left = `${rect.left}px`;
  bubble.style.width = `${rect.width}px`;
  bubble.style.height = `${rect.height}px`;

### 4.3 Two-Layer Speech Bubble Mounting (`src/extension/content/overlay_manager.ts`)
To eliminate the **Text Wrapping Hazard** (where CSS clips text inside irregular non-rectangular containers) and protect background artwork:

```html
<!-- Speech Bubble Overlay Container (Positioned via [ymin, xmin, ymax, xmax]) -->
<div class="inkshift-speech-bubble" style="top: ...px; left: ...px; width: ...px; height: ...px;">
  
  <!-- Layer 1: Background Mask (Curved Polygon) -->
  <div class="inkshift-mask-layer" 
       style="clip-path: polygon(15.2% 5.1%, 50.0% 2.0%, 85.4% 6.2%, ...);
              background-color: #ffffff;
              position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;">
  </div>

  <!-- Layer 2: Text Layout Box (Inner Safe-Zone / Child Text Box) -->
  <div class="inkshift-text-layer"
       style="position: absolute; inset: 10% 12%; display: flex; align-items: center; justify-content: center; pointer-events: auto;">
    <p class="inkshift-translated-text">Translated dialogue here</p>
  </div>
  
</div>
```

- When `block.polygon` is provided: Layer 1 receives CSS `clip-path: polygon(...)` using relative % vertices.
- When `block.polygon` is absent (fallback): Layer 1 falls back to standard rounded rect (`border-radius: 4px`).
- **MUST use textContent exclusively** per `CONSTRAINTS.md` and `SPEC-api-contract.md` (zero `innerHTML` for XSS defense).

Status pill elements store error diagnostics for quick inspection:
- `data-error-code`: e.g. `"RATE_LIMITED"`, `"NETWORK_ERROR"`, `"UNPROCESSABLE_ENTITY"`.
- `title`: Tooltip describing failure detail directly on hover, preventing silent error swallowing.

When `debugGeometry` is enabled in `chrome.storage.local`:
- Overlay manager renders intermediate diagnostic outlines inside the Shadow DOM:
  - Blue outline: Computed inner rendered image rect (`computeRenderedImageRect`).
  - Yellow outline: Normalized raw AI coordinate box scaled to pixels.
  - Green outline: Decoded polygon contour vertices.
  - Red outline: Final mounted speech bubble.

### 4.4 Typography & Word Wrap Rules
Vietnamese text rendering must follow typography constraints:
```css
.inkshift-speech-bubble {
  all: initial;
  position: absolute;
  box-sizing: border-box;
  pointer-events: none;
  overflow: visible;
}

.inkshift-mask-layer {
  all: initial;
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.18);
  transition: opacity 0.15s ease;
}

.inkshift-text-layer {
  all: initial;
  position: absolute;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  text-wrap: balance;
  word-break: keep-all;
  overflow-wrap: break-word;
  hyphens: none;
  line-height: 1.25;
  font-family: var(--inkshift-font-family, 'CC Wild Words', 'Comic Neue', sans-serif);
  color: #000000;
  pointer-events: auto;
  user-select: text;
}
```

### 4.5. Manga Typography Engine & Smart Bubble Typography Fitter v2

1. **Local Manga Fonts (`src/extension/assets/fonts/`):**
   - Packaged offline as `.woff2` and declared in `manifest.json` `web_accessible_resources`:
     - `'cc-wild-words'`: Classical scanlation dialogue (Default).
     - `'comic-neue'`: Clean, modern, highly legible comic font.
     - `'bangers'`: High-impact dramatic action & shouting font.
     - `'patrick-hand'`: Natural handwritten font for thoughts/whispers.
     - `'system-ui'`: Fallback clean sans-serif.
   - Storage setting: `speechBubbleFont` in `chrome.storage.local`.

2. **Smart Bubble Typography Fitter v2 Formulas:**
   - **Dynamic Upper Bound:**
     $$\text{maxFontSize} = \min\left(\max\left(24, \lfloor H \times 0.65 \rfloor\right), 80\right)$$
   - **Dynamic Lower Bound & Adaptive Micro-Padding:**
     $$\text{minFontSize} = \begin{cases} 7.5\text{px} & \text{if } H < 28\text{px} \lor W < 35\text{px} \\ 10\text{px} & \text{otherwise} \end{cases}$$
     $$\text{padding} = \begin{cases} 1\text{px } 2\text{px} & \text{if } H < 30\text{px} \lor W < 40\text{px} \\ 4\text{px } 6\text{px} & \text{otherwise} \end{cases}$$
   - **Diamond / Oval Shape Line Balancing:**
     - Uses native CSS `text-wrap: balance`.
     - When aspect ratio $W / H \ge 1.3$ and $\text{wordCount} \ge 4$, wrap text within `max-width: 82%` to distribute sentences into an oval/diamond contour matching speech balloon geometry.
   - **Shouting / Impact Scale:**
     - When $\text{wordCount} \le 3$ and bubble area $W \times H \ge 10,000\text{px}^2$, apply `font-weight: 800` (Bold) to fill 50–70% of balloon height.

---

## 5. Testing Strategy

1. **Unit Testing (`vitest` + `happy-dom`):**
   - Geometry math: Verify `computeRenderedImageRect` accurately calculates letterbox offsets for arbitrary aspect ratios.
   - Font fitting: Verify `fitFontSize` converges within 6 iterations and never allows `scrollHeight > clientHeight`.
   - Image filter: Verify `isMangaImage` accepts $\ge 300$px manga art and rejects $48 \times 48$ avatars or $728 \times 90$ banners.
   - Hashing & Base64: Verify `uint8ArrayToBase64` and SHA-256 computation produce correct digests matching Golden fixtures.
2. **Mock Chrome API Layer:**
   - Provide clean mocks for `chrome.runtime.sendMessage`, `chrome.storage.local`, `chrome.action.setBadgeText`, and `chrome.webNavigation`.
3. **Contract Test Verification:**
   - Verify that data returned by `backend_gateway.ts` strictly satisfies `TranslationResponse` from `src/types/contract.ts`.

---

## 6. Boundaries

- **Always:**
  - Attach a deterministic `traceId` to every IPC message across Content Script ↔ Service Worker boundaries.
  - Render speech bubbles with `element.textContent` (zero `innerHTML`).
  - Use `computeRenderedImageRect` for all bounding box transformations.
  - Return `true` synchronously in `chrome.runtime.onMessage` listeners handling async promises.
  - Set `:host { all: initial }` on Shadow Roots to prevent CSS contamination.
  - Scope extension badges using `tabId`.
  - Check `img.complete` and `img.naturalWidth > 0` before geometry computation; await `img.decode()` if loading.
  - Teardown orphan overlays via `teardownAll()` upon SPA navigation or tracked image removal.
  - Expose diagnostic error metadata on status pills via `data-error-code` and `title` tooltip.
- **Ask First:**
  - Introducing any third-party UI framework (Preact, React, Svelte, Tailwind).
  - Adding permissions to `manifest.json` beyond `storage` and `webNavigation`.
  - Modifying the shared `src/types/contract.ts` schema.
  - Introducing request throttling or concurrency limiting queues (human approval mandatory).
- **Never:**
  - Commit `@ts-ignore`, `@ts-expect-error`, or `eslint-disable` suppressions.
  - Call `img.attachShadow()` directly on an `HTMLImageElement`.
  - Execute `fetch()` directly in the Content Script for cross-origin manga images.
  - Use `setInterval` polling loops for DOM change tracking.
  - Silently swallow API errors in overlay status pills without developer/user diagnostic hints.

---

## 7. Success Criteria

- [ ] **SC-1 (Type Safety & Floor Guard):** `tsc --noEmit` compiles with zero errors; Floor Guard confirms zero suppressions.
- [ ] **SC-2 (Test Coverage):** Extension unit test suite passes with $\ge 80\%$ line coverage on new files.
- [ ] **SC-3 (CORS Bypass & Image Processing):** Service Worker successfully fetches cross-origin images, calculates SHA-256, and converts to Base64 without DOM dependencies.
- [ ] **SC-4 (Isolated Shadow DOM & Diagnostics):** Overlay renders in a Shadow Root with `adoptedStyleSheets` and `:host { all: initial }` with zero styling leaks. Status pills display error codes on failure. Visual geometry debug mode renders alignment outlines.
- [ ] **SC-5 (Geometry & Drift Resilience):** Normalized `[0, 1000]` boxes scale correctly onto letterboxed `object-fit: contain` images without offset drift. Lazy-loaded images wait for `img.complete` and `decode()`.
- [ ] **SC-6 (Reactivity & SPA Navigation):** Infinite scroll lazy-loads and chapter transitions via `webNavigation` are automatically detected, orphan overlays are cleanly torn down via `teardownAll()`, and translations trigger without manual refresh.
- [ ] **SC-7 (Minimal Popup Controller):** Popup UI displays live backend status, active engine switch, debug overlay toggle, and opacity toggle persisting to `chrome.storage.local`.
- [ ] **SC-8 (IPC Correlation & Error Recovery):** IPC messages carry `traceId` correlation across boundaries; transient failures (`429`, `503`, network drops) execute bounded exponential retry in `backend_gateway.ts`.
- [ ] **SC-9 (Content Orchestration Verification):** Top-level `content_script.ts` workflow verified with comprehensive pipeline test `test_content_orchestrator.test.ts`.
- [ ] **SC-10 (Manga Typography & Adaptive Fitting):** Extension supports 4 offline comic fonts + system-ui; user font choice persists in storage and applies to all speech balloons. Large shouting balloons scale dynamically to fill $\ge 50\%$ height without being capped at 22px; wide oval balloons balance text lines without single-line stretching; micro-bubbles fit short text without letter clipping.

---

## 8. Open Questions

*(All primary requirements have been clarified and decided during previous design sessions and Doubt Cycle DDD-M4-001. No blocking open questions remain).*
