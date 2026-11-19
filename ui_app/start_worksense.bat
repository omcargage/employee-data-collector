@echo off
title WorkSense — Burnout Prevention Platform
echo.
echo   WorkSense — Early-Warning Burnout Prevention
echo   FLAME University Research Prototype
echo   ---------------------------------------------
echo.

cd /d "%~dp0"

set PYTHON="..\agent\.venv\Scripts\python.exe"

if not exist %PYTHON% (
    echo [ERROR] Python venv not found. Run setup first.
    pause & exit /b 1
)

echo Starting WorkSense desktop application...
echo (First launch takes ~10 seconds to load the AI model)
echo.

%PYTHON% launch.py

pause
