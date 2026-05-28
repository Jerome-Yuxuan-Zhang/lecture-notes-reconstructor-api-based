@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"
title Lecture Reconstructor

echo.
echo ===============================================
echo   Lecture Reconstructor - one click launcher
echo ===============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Please install Python 3.11 or newer, then run this file again.
  echo Download: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating local Python environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

set "STAMP=.venv\requirements.stamp"
set "NEED_INSTALL=0"

if not exist "%STAMP%" (
  set "NEED_INSTALL=1"
) else (
  for %%R in ("requirements.txt") do for %%S in ("%STAMP%") do (
    if "%%~tR" GTR "%%~tS" set "NEED_INSTALL=1"
  )
)

if "%NEED_INSTALL%"=="1" (
  echo Installing or updating dependencies...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
  )
  copy /y requirements.txt "%STAMP%" >nul
) else (
  echo Dependencies are already installed. Skipping install.
)

echo.
echo Starting app...
echo Browser URL: http://127.0.0.1:8080
echo Keep this window open while using the app.
echo.

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8080' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 (
  echo App already seems to be running.
  start "" "http://127.0.0.1:8080"
  echo.
  pause
  exit /b 0
)

start "" "http://127.0.0.1:8080"
python app.py

echo.
echo App stopped.
pause
