@echo off
rem ===================================================================
rem  AIOneWeek - one-click local launcher
rem  Double-click this file to start the site.
rem  CLOSE THIS WINDOW (or press Ctrl+C) to stop the server.
rem
rem  NOTE: this file is intentionally ASCII-only. Chinese text is
rem  printed by run.py, which the console renders natively.
rem ===================================================================

setlocal
cd /d "%~dp0"
title AIOneWeek

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"

echo.
echo   ============================================
echo     AIOneWeek  -  local launcher
echo   ============================================
echo.

rem ---------- 1. find a python interpreter to build the venv ----------
if exist "%PY%" goto :deps

set "BOOT="
where py >nul 2>nul && set "BOOT=py -3"
if not defined BOOT (
  where python >nul 2>nul && set "BOOT=python"
)
if not defined BOOT (
  echo   [ERROR] Python was not found on this machine.
  echo.
  echo   Install Python 3.10 or newer from https://www.python.org/downloads/
  echo   During setup, tick "Add python.exe to PATH", then run this file again.
  echo.
  pause
  exit /b 1
)

echo   [1/3] Creating virtual environment .venv  (one time only) ...
%BOOT% -m venv "%VENV%"
if not exist "%PY%" (
  echo.
  echo   [ERROR] Failed to create the virtual environment.
  echo.
  pause
  exit /b 1
)

rem ---------- 2. install dependencies ----------
:deps
echo   [2/3] Checking dependencies ...
"%PY%" -c "import fastapi, uvicorn, sqlalchemy, httpx, apscheduler, cryptography, dotenv" >nul 2>nul
if not errorlevel 1 goto :config

echo         Installing from requirements.txt, this may take a few minutes ...
"%PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%PY%" -m pip install -r "%~dp0requirements.txt" --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo   [ERROR] Dependency installation failed. Check your network, then retry.
  echo.
  pause
  exit /b 1
)
"%PY%" -c "import fastapi, uvicorn, sqlalchemy, httpx, apscheduler, cryptography, dotenv" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [ERROR] Dependencies still missing after install. Retry later.
  echo.
  pause
  exit /b 1
)

rem ---------- 3. check .env ----------
:config
if not exist "%~dp0.env" (
  echo.
  echo   [ERROR] .env not found in this folder.
  echo.
  echo   Copy .env.example to .env, then fill in:
  echo     DEEPSEEK_API_KEY, SMTP_USER, SMTP_AUTH_CODE,
  echo     FERNET_KEY, SESSION_SECRET, ADMIN_EMAIL, ADMIN_INIT_PASSWORD
  echo.
  echo   Generate FERNET_KEY with:
  echo     .venv\Scripts\python.exe -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
  echo.
  pause
  exit /b 1
)

echo   [3/3] Starting server ...
echo.

rem ---------- run (foreground: closing this window kills the server) ----------
"%PY%" "%~dp0run.py"

echo.
echo   Server stopped.
pause
endlocal
