@echo off
chcp 65001 >nul
title File Monitor v2

echo.
echo =============================================
echo    Windows File Monitor v2
echo =============================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+ first.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Install dependencies
echo [INFO] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

REM Start the application
echo.
echo [INFO] Starting File Monitor...
echo [INFO] Open http://localhost:5006 in your browser
echo.
python app.py

pause