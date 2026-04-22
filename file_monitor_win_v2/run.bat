@echo off
chcp 65001 >nul
title File Monitor v2

REM =============================================
REM Windows File Monitor v2 - Launcher
REM =============================================

REM Get script directory and change to it (support UNC paths)
pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot access script directory.
    pause
    exit /b 1
)

echo.
echo =============================================
echo    Windows File Monitor v2
echo =============================================
echo.

REM Run Python launcher
python run.py

REM Restore original directory
popd

pause