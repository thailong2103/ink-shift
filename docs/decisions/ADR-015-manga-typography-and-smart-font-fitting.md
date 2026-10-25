# ADR-015: Manga Typography, Font Switching, and Smart Bubble Typography Fitter v2

- **Status:** Accepted
- **Date:** 2026-10-24
- **Decision-Maker:** Solo Developer (human)
- **Consulted:** AI Agent

---

## 1. Context & Problem Statement

InkShift's in-page translation overlay currently renders translated text using default system sans-serif fonts (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto...`), which feel sterile and lack the visual aesthetics of authentic manga/comic scanlation. Furthermore, the existing font fitting algorithm in `src/extension/content/font_fitter.ts` exhibits three prominent typesetting defects:

1. **Hardcoded Upper Cap (`maxFontSize: 22px`):** Large dramatic or shouting bubbles (e.g. $250\text{px} \times 350\text{px}$) contain a tiny 22px text cluster floating in the center, failing to express dramatic shouting scale.
2. **Hardcoded Lower Floor (`minFontSize: 10px`) & Static Padding (`4px 6px`):** Micro-bubbles (e.g. whispers or marginal notes measuring $25\text{px} \times 20\text{px}$) have usable width reduced to $13\text{px}$. Short words fail to fit, forcing text to clip and slice off diacritics and letters.
3. **Absence of Paragraph Shape Balancing:** In oval or horizontally wide bubbles, short multi-word sentences (5–7 words) stretch across the bubble as a single flat horizontal line because `scrollWidth <= clientW` and `scrollHeight <= clientH` are technically met. The top and bottom 80px remain vacant instead of wrapping into a classical manga diamond/oval paragraph contour.
4. **No User Font Choice:** Users cannot customize their preferred manga reading font from the extension popup.

---

## 2. Options Considered

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| **Option A: Local Bundled Manga Fonts (`.woff2`) + Smart Bubble Typography Fitter v2** | - Authentic Japanese manga scanlation aesthetic with full Vietnamese UTF-8 diacritics.<br>- 100% offline; zero external network requests, immune to CDN blocking or CSP restrictions.<br>- Dynamic bounds (8px–80px) and native `text-wrap: balance` fix all 3 sizing defects. | - Adds $\approx 150\text{KB} - 250\text{KB}$ of compressed `.woff2` font files to extension package. | **(Accepted)** |
| **Option B: Remote Google Fonts via CDN Runtime Loading** | - Smaller extension package size. | - Fails offline or under strict website Content Security Policies (CSP).<br>- Noticeable font layout shift (FOUT) while loading CDN fonts. | Rejected |
| **Option C: Algorithm-Only Optimization (Keep System Fonts)** | - Zero asset overhead. | - Text still looks like a generic web page; completely lacks manga typesetting identity. | Rejected |

---

## 3. Decision & Rationale

We adopt **Option A**:

### 3.1. Manga Font Strategy & Storage Schema
Bundle high-quality, open-source/permissive comic fonts with complete Vietnamese diacritic coverage locally under `src/extension/assets/fonts/`:
1. **`cc-wild-words` (Default Manga Dialogue):** Classic scanlation dialogue font. Clean, slightly italicized, perfectly proportioned for speech balloons.
2. **`comic-neue` (Modern Comic):** Refined, elegant, highly legible comic font for web reading.
3. **`bangers` (Action / Shouting):** Heavy, dramatic uppercase comic font for high-impact battle/shouting scenes.
4. **`patrick-hand` (Handwritten / Monologue):** Organic handwritten font for thoughts, whispers, and slice-of-life narratives.
5. **`system-ui` (System Sans-Serif):** Clean fallback for users who prefer standard typography.

Add `speechBubbleFont: 'cc-wild-words' | 'comic-neue' | 'bangers' | 'patrick-hand' | 'system-ui'` to `chrome.storage.local` settings, with dynamic selection in `popup.html`.

### 3.2. Smart Bubble Typography Fitter v2
Upgrade `fitFontSize()` in `src/extension/content/font_fitter.ts` with four dynamic capabilities:
1. **Dynamic Max Font Size:** Calculate `maxFontSize = Math.min(Math.max(24, Math.floor(clientH * 0.65)), 80)`. Large shouting bubbles ($H \ge 120\text{px}$) can scale up to 60–80px to fill the bubble dramatically.
2. **Dynamic Min Font Size & Micro-Padding:** For micro-bubbles ($H < 28\text{px}$ or $W < 35\text{px}$), drop `minFontSize` to $7.5\text{px}$ and reduce padding from `4px 6px` to `1px 2px`, eliminating text edge clipping.
3. **Diamond/Oval Paragraph Balancing:** Apply native CSS `text-wrap: balance` inside Shadow DOM. For bubbles with aspect ratio $W / H \ge 1.3$ and `wordCount >= 4`, constrain the inner text wrapper to `max-width: 82%` to naturally fold sentences into 2–3 balanced lines.
4. **Shouting & Impact Detection:** If `wordCount <= 3` and bubble area $W \times H \ge 10,000\text{px}^2$, assign `font-weight: 800` (Extra Bold) to emphasize shouting exclamations.

---

## 4. Consequences

- **Positive Impact:**
  - True manga scanlation look and feel out of the box with zero setup.
  - Complete elimination of single-line stretching in tall/oval bubbles.
  - Shouting text commands proper dramatic scale without floating tiny in the center.
  - Micro-bubbles fit short words cleanly without truncation.
- **Trade-offs:**
  - Slightly larger `.zip` package size (+$\approx 180\text{KB}$) due to embedded `.woff2` font files.
- **Follow-up Tasks:**
  - Author and register `@font-face` definitions in Shadow DOM styles.
  - Implement `fitFontSize` v2 formulas in `font_fitter.ts`.
  - Add font selector UI to `popup.html` and wire change listener to `chrome.storage.local`.
