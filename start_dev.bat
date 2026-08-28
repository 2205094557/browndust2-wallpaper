@echo off
setlocal
cd /d "%~dp0"

rem ===== 1) Locate Python: prefer project .venv, else system PATH =====
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo [dev] Python not found. Install Python 3, add it to PATH, or create .venv first.
    pause
    exit /b 1
)

rem ===== 2) Frontend deps (Vite) check; auto install if missing =====
if not exist "frontend\node_modules\vite\bin\vite.js" (
    echo [dev] Frontend deps missing, running npm install ...
    pushd frontend
    call npm install
    popd
    if errorlevel 1 (
        echo [dev] npm install failed. Run manually: cd frontend ^&^& npm install
        pause
        exit /b 1
    )
)

rem ===== 3) Start backend 8766 + Vite 5173 + window =====
rem      Closing the app window makes start_dev.py auto-clean backend & Vite.
rem      Pass --stop to shut the whole stack down manually.
echo [dev] Starting dev stack (backend 8766 / Vite 5173 / window)...
"%PY%" scripts\start_dev.py %*
set "EXIT=%errorlevel%"

echo.
echo [dev] Dev stack exited (code %EXIT%).
if not "%EXIT%"=="0" (
    echo [dev] Startup or run failed, see log above. Or run: python scripts\start_dev.py --stop
    pause
)
exit /b %EXIT%
