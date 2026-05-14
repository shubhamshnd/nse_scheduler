@echo off
setlocal enabledelayedexpansion
title Nifty Pipeline — Windows Setup

echo.
echo  =====================================================
echo   Nifty Pipeline — Windows Setup
echo  =====================================================
echo.

REM ── Check Python ─────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found.

REM ── Create virtual environment ────────────────────────
echo.
echo [1/4] Creating virtual environment...
if exist venv (
    echo       venv\ already exists, skipping creation.
) else (
    python -m venv venv
    if errorlevel 1 ( echo [ERROR] Failed to create venv. & pause & exit /b 1 )
    echo [OK] venv\ created.
)

REM ── Activate and upgrade pip ──────────────────────────
echo.
echo [2/4] Activating venv and upgrading pip...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
echo [OK] pip upgraded.

REM ── Install requirements ──────────────────────────────
echo.
echo [3/4] Installing requirements (this may take a minute)...
pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] pip install failed. & pause & exit /b 1 )
echo [OK] Dependencies installed.

REM ── Create directories ────────────────────────────────
echo.
echo [4/4] Creating data/ and logs/ directories...
if not exist data  mkdir data
if not exist logs  mkdir logs
echo [OK] Directories ready.

REM ── Done ──────────────────────────────────────────────
echo.
echo  =====================================================
echo   Setup complete!
echo  =====================================================
echo.
echo  Next steps:
echo.
echo    1. Edit config.yaml — fill in your API keys:
echo         alpha_vantage, newsdata_io, groq, telegram_bot, telegram_chat
echo.
echo    2. Start the web server:
echo         venv\Scripts\activate.bat
echo         python app.py
echo.
echo    3. Open browser: http://localhost:5000
echo.
echo    4. (Optional) Run CLI pipeline:
echo         python run.py --list-tasks
echo         python run.py screen
echo.
pause
