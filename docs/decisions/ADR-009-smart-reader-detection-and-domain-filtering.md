# ADR-009: Smart Reader Detection Heuristics and Unified Domain Filtering

- **Status:** Accepted
- **Date:** 2026-10-21
- **Decision-Maker:** Solo Developer (@human)
- **Consulted:** Antigravity AI Agent
- **Related Spec / Feature:** Feature F1 (`docs/temp/smart-reading-pipeline/FEATURE-smart-reader-detection.md`)
- **Research Source:** [RESEARCH-smart-reader-detection.md](../research/RESEARCH-smart-reader-detection.md)

---

## 1. Context & Problem Statement

In previous phases, `manifest.json` declared `"matches": ["<all_urls>"]`, and `content_script.ts` triggered `scanAndTranslate()` indiscriminately on every webpage visited. The sole filter in `dom_scanner.ts` evaluated only individual image pixel dimensions ($\ge 300\text{px}$) and basic ad class name regexes.

Consequently:
1. Cover images and listing thumbnails on manga catalog pages (e.g. `/manga/one-piece`, `/the-loai/`) passed the filter and were dispatched for translation.
2. Large banners, hero illustrations, product pictures on mainstream websites (news, e-commerce, dev portals) triggered unnecessary translation calls, consuming GPU/API tokens and disrupting normal web browsing.
3. Minimalist, modern single-page and webtoon readers with dynamic/SPA routing or hidden toolbars were vulnerable to false negatives when using simple regex or static navigation button selectors.

We require a deterministic, low-latency ($<3\text{ms}$) reader detection and domain-filtering engine that runs in the content script before any image scanning or IPC translation begins.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option 1: Pure URL Regex Matching** | - Near zero execution time ($<0.1\text{ms}$).<br>- Trivial implementation. | - Fails on UUID routes (MangaDex), numeric routes, or SPA hash routes.<br>- Causes false positives on catalog paths like `/chapter-list/`.<br>- Accuracy only ~65%. | Rejected |
| **Option 2: 3-Layer Draft Heuristic (URL + Buttons + Image Parent)** | - Better than pure regex.<br>- Distinguishes some covers. | - Fails on modern minimalist readers where buttons are hidden until tap.<br>- Breaks on single-page readers where images are wrapped in `<a>` tags.<br>- Completely misses SPA navigation without `pushState` hooks. | Superseded by Research |
| **Option 3: Profile-Assisted Heuristic Engine (PAHE) with Unified Domain Filter** | - **Tier 0:** Unified Whitelist/Blacklist with pre-seeded popular sites ($<0.05\text{ms}$ fast skip).<br>- **Tier 1:** Fast-path CMS profiles (WP-Manga, NetTruyen, MangaDex, Webtoons) covering ~80% traffic at 100% precision.<br>- **Tier 2:** Dimension clustering ($CV_w < 0.15$) for long-strip readers.<br>- **Tier 3:** Viewport prominence ($\ge 45\%$) & centrality for single-page readers.<br>- **Tier 4:** SPA `history.pushState` & mutation observers.<br>- Zero external dependencies, $<3\text{ms}$ latency. | - Requires modular code structure in `reader_detector.ts`.<br>- Requires Popup UI extension for domain management. | **Accepted (Recommended)** |

---

## 3. Decision & Rationale

The developer approved **Option 3: Profile-Assisted Heuristic Engine (PAHE) with Unified Domain Filtering**:

1. **Unified Blacklist / Whitelist (Tier 0):**
   - A single unified `blacklist: string[]` stored in `chrome.storage.local`.
   - Pre-seeded upon install with top non-manga web domains (search engines, social media, e-commerce, news, tech tools) ensuring mainstream web browsing triggers an instantaneous ($<0.05\text{ms}$) sleep state with zero DOM queries.
   - Users can freely add any domain to the Blacklist or Whitelist, or remove any pre-seeded domain (e.g. to translate comics on Reddit or Twitter), with a single-click "Restore Defaults" button.
2. **Fast-Path Profile Matching (Tier 1):**
   - High-confidence CSS selectors for dominant CMS engines (Madara `.reading-content`, NetTruyen `.reading-detail`, MangaDex `#reader`, Webtoons `#_imageList`).
   - Scopes downstream image extraction strictly to the reader container, eliminating 100% of surrounding promotional thumbnails and sidebar cards.
3. **Statistical Dimension Clustering & Viewport Geometry (Tier 2 & 3):**
   - Long-strip readers on unknown sites are identified by uniform image widths (Coefficient of Variation $CV_w \le 0.15$ for $N \ge 3$ images).
   - Single-page readers are identified by viewport area prominence ($VCR \ge 0.45$) and horizontal centering ($\Delta_{\text{center}} \le 80\text{px}$).
4. **SPA Navigation Hook (Tier 4):**
   - Monkey-patching `history.pushState` / `replaceState` and listening to `popstate` ensuring dynamic client-side transitions seamlessly trigger detection and cleanup.

---

## 4. Consequences

- **Positive Impact:**
  - Zero unwanted translation calls during regular web browsing.
  - Automatic, accurate reader detection across both infinite vertical scrolls and single-page flip readers.
  - Transparent user control: instant override from the extension popup.
  - Supplies reliable `chapterMeta` (series slug, chapter number, source domain) required by subsequent features (F2 Context Graph & F3 Prefetch).
- **Trade-offs / Negatives:**
  - Content script adds ~200-300 lines of modular TypeScript logic in `reader_detector.ts`.
  - Popup UI requires expandable/clean controls for managing domain lists.
- **Follow-up Tasks:**
  - Create `src/extension/content/reader_detector.ts`.
  - Update `src/extension/content/content_script.ts` to gate translation on `detectReaderContext()`.
  - Update `src/extension/popup/` HTML, CSS, and TS to support domain toggles and list management.
  - Implement comprehensive unit test suites in `tests/extension/test_reader_detector.test.ts`.

---

## 5. Live Browser Hardening & Edge-Case Addendum (Post-Verification)

During live browser testing on MangaDex (`mangadex.org`), critical real-world edge cases were discovered and resolved:

1. **Top-Frame IPC Isolation (`manifest.json` & `popup.ts`):**
   - MangaDex embeds third-party iframes (e.g. Google reCAPTCHA). Content scripts running with `all_frames: true` caused the reCAPTCHA iframe to execute and reply to `GET_PAGE_READER_STATUS` first with `domainStatus: 'blacklisted'` (due to `google.com`), poisoning popup badges.
   - *Fix:* Set `"all_frames": false` in `manifest.json`, gate `content_script.ts` with `window.self === window.top`, and target popup IPC strictly via `{ frameId: 0 }`.
2. **Strict Profile URL Enforcement & Homepage Guards:**
   - On SPA homepages (`mangadex.org/`), generic container selectors (e.g. pagination or cards) and uniform cover widths caused false-positive reader detection, triggering OCR on dozens of catalog covers.
   - *Fix:* Tier 1 profiles strictly require `urlPattern` match before evaluating container selectors. Added an absolute homepage guard (`pathname === '/'`) and multi-column grid rejection in Tier 2 heuristic clustering.
3. **Empty Container Fallback:**
   - Selecting a reader container that has zero images (e.g. a navbar matching broad reader classes) permanently blinded the scanner.
   - *Fix:* Only select containers with `imageCount > 0`. If `findMangaImages(container)` yields 0 images on a confirmed reader page, automatically fall back to scanning `document.body`.
4. **Catalog Cover Thumbnail Exclusion:**
   - Manga catalog covers (`/covers/` paths, `manga-cover` classes) are explicitly rejected in `isMangaImage()` to protect against accidental translation on title detail pages.

