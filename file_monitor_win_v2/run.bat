@echo off
chcp 65001 >nul
title File Monitor v2

echo.
echo =============================================
echo    Windows File Monitor v2
echo =============================================
echo.

REM =============================================
REM Step 1: Find or Install Python
REM =============================================

set PYTHON_CMD=

REM Try to find existing Python
where python >nul 2>&1 && set PYTHON_CMD=python
if not defined PYTHON_CMD where python3 >nul 2>&1 && set PYTHON_CMD=python3
if not defined PYTHON_CMD where py >nul 2>&1 && set PYTHON_CMD=py

REM Check common installation paths
if not defined PYTHON_CMD (
    for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if exist "%%P\python.exe" set PYTHON_CMD=%%P\python.exe
    )
)
if not defined PYTHON_CMD (
    for /d %%P in ("%USERPROFILE%\AppData\Local\Programs\Python\Python*") do (
        if exist "%%P\python.exe" set PYTHON_CMD=%%P\python.exe
    )
)

REM Python not found - offer to install
if not defined PYTHON_CMD (
    echo [INFO] Python not found on this system.
    echo.
    echo This program requires Python 3.8 or higher.
    echo.
    echo Options:
    echo   1. Install Python automatically via winget (recommended)
    echo   2. Open download page in browser
    echo   3. Cancel
    echo.
    set /p choice="Choose option (1/2/3): "

    if /i "%choice%"=="1" (
        echo.
        echo [INFO] Installing Python via winget...
        echo [INFO] Please wait, this may take a few minutes...
        winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [ERROR] winget install failed.
            echo Please install Python manually from https://www.python.org/downloads/
            pause
            exit /b 1
        )
        echo.
        echo [OK] Python installed. Please run this script again.
        echo.
        pause
        exit /b 0
    )

    if /i "%choice%"=="2" (
        start https://www.python.org/downloads/
        echo.
        echo Please download and install Python, then run this script again.
        pause
        exit /b 0
    )

    echo Cancelled.
    pause
    exit /b 1
)

REM Check Python version
for /f "delims=" %%v in ('"%PYTHON_CMD%" --version 2^>nul') do set PY_VERSION=%%v
echo [OK] Found: %PY_VERSION%

REM =============================================
REM Step 2: Install Dependencies
REM =============================================

echo.
echo [INFO] Installing dependencies...
echo.

"%PYTHON_CMD%" -m pip install flask watchdog psutil --upgrade
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies.
    echo.
    set /p retry="Try again? (y/n): "
    if /i "!retry!"=="y" (
        "%PYTHON_CMD%" -m pip install flask watchdog psutil --upgrade
        if errorlevel 1 (
            echo [ERROR] Still failed. Please check your internet connection.
            pause
            exit /b 1
        )
    ) else (
        exit /b 1
    )
)

echo.
echo [OK] All dependencies installed.

REM =============================================
REM Step 3: Start Application
REM =============================================

echo.
echo [INFO] Starting File Monitor...
echo [INFO] Open http://localhost:5006 in your browser
echo.
echo =============================================
echo.

"%PYTHON_CMD%" app.py

pause