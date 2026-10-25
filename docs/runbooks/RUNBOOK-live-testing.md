# InkShift Runbook: Live Testing Local Engine with Chrome Extension

> **Target Module:** Module 5 (`local-engine`) & Module 4 (`extension-core`)  
> **Environment:** Windows 10/11 (DirectML GPU or CPU Fallback)  
> **Status:** Active & Ready for Verification  

---

## 1. Prerequisites Checklist

Ensure all foundational components are built and present:

1. **Model Weights:**
   - Location: `.cache/inkshift/models/yolo11s-seg.onnx` (~25 MB).
   - **Auto-Download:** The backend automatically stream-downloads missing weights from Hugging Face on startup when `INKSHIFT_AUTO_DOWNLOAD_MODELS=true`.
   - Alternatively, pre-download manually via:
     ```powershell
     python scripts/download_models.py
     ```
2. **Python Backend Packages:**
   - Verify `onnxruntime-directml`, `rapidocr-onnxruntime`, `httpx`, and `fastapi` are installed.
3. **Extension Distribution Bundle:**
   - Freshly compiled bundle exists in `dist/`.
   - Built via:
     ```powershell
     npm run build:extension
     ```

---

## 2. Step-by-Step Launch & Test Procedure

### Step 1: Launch FastAPI Backend Server

You can launch the gateway using the one-click launcher or manually:

**Method A: One-Click Launcher (Windows)**
Double-click `start.bat` in the repository root.

**Method B: Manual Launch (PowerShell / Bash)**
Open a terminal in the project root (`c:\Vide_coding\ink-shift`) and run:

```powershell
python -m uvicorn src.backend.app:app --host 127.0.0.1 --port 8000 --reload
```

**Expected Startup Output in Terminal:**
```text
==================================================
InkShift Backend Gateway is ready
Default Engine: mock (or local / cloud)
Database Path:  ./data/cache.db
==================================================
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

---

### Step 2: Load Extension into Chromium Browser

1. Open Google Chrome, Microsoft Edge, or Brave.
2. Navigate to: `chrome://extensions/`.
3. Enable **Developer mode** toggle in the top-right corner.
4. Click **Load unpacked** in the top-left corner.
5. Select the build directory:
   ```text
   c:\Vide_coding\ink-shift\dist
   ```
6. **Required for Local File Testing (`file:///`):**
   - On the **InkShift** extension card, click **Details**.
   - Scroll down and enable **Allow access to file URLs**.

---

### Step 3: Open Manga Reader Test Page

Select either test approach:

#### Approach A: Offline Local Testing (No External Network Required)
Drag and drop the fixture file into Chrome, or paste this URL:
```text
file:///c:/Vide_coding/ink-shift/tests/fixtures/manga_test_page.html
```

#### Approach B: Live Web Testing (MangaDex, Cuutruyen, etc.)
Navigate to any chapter on an online reader (e.g., [MangaDex](https://mangadex.org)).

---

### Step 4: Translation Operation via Extension Popup & Mascot

1. Click the **InkShift** extension icon in your browser toolbar (pin the extension for convenience).
2. Check the status badge:
   - Should indicate green: **Online**.
3. Under **Translation Engine**, select your target pipeline:
   - `Auto (Default)`: Routes requests based on server configuration.
   - `Local DirectML (On-Device)`: Fully on-device inference. Enables the **Text Translator** selector:
     - `Google Translate (Free $0)` (Default)
     - `LLM Text (OpenAI / DeepSeek / Ollama)`
   - `Cloud AI (Multi-Provider)`: Multimodal Vision with Set-of-Marks grounding. Enables the **Cloud Provider** selector:
     - `Google Gemini (Default)`
     - `OpenAI / Compatible`
4. Click **Re-scan Current Page**.

---

### Step 4.1: Reader Keyboard Shortcuts

While viewing manga chapters:
- **`Alt + Z`**: Toggle translation overlays on/off in real-time. When toggled off, the Mascot enters sleep state (`sleeping`).
- **`Alt + M`**: Toggle Mascot HUD companion visibility on/off.
- **Typing Guard**: Shortcuts are bypassed when typing inside `<input>`, `<textarea>`, `contenteditable`, or during IME composition.
- **Z-Index Layering**: Mascot HUD is anchored at `z-index: 2147483647` (highest), overlays at `z-index: 2147483640` to guarantee accessibility without occlusion.

---

### Step 5: Verification Checklist

Observe the browser viewport and backend logs to confirm operation:

1. **Backend Terminal & Log File (`data/logs/inkshift.log`):**
   - Backend traces pipeline stages with millisecond precision:
     ```text
     RequestReceived: engine=local, target=vi, size_kb=2463.3
     StageStarted: stage=1/4, action="DecodeImageAndValidate"
     StageCompleted: stage=1/4, elapsed_ms=63.6
     StageStarted: stage=3/4, action="OCRRecognition (mode=en)"
     RapidOCR full-page completed: 29 text elements mapped to 7 bubbles in 1354.41ms (valid=6/7)
     StageStarted: stage=4/4, action="BatchTranslate (6 blocks -> vi via google-free)"
     StageCompleted: stage=4/4, elapsed_ms=3905.0
     PipelineCompleted: engine=local, elapsed_ms=5348, blocks=6
     ```
   - On `local` (Non-JA): RapidOCR executes single-pass full-page recognition without individual bubble crops.
   - On `cloud`: Visual grounding renders Set-of-Marks and queries upstream providers with automated retry on HTTP 429/503.

2. **Chrome Browser & Extension Telemetry Log (`data/logs/extension.log`):**
   - Inspect `data/logs/extension.log` for background prefetch telemetry:
     ```text
     [INFO] [inkshift.extension.prefetch] Starting prefetch for page #18 (P1, provider: google-free)
     [INFO] [inkshift.extension.prefetch] Page #18 ready in prefetch cache (6 blocks, cache)
     [INFO] [inkshift.extension.cs] Mounted overlay from prefetch cache (page_number) for image #2 (page #18, 6 blocks)
     ```
   - On navigating to the next page, the **Shadow DOM** overlay mounts instantly (0ms) from the prefetch cache.
   - Text size automatically balances via dynamic font-fitting inside the bubble safe-zone.

---

## 3. Troubleshooting Matrix

| Issue | Likely Cause | Resolution |
|---|---|---|
| Badge displays **Offline** | Backend gateway is stopped or port 8000 is occupied | Re-run uvicorn or `start.bat`. Confirm `http://127.0.0.1:8000/api/v1/cache/stats` responds. |
| Cannot scan images on `file:///` URLs | File URL access permission not granted | Navigate to `chrome://extensions/` -> Details on InkShift -> Enable **Allow access to file URLs**. |
| Missing model weights error | `yolo11s-seg.onnx` incomplete or missing | Run `python scripts/download_models.py --force`. |
| Extension UI does not reflect changes | Chrome cached previous build bundle | Click the **Reload (circular arrow)** button on the InkShift card in `chrome://extensions/`. |
