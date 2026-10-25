# Extension Popup UI Specification & Overrides

> **PROJECT:** InkShift  
> **Target:** `src/extension/popup/` (`popup.html`, `popup.css`, `popup.ts`)  
> **Master Reference:** `design-system/inkshift/MASTER.md`

---

## 1. Viewport & Dimensions

- **Width:** Exactly `400px` (standard Chrome Extension width)
- **Max Height:** `560px` (Main View fits strictly within $\le 420px$, zero vertical scrolling)
- **Background:** `var(--inkshift-bg)` (`#12100E`)
- **Text:** `var(--inkshift-text-primary)` (`#FAF5F0`)
- **Border Radius:** `12px` (outer popup frame if floating, otherwise `0px` inside browser popup window)

---

## 2. Information Architecture (2-View Model)

### View A: Main Reading Dashboard (`#view-main`)
- **Header:**
  - InkShift Logo with terracotta dot (`#DE886D`).
  - Backend Status Pill (`🟢 Online` / `🔴 Offline`) with live latency indicator.
  - Quick Settings Button: Gear icon `⚙️` (`#btn-open-settings`) with hover rotation transition.
- **Card 1: Active Domain Status Card:**
  - Active domain badge (e.g., `mangadex.org` — Supported / Whitelisted).
  - Quick shortcut hint (`Nhấn "Z" để ẩn/hiện bóng thoại`).
- **Card 2: Primary Control (Hero Toggle):**
  - Prominent Toggle Switch: **Bật Bản Dịch (Show Overlays)**.
  - Large CTA Button: **Quét & Dịch lại trang (Re-scan Page)**.
- **Card 3: Engine & Model Quick Picker:**
  - Engine switcher: `Cloud AI` ↔ `Local DirectML` (Segmented pills).
  - Active Model Combobox with vision indicator badge.
- **Card 4: Reading Aesthetics Customizer:**
  - Font dropdown: Manga Comic (`Itim`), Action (`Bangers`), Handwritten (`Patrick Hand`), System Sans.
  - Speech Bubble Background Palette: Warm Paper (`#FAF5F0`), OLED Dark (`#1C1917`), Sepia (`#F4ECD8`).
  - Opacity Slider with live percentage label (`88%`).
  - Source Language Selector (`Auto`, `ja`, `en`, `ko`, `zh`).

---

### View B: Settings & Configuration Drawer (`#view-settings`)
- **Sub-header:**
  - Back Button: `← Quay lại` (`#btn-close-settings`) returning smoothly to Main View.
  - Title: "Cài đặt & Cấu hình".
- **Section 1: API Keys & Endpoints (Accordion):**
  - Google Gemini API Key (masked input, test connection, status pill).
  - OpenAI API Key.
  - Anthropic Claude API Key.
  - Custom OpenAI-Compatible Base URL & Key.
- **Section 2: Domain Management (Accordion):**
  - Whitelist domains list with tag deletion pills.
  - Blacklist domains list with tag deletion pills.
  - Add domain row (`input + select + button`).
  - "Khôi phục mặc định" reset button.
- **Section 3: Speed & Prefetch Engine (Accordion):**
  - Prefetch sliding window toggle.
  - Prefetch depth dropdown (3, 5, 10 pages, whole chapter).
- **Section 4: Developer & Diagnostics (Accordion):**
  - Visual YOLO polygon debug toggle.
  - Mascot floating HUD toggle (`Bật/Tắt linh vật trên trang`).
  - Clear translation cache button.
  - Telemetry log summary.

---

## 3. Component Specs

- **Bento Card:** Background `var(--inkshift-card)` (`#1C1917`), border `1px solid var(--inkshift-border-subtle)` (`#2E2825`), padding `10px 12px`, border-radius `10px`.
- **Primary CTA:** Background `var(--inkshift-brand)` (`#DE886D`), color `#12100E`, font-weight `700`, height `38px`.
- **Toggle Switch:** Width `36px`, height `20px`, smooth thumb translation `16px` on check.
- **Combobox:** Custom dark dropdown with search filter and hover highlighting.
