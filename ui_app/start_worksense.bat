@echo off
@chcp 65001 > nul
title WorkSense - Early-Warning Burnout Prevention
cls

echo ======================================================================
echo    _       __           __   _____                      
echo   ^| ^|     / /___  _____/ /__/ ___/___  ____  ________ 
echo   ^| ^| /^| / / __ \/ ___/ //_/\__ \/ _ \/ __ \/ ___/ _ \
echo   ^| ^|/ ^|/ / /_/ / /  / ,^<  ___/ /  __/ / / (__  )  __/
echo   ^|__/^|__/\____/_/  /_/^|_^|/____/\___/_/ /_/____/\___/ 
echo.
echo   FLAME University Research Prototype -- Burnout Prevention Platform
echo ======================================================================
echo.

cd /d "%~dp0"

set PYTHON="..\agent\.venv\Scripts\python.exe"
if not exist %PYTHON% (
    echo [ERROR] Virtual environment Python not found at:
    echo         agent\.venv\Scripts\python.exe
    echo.
    echo Please ensure the agent venv is set up.
    echo.
    pause
    exit /b 1
)

%PYTHON% desktop.py
pause
