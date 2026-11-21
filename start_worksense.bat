@echo off
title WorkSense - Early-Warning Burnout Prevention
cls

echo ======================================================================
echo   WorkSense - Early-Warning Burnout Prevention Platform
echo   FLAME University Research Prototype
echo ======================================================================
echo.

set SCRIPT_DIR=%~dp0
set TARGET_DIR=%SCRIPT_DIR%

:: Detect python executable across common paths
set PYTHON=
if exist "%SCRIPT_DIR%agent\.venv\Scripts\python.exe" (
    set PYTHON="%SCRIPT_DIR%agent\.venv\Scripts\python.exe"
    set TARGET_DIR=%SCRIPT_DIR%ui_app\
) else if exist "%SCRIPT_DIR%employee-data-collector\agent\.venv\Scripts\python.exe" (
    set PYTHON="%SCRIPT_DIR%employee-data-collector\agent\.venv\Scripts\python.exe"
    set TARGET_DIR=%SCRIPT_DIR%employee-data-collector\ui_app\
) else if exist "D:\FLAME_UG\UG4\IMP_Data\employee-data-collector\agent\.venv\Scripts\python.exe" (
    set PYTHON="D:\FLAME_UG\UG4\IMP_Data\employee-data-collector\agent\.venv\Scripts\python.exe"
    set TARGET_DIR=D:\FLAME_UG\UG4\IMP_Data\employee-data-collector\ui_app\
) else (
    set PYTHON=python
)

:: Detect desktop.py
set DESKTOP_SCRIPT=
if exist "%TARGET_DIR%desktop.py" (
    set DESKTOP_SCRIPT="%TARGET_DIR%desktop.py"
) else if exist "%SCRIPT_DIR%ui_app\desktop.py" (
    set DESKTOP_SCRIPT="%SCRIPT_DIR%ui_app\desktop.py"
) else if exist "D:\FLAME_UG\UG4\IMP_Data\employee-data-collector\ui_app\desktop.py" (
    set DESKTOP_SCRIPT="D:\FLAME_UG\UG4\IMP_Data\employee-data-collector\ui_app\desktop.py"
)

if "%DESKTOP_SCRIPT%"=="" (
    echo [ERROR] Could not find desktop.py.
    echo Please make sure WorkSense files are in place.
    pause
    exit /b 1
)

cd /d "%TARGET_DIR%"
%PYTHON% %DESKTOP_SCRIPT%
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] WorkSense exited with error code %ERRORLEVEL%.
    pause
)
