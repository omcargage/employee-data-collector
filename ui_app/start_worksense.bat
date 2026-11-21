@echo off
title WorkSense - Early-Warning Burnout Prevention
cls

echo ======================================================================
echo   WorkSense - Early-Warning Burnout Prevention Platform
echo   FLAME University Research Prototype
echo ======================================================================
echo.

setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"

if not exist "%SCRIPT_DIR%desktop.py" (
    echo [ERROR] Cannot locate desktop.py in %SCRIPT_DIR%
    pause
    exit /b 1
)

set "PY_EXE="
if exist "%SCRIPT_DIR%..\agent\.venv\Scripts\python.exe" (
    set "PY_EXE=%SCRIPT_DIR%..\agent\.venv\Scripts\python.exe"
) else if exist "D:\FLAME_UG\UG4\IMP_Data\employee-data-collector\agent\.venv\Scripts\python.exe" (
    set "PY_EXE=D:\FLAME_UG\UG4\IMP_Data\employee-data-collector\agent\.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

echo Starting WorkSense with: !PY_EXE!
echo.

cd /d "%SCRIPT_DIR%"
"!PY_EXE!" "desktop.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ======================================================================
    echo [ERROR] WorkSense closed with return code %ERRORLEVEL%.
    echo Check the error message above for details.
    echo ======================================================================
    pause
)
