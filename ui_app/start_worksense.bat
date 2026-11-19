@echo off
title WorkSense — Burnout Prevention Platform
echo.
echo  ██╗    ██╗ ██████╗ ██████╗ ██╗  ██╗███████╗███████╗███╗   ██╗███████╗███████╗
echo  ██║    ██║██╔═══██╗██╔══██╗██║ ██╔╝██╔════╝██╔════╝████╗  ██║██╔════╝██╔════╝
echo  ██║ █╗ ██║██║   ██║██████╔╝█████╔╝ ███████╗█████╗  ██╔██╗ ██║███████╗█████╗  
echo  ██║███╗██║██║   ██║██╔══██╗██╔═██╗ ╚════██║██╔══╝  ██║╚██╗██║╚════██║██╔══╝  
echo  ╚███╔███╔╝╚██████╔╝██║  ██║██║  ██╗███████║███████╗██║ ╚████║███████║███████╗
echo   ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝╚══════╝╚══════╝
echo.
echo  Early-Warning Burnout Prevention — FLAME University Research Prototype
echo  -----------------------------------------------------------------------
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

REM Check if model weights exist
if not exist "..\Metric_data\model\worksense_nn.pt" (
    echo [WARNING] Pretrained model not found. Run scripts\train_burnout_model.py first.
    echo.
)

echo [1/3] Starting WorkSense application server...
echo       API:    http://localhost:8000/docs
echo       App:    http://localhost:8000
echo.
echo [2/3] Loading PyTorch model and dataset (this takes ~10 seconds)...
echo.

REM Start server in background and wait for startup
start /b "" %PYTHON% -m uvicorn server:app --host 127.0.0.1 --port 8000 --log-level warning

REM Wait for server to be ready
timeout /t 12 /nobreak > nul

REM Open browser
echo [3/3] Opening WorkSense in your browser...
start "" "http://localhost:8000"

echo.
echo  ✓ WorkSense is running at http://localhost:8000
echo  ✓ Press CTRL+C or close this window to stop the server
echo.

REM Keep window alive so server stays running
%PYTHON% -m uvicorn server:app --host 127.0.0.1 --port 8000 --log-level warning 2>nul
pause
