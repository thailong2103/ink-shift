# ADR-005: Chrome Extension MV3 Architecture, Shadow DOM Overlay, and Image Acquisition Pipeline

- **Status:** Accepted
- **Date:** 2026-10-12
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent
- **Target Module:** `extension-core` (Module 4 User Interface & Client Experience)

---

## 1. Context & Problem Statement

Module 4 (`extension-core`) provides the direct user-facing experience of InkShift: an in-browser manga reader extension that translates manga pages directly on the webpage without disrupting the user's natural reading flow or navigating away.

Building this on modern Chromium presents technical constraints and browser boundaries:
1. **Manifest V3 Runtime Constraints:** Background execution is restricted to ephemeral Service Workers with a 30-second idle termination limit and no access to DOM APIs or `<canvas>`.
2. **Same-Origin Policy & Cross-Origin Images:** Manga websites host reading images on third-party CDNs. Content scripts attempting to fetch images directly fail with CORS errors, and drawing images to a `<canvas>` causes canvas tainting (`SecurityError`).
3. **DOM Encapsulation & Styling Conflicts:** Manga reader websites employ complex, aggressive CSS rules (`!important`, global typography, dark themes, flex/grid layouts). The translation overlay must be 100% immune to host page CSS bleeding and must never affect host styling.
4. **Coordinate Precision & Responsive Layout Shifts:** Manga sites frequently use responsive containers with `object-fit: contain` (creating letterboxing). Bounding boxes normalized to `[0, 1000]` must map to real pixels with zero coordinate drift across window resize, lazy-loading, and dynamic ads.
5. **Single-Page Application (SPA) Reader Navigation:** Modern portals (e.g. MangaDex) navigate chapters/pages via `history.pushState()` without full page reloads.

---

## 2. Options Considered & Architectural Decisions

### A. Extension Architecture & Process Separation
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1A: Service Worker Gateway + Content Script Overlay (Selected)** | - Service Worker handles privileged networking (`fetch` to CDN & FastAPI backend with `host_permissions`).<br>- Content Script focuses strictly on DOM scanning and Shadow DOM overlay rendering.<br>- Clean separation of concerns. | - Requires structured IPC messaging across context boundaries. | **Selected (Agent & Human Approved)** |
| **Option 1B: Fat Content Script (Direct Backend Fetch from Page)** | - Fewer IPC messages. | - Fails on cross-origin image CDNs due to CORS restrictions in the webpage context.<br>- Cannot bypass CDN protections. | Rejected |

---

### B. DOM Isolation & Overlay Injection Strategy
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 2A: Dedicated Host Element with Shadow DOM v1 & `adoptedStyleSheets` (Selected)** | - 100% CSS encapsulation via `:host { all: initial }`.<br>- Host site styles cannot alter translation text, line-height, or font sizes.<br>- Extension styling cannot break host site layout.<br>- Reuses a single `CSSStyleSheet` instance across all page overlays for minimal memory footprint. | - Cannot attach Shadow Root directly to `<img>` (throws `NotSupportedError` on replaced elements); requires a sibling/parent host container. | **Selected (Agent & Human Approved)** |
| **Option 2B: Pure Inline CSS on Standard `<div>` Elements** | - No Shadow DOM required. | - Extremely fragile; host site `!important` rules, CSS resets, and global font rules inevitably bleed through and corrupt text layout. | Rejected |
| **Option 2C: Full-Page `<iframe>` Overlay** | - Complete isolation. | - Heavyweight; blocks user clicks on the underlying webpage; synchronization with scrolling is laggy and produces visual jitter. | Rejected |

---

### C. Image Acquisition, CORS Bypass & Encoding Pipeline
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 3A: Service Worker Fetch Proxy + Native Base64 / Web Crypto (Selected)** | - Content script passes image URL to Service Worker.<br>- Service Worker fetches image via `fetch()` leveraging `host_permissions: ["<all_urls>"]` (bypassing CORS completely).<br>- Computes SHA-256 via native `crypto.subtle.digest()`.<br>- Checks backend cache (`GET /api/v1/cache/{hash}`).<br>- On cache miss, encodes to Base64 using native `Uint8Array.prototype.toBase64` (with chunked fallback) and posts to FastAPI. | - Image bytes travel through extension IPC once on cache misses. | **Selected (Agent & Human Approved)** |
| **Option 3B: Content Script Canvas Extraction (`toDataURL`)** | - Avoids network fetch if image is cached in browser memory. | - Crashes on cross-origin images due to Canvas Tainting (`SecurityError`).<br>- Fails on $>80\%$ of actual manga reader sites. | Rejected |
| **Option 3C: `chrome.offscreen` Document** | - Provides full DOM/Canvas environment in background. | - Unnecessary overhead and complexity since native `Uint8Array` Base64 and `crypto.subtle` run directly in the Service Worker without DOM. | Rejected |

---

### D. Geometry Scaling & Letterbox Mitigation
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 4A: Aspect-Ratio Letterbox Math via `computeRenderedImageRect` (Selected)** | - Compares image aspect ratio (`naturalWidth / naturalHeight`) with container aspect ratio (`clientWidth / clientHeight`).<br>- Calculates the exact pixel boundaries of the rendered artwork inside `object-fit: contain`.<br>- Maps normalized `[0, 1000]` coordinates with zero offset error. | - Requires `naturalWidth` and `naturalHeight` to be loaded before computation. | **Selected (Agent & Human Approved)** |
| **Option 4B: Naive `getBoundingClientRect()` Scaling** | - Simplest multiplication: `(box / 1000) * rect.width`. | - Severely drifts when images are letterboxed or pillarboxed (common on wide monitors and mobile reader modes). | Rejected |

---

### E. Navigation Tracking & DOM Reactivity
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 5A: Dual Hybrid Observer (`MutationObserver` + `webNavigation`) (Selected)** | - `MutationObserver` detects lazy-loaded images, swapped `src` attributes, and infinite scroll additions.<br>- `chrome.webNavigation.onHistoryStateUpdated` in the Service Worker catches SPA chapter/page transitions.<br>- `ResizeObserver` recalculates overlay positions on layout shift or window resize. | - Must debounce re-scans ($\ge 300$ ms) to prevent event thrashing. | **Selected (Agent & Human Approved)** |
| **Option 5B: Polling Interval (`setInterval`)** | - Simple to implement. | - Wastes CPU cycles, drains laptop battery, causes sluggish UI. | Rejected |

---

### F. Toolchain, UI Framework & Styling
| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 6A: TypeScript + Vite + Vanilla CSS / HTML (Selected)** | - Vite provides fast HMR and optimized Chromium extension packaging.<br>- TypeScript provides 100% type safety sharing contracts from `src/types/contract.ts`.<br>- Vanilla CSS for overlay and popup ensures minimal bundle size ($<150$ KB total), zero runtime overhead, and strict CSP compliance. | - No heavy component framework for popup UI (acceptable since popup is minimal). | **Selected (Agent & Human Approved)** |
| **Option 6B: React / Tailwind Bundle** | - Component declarative UI. | - Large bundle footprint ($>500$ KB), complex Tailwind build step for Shadow DOM styling, slower popup launch. | Rejected |

---

## 3. Decision Outcome

1. **Manifest V3 Core:** Build `extension-core` with TypeScript and Vite. Use a background Service Worker as the privileged network gateway and content scripts for in-page DOM operations.
2. **CORS Bypass:** Service Worker fetches images directly with `host_permissions: ["<all_urls>"]`. Content scripts never attempt to draw cross-origin images to canvas.
3. **Shadow DOM Encapsulation:** Inject `<div class="ink-shift-overlay-host">` over each target `<img>`. Isolate all styling via `:host { all: initial }` and shared `adoptedStyleSheets`.
4. **Letterbox Geometry:** Implement `computeRenderedImageRect(img)` to accurately scale `[0, 1000]` coordinates for `object-fit: contain`.
5. **Reactivity:** Coordinate `ResizeObserver`, `MutationObserver`, and `webNavigation.onHistoryStateUpdated` for seamless scrolling and chapter transitions.
6. **Popup UI:** Minimal native HTML/CSS popup supporting backend status display, active engine selection, opacity toggle, and translation progress badges.

---

## 4. Consequences & Constraints Compliance

- **CONSTRAINTS.md:**
  - Zero suppression comments (`@ts-ignore`, `eslint-disable`).
  - Zero type errors (`tsc --noEmit`).
  - Unit and contract test coverage $\ge 80\%$ via `vitest`.
- **Security:**
  - Zero `innerHTML` usage for translation rendering; all text nodes use `textContent` to prevent XSS.
  - Zero inline scripts in popup HTML (compliant with strict MV3 CSP).
- **Performance:**
  - Coordinate scaling and font-fitting execute in $<16$ ms per page, maintaining 60 FPS scrolling.

---

## 5. Addendum: Debuggability & Robustness Refinements (Doubt Cycle DDD-M4-001)

Following Cross-Model Doubt-Driven Development audit (DDD-M4-001), the following architectural decisions are codified:

### A. Concurrency Dispatch: Direct Processing (No Request Queue / No Concurrency Limiter)
- **Decision:** The extension dispatches all detected manga image requests concurrently without artificial client-side queuing or concurrency semaphores.
- **Alternatives Considered:**
  - *Option: Service Worker Async Semaphore Queue (maxConcurrent = 3):* Rejected per human decision. Avoids client-side bottlenecking, unnecessary queuing state in ephemeral Service Workers, and latency overhead on high-bandwidth connections.
  - *Option: Direct Concurrent Dispatch (Selected):* Content script sends `TRANSLATE_IMAGE` for detected images immediately. Backend and upstream vision models handle concurrency natively; extension relies on bounded backoff for transient rate limits.

### B. IPC Message Correlation (`traceId`)
- **Decision:** Every IPC message payload across Content Script ↔ Service Worker carries a mandatory `traceId: string` and `imageIndex: number`. Responses echo the `traceId`.
- **Rationale:** Ensures deterministic request-to-image matching, prevents cross-talk if multiplexed channels are used, and provides unified end-to-end logging across browser DevTools and backend logs.

### C. Visual Geometry Debug Overlay
- **Decision:** Provide a `debugGeometry: boolean` toggle in `chrome.storage.local` (switchable via Popup). When enabled, `overlay_manager.ts` renders colored diagnostic bounding boxes inside the Shadow DOM:
  - Blue: Inner rendered image rect (`computeRenderedImageRect`).
  - Yellow: Raw normalized `[0, 1000]` box scaled to pixels.
  - Red: Final mounted speech bubble.
- **Rationale:** Separates vision detection coordinate anomalies from CSS scaling or container letterbox bugs without DevTools trial-and-error.

### D. Error Diagnostics on In-Page Status Pills
- **Decision:** Overlay status pills store error metadata as `data-error-code` attributes and render human-readable error reasons in a native `title` tooltip on hover/click.
- **Rationale:** Eliminates silent error swallowing and avoids forcing developers and users to open background DevTools panels for routine errors.

### E. Lazy-Loaded Image Readiness Guards
- **Decision:** `dom_scanner.ts` checks `img.complete === true && img.naturalWidth > 0`. If false, it awaits `img.decode()` and one-shot `load` listener before initiating geometry calculations.
- **Rationale:** Prevents `Infinity`/`NaN` calculations from unrendered or placeholder images.

### F. SPA Overlay Teardown Lifecycle
- **Decision:** `overlay_manager.ts` implements `teardownAll()`. `navigation_tracker.ts` calls `teardownAll()` prior to re-scanning upon `historyStateUpdated` events. `MutationObserver` also removes overlay hosts when associated `<img>` nodes are removed from the DOM.
- **Rationale:** Eliminates ghost overlays and memory leaks across chapter transitions on SPA manga readers.

### G. Transient Error Recovery & Bounded Retry
- **Decision:** `backend_gateway.ts` implements bounded exponential backoff retry (max 2 retries, 10s maximum wait ceiling) for retryable status codes (`429`, `503`, `504`, network timeouts). Status pill remains yellow (processing) during retry attempts. Non-retryable errors fail immediately.

### H. Content Script Orchestrator Testing
- **Decision:** Formalize `content_script.ts` pipeline orchestration with explicit acceptance criteria and automated integration tests in `tests/extension/test_content_orchestrator.test.ts`.
