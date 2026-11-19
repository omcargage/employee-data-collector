@echo off
title WorkSense — Early-Warning Burnout Prevention
echo.
echo  ██╗    ██╗ ██████╗ ██████╗ ██╗  ██╗███████╗███████╗███╗   ██╗███████╗███████╗
echo  ██║    ██║██╔═══██╗██╔══██╗██║ ██╔╝██╔════╝██╔════╝████╗  ██║██╔════╝██╔════╝
echo  ██║ █╗ ██║██║   ██║██████╔╝█████╔╝ ███████╗█████╗  ██╔██╗ ██║███████╗█████╗  
echo  ██║███╗██║██║   ██║██╔══██╗██╔═██╗ ╚════██║██╔══╝  ██║╚██╗██║╚════██║██╔══╝  
echo  ╚███╔███╔╝╚██████╔╝██║  ██║██║  ██╗███████║███████╗██║ ╚████║███████║███████╗
echo   ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝╚══════╝╚══════╝
echo.
echo  WorkSense Desktop Application — FLAME University Research Prototype
echo  -------------------------------------------------------------------
echo.

cd /d "%~dp0"

REM Check if venv Python exists
set PYTHON="..\agent\.venv\Scripts\python.exe"
if not exist %PYTHON% (
    echo [ERROR] Python venv not found at agent\.venv
    echo         Please run: cd agent ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

REM Launch Desktop App via launcher
%PYTHON% desktop.py

pause
