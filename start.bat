@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title InkShift Gateway Launcher

echo ============================================================
echo   InkShift - Manga Vision Translation Gateway Launcher
echo ============================================================
echo.

:: ------------------------------------------------------------
:: 1. Pre-flight Network Port 8000 Conflict Guard
:: ------------------------------------------------------------
set "PORT_BUSY="
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    set "PORT_BUSY=%%a"
)
if defined PORT_BUSY (
    echo [WARNING] Port 8000 is already in use by PID: %PORT_BUSY%
    echo Another InkShift Gateway or web service is running.
    echo If launch fails, please terminate process %PORT_BUSY% or restart your terminal.
    echo.
)

:: ------------------------------------------------------------
:: 2. Environment Resolution (Priority: .venv first, then Host)
:: ------------------------------------------------------------
set "ACTIVE_PYTHON="

:: Step 2a. Check if local .venv exists
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, aiosqlite, onnxruntime, cv2, deep_translator, rapidocr_onnxruntime" >nul 2>&1
    if not errorlevel 1 (
        set "ACTIVE_PYTHON=%~dp0.venv\Scripts\python.exe"
        echo [InkShift] Using ready local .venv environment.
        goto :DEPS_READY
    )
    echo [InkShift] Local .venv environment found, but some dependencies are missing.
    set "ACTIVE_PYTHON=%~dp0.venv\Scripts\python.exe"
    goto :INSTALL_DEPS
)

:: Step 2b. If .venv does not exist, find host Python to initialize it
echo [InkShift] Local .venv not found. Locating host Python...

set "SYS_PYTHON="
for %%p in (
    "python"
    "py -3"
    "py"
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
) do (
    if not defined SYS_PYTHON (
        %%~p -c "import sys; exit(0 if sys.version_info.major == 3 and sys.version_info.minor >= 10 else 1)" >nul 2>&1
        if not errorlevel 1 set "SYS_PYTHON=%%~p"
    )
)

if not defined SYS_PYTHON (
    echo [ERROR] Python 3.10+ was not found on your system.
    echo Please install Python 3.10 or newer from https://www.python.org/
    echo CRITICAL: Ensure you check the box: "Add python.exe to PATH".
    goto :HALT
)

echo [InkShift] Initializing local virtual environment .venv...
"%SYS_PYTHON%" -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment .venv.
    goto :HALT
)
set "ACTIVE_PYTHON=%~dp0.venv\Scripts\python.exe"

:INSTALL_DEPS
echo [InkShift] Installing / updating dependencies from requirements.txt...
"%ACTIVE_PYTHON%" -m pip install --upgrade pip >nul 2>&1
"%ACTIVE_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. Please check network connectivity.
    goto :HALT
)

:DEPS_READY

:: ------------------------------------------------------------
:: 3. Configuration Initialization (.env)
:: ------------------------------------------------------------
if exist ".env" goto :SKIP_ENV_INIT
if exist ".env.example" copy .env.example .env >nul
echo [InkShift] Initialized default configuration .env with zero-cost local engine.
:SKIP_ENV_INIT

:: ------------------------------------------------------------
:: 4. Browser Extension Bundle Resolution (dist/ or zip fallback)
:: ------------------------------------------------------------
if exist "dist\manifest.json" goto :CHECK_MODELS

echo [InkShift] Browser extension bundle not found in dist/.
where npm >nul 2>&1 || goto :TRY_UNPACK_ZIP

echo [InkShift] Node.js detected. Compiling extension bundle via Vite...
if not exist "node_modules" call npm install
call npm run build:extension
if exist "dist\manifest.json" (
    echo [InkShift] Browser extension successfully compiled to dist/.
    goto :CHECK_MODELS
)

:TRY_UNPACK_ZIP
if exist "inkshift-extension.zip" goto :DO_UNPACK

echo [InkShift] Checking GitHub Releases for pre-built extension package...
powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://github.com/thailong2103/ink-shift/releases/latest/download/inkshift-extension.zip', 'inkshift-extension.zip'); exit 0 } catch { exit 1 }" >nul 2>&1

:DO_UNPACK
if exist "inkshift-extension.zip" (
    echo [InkShift] Pre-built package inkshift-extension.zip detected. Unpacking...
    powershell -NoProfile -Command "Expand-Archive -Path 'inkshift-extension.zip' -DestinationPath 'dist' -Force" >nul 2>&1
    if exist "dist\manifest.json" (
        echo [InkShift] Browser extension successfully unpacked into dist/.
        goto :CHECK_MODELS
    )
)

echo [WARNING] Extension bundle not found and Node.js is not installed.
echo Gateway will run in headless API mode.
echo.
echo To use the Chrome Extension:
echo   1. Download 'inkshift-extension.zip' from GitHub Releases:
echo      https://github.com/thailong2103/ink-shift/releases
echo      and place it in this repository folder, then restart start.bat.
echo   2. Or install Node.js v18+ from https://nodejs.org/ to compile it automatically.
echo.

:CHECK_MODELS
:: ------------------------------------------------------------
:: 5. YOLO11 ONNX Model Weights Check & Download
:: ------------------------------------------------------------
if exist ".cache\inkshift\models\yolo11s-seg.onnx" goto :LAUNCH_GATEWAY
if exist "models\yolo11s-seg.onnx" goto :LAUNCH_GATEWAY

echo [InkShift] YOLO11s-seg detection weights not found.
echo [InkShift] Downloading on-device model weights from Hugging Face ~39 MB...
"%ACTIVE_PYTHON%" scripts\download_models.py
if errorlevel 1 (
    echo [ERROR] Failed to download or verify YOLO11s-seg model weights.
    echo Please verify your internet connection or run manually:
    echo   "%ACTIVE_PYTHON%" scripts\download_models.py
    goto :HALT
)

:LAUNCH_GATEWAY
if "%~1"=="--dry-run" (
    echo [InkShift] Dry run verification successful!
    echo   Active Python:     %ACTIVE_PYTHON%
    echo   Extension Manifest: dist\manifest.json
    goto :HALT_SUCCESS
)
if "%~1"=="--help" goto :PRINT_HELP
if "%~1"=="-h" goto :PRINT_HELP
goto :START_SERVER

:PRINT_HELP
echo Usage: start.bat [OPTIONS]
echo.
echo Options:
echo   --dry-run     Verify environment, dependencies, and models without launching server
echo   --help, -h    Display this help message
goto :HALT_SUCCESS

:START_SERVER
:: ------------------------------------------------------------
:: 6. Launch Uvicorn Gateway & Display Onboarding Instructions
:: ------------------------------------------------------------
echo.
echo ============================================================
echo   INKSHIFT GATEWAY IS READY!
echo ============================================================
echo   Server Address:    http://127.0.0.1:8000
echo   OpenAPI Swagger:   http://127.0.0.1:8000/docs
echo.

if not exist "dist\manifest.json" goto :PRINT_API_MODE
echo   [HOW TO LOAD BROWSER EXTENSION]
echo   1. Open Google Chrome, Brave, or Microsoft Edge.
echo   2. Navigate to:  chrome://extensions/
echo   3. Enable Developer mode [toggle in top-right corner].
echo   4. Click Load unpacked [top-left button].
echo   5. Select this folder:
echo      %~dp0dist
echo.
echo   [HOTKEYS ON MANGA SITES]
echo   - Alt + Z : Toggle Japanese-to-Vietnamese Translation Overlay
echo   - Alt + M : Toggle Mascot HUD / Mode Switcher
goto :CONTINUE_BANNER

:PRINT_API_MODE
echo   [NOTICE] Extension dist/ not loaded. Gateway running in API mode.

:CONTINUE_BANNER
echo ============================================================
echo   Press Ctrl+C to stop the gateway server.
echo.

"%ACTIVE_PYTHON%" -m uvicorn src.backend.app:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
    echo.
    echo [ERROR] InkShift Gateway server stopped unexpectedly.
    goto :HALT
)

:HALT_SUCCESS
echo [InkShift] Verification complete.
endlocal
exit /b 0

:HALT
echo.
echo [InkShift] Process terminated.
if "%~1"=="" (
    echo Press any key to close this window...
    pause >nul
)
endlocal
exit /b 1
