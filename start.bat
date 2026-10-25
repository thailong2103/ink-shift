@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title InkShift Gateway Launcher

echo ============================================================
echo   InkShift - Manga Vision Translation Gateway Launcher
echo ============================================================
echo.

set "ACTIVE_PYTHON="

:: 1. Check host system 'python'
where python >nul 2>&1 || goto :CHECK_PY
python -c "import fastapi, uvicorn" >nul 2>&1 || goto :CHECK_PY
set "ACTIVE_PYTHON=python"
echo [InkShift] Found ready host Python environment.
goto :DEPS_READY

:CHECK_PY
:: 2. Check host 'py' launcher
where py >nul 2>&1 || goto :CHECK_VENV
py -c "import fastapi, uvicorn" >nul 2>&1 || goto :CHECK_VENV
set "ACTIVE_PYTHON=py"
echo [InkShift] Found ready host Python via py launcher.
goto :DEPS_READY

:CHECK_VENV
:: 3. Check local .venv
if not exist ".venv\Scripts\python.exe" goto :FIND_PYTHON
".venv\Scripts\python.exe" -c "import fastapi, uvicorn" >nul 2>&1 || goto :FIND_PYTHON
set "ACTIVE_PYTHON=%~dp0.venv\Scripts\python.exe"
echo [InkShift] Using existing .venv environment.
goto :DEPS_READY

:FIND_PYTHON
:: 4. If nowhere has dependencies, find Python binary to initialize
where python >nul 2>&1 && set "ACTIVE_PYTHON=python"
if defined ACTIVE_PYTHON goto :FOUND_SYS_PYTHON

where py >nul 2>&1 && set "ACTIVE_PYTHON=py"
if defined ACTIVE_PYTHON goto :FOUND_SYS_PYTHON

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "ACTIVE_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe" & goto :FOUND_SYS_PYTHON
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "ACTIVE_PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe" & goto :FOUND_SYS_PYTHON
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "ACTIVE_PYTHON=%LocalAppData%\Programs\Python\Python310\python.exe" & goto :FOUND_SYS_PYTHON
if exist "%ProgramFiles%\Python312\python.exe" set "ACTIVE_PYTHON=%ProgramFiles%\Python312\python.exe" & goto :FOUND_SYS_PYTHON
if exist "%ProgramFiles%\Python311\python.exe" set "ACTIVE_PYTHON=%ProgramFiles%\Python311\python.exe" & goto :FOUND_SYS_PYTHON
if exist "C:\Python312\python.exe" set "ACTIVE_PYTHON=C:\Python312\python.exe" & goto :FOUND_SYS_PYTHON
if exist "C:\Python311\python.exe" set "ACTIVE_PYTHON=C:\Python311\python.exe" & goto :FOUND_SYS_PYTHON

echo [ERROR] Python 3.10+ was not found on your system.
echo Please install Python from https://www.python.org/
echo Make sure to check the box: "Add python.exe to PATH".
goto :HALT

:FOUND_SYS_PYTHON
:: Verify version >= 3.10
"%ACTIVE_PYTHON%" -c "import sys; exit(0 if sys.version_info.major == 3 and sys.version_info.minor >= 10 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10 or newer is required.
    goto :HALT
)

:: Setup venv only if dependencies missing
echo [InkShift] Setting up local virtual environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
    "%ACTIVE_PYTHON%" -m venv .venv || goto :HALT
)
set "ACTIVE_PYTHON=%~dp0.venv\Scripts\python.exe"
echo [InkShift] Installing dependencies from requirements.txt...
"%ACTIVE_PYTHON%" -m pip install -r requirements.txt || goto :HALT

:DEPS_READY

:: 5. Initialize .env from .env.example if missing
if not exist ".env" (
    if exist ".env.example" copy .env.example .env >nul
)

:: 6. Check and Build Browser Extension if dist/ is missing
if exist "dist\manifest.json" goto :CHECK_MODELS

echo [InkShift] Browser extension bundle not found in dist/.
where npm >nul 2>&1 || goto :NO_NPM

echo [InkShift] Node.js detected. Building extension bundle via Vite...
if not exist "node_modules" call npm install
call npm run build:extension
if exist "dist\manifest.json" (
    echo [InkShift] Browser extension successfully compiled to dist/.
) else (
    echo [WARNING] Extension build completed with warnings. Check dist/ directory.
)
goto :CHECK_MODELS

:NO_NPM
echo [WARNING] Node.js is not installed or not in PATH.
echo Cannot automatically build the browser extension from source.
echo You can install Node.js (v18+) or load a pre-built extension zip.

:CHECK_MODELS
:: 7. Check YOLO11 ONNX Model Weights
if exist ".cache\inkshift\models\yolo11s-seg.onnx" goto :LAUNCH_GATEWAY
if exist "models\yolo11s-seg.onnx" goto :LAUNCH_GATEWAY

echo [InkShift] YOLO11s-seg weights not found. Pre-downloading (~25 MB)...
"%ACTIVE_PYTHON%" scripts\download_models.py

:LAUNCH_GATEWAY
:: 8. Launch Uvicorn Gateway
echo.
echo ============================================================
echo   Gateway Server:   http://127.0.0.1:8000
echo   OpenAPI Docs:     http://127.0.0.1:8000/docs
echo.
if exist "dist\manifest.json" (
    echo   Chrome Extension: Load unpacked from:
    echo   %~dp0dist
) else (
    echo   Chrome Extension: Please build extension or load pre-built zip.
)
echo ============================================================
echo   Press Ctrl+C to terminate the server.
echo.

"%ACTIVE_PYTHON%" -m uvicorn src.backend.app:app --host 127.0.0.1 --port 8000

:HALT
echo.
echo [InkShift] Process finished.
pause
endlocal
