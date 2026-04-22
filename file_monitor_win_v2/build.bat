@echo off
chcp 65001 >nul
title File Monitor v2 - Build

REM Change to script directory (support UNC paths)
pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot access script directory.
    pause
    exit /b 1
)

echo.
echo =============================================
echo    File Monitor v2 - PyInstaller Build
echo =============================================
echo.

REM Find Python
set PYTHON_CMD=
where python >nul 2>&1 && set PYTHON_CMD=python
if not defined PYTHON_CMD where py >nul 2>&1 && set PYTHON_CMD=py

if not defined PYTHON_CMD (
    echo [ERROR] Python not found.
    echo Please run run.bat first to install dependencies.
    popd
    pause
    exit /b 1
)

REM Install PyInstaller
echo [INFO] Installing PyInstaller...
%PYTHON_CMD% -m pip install pyinstaller -q
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    popd
    pause
    exit /b 1
)

REM Build
echo [INFO] Building executable...
%PYTHON_CMD% -m PyInstaller file_monitor.spec --clean
if errorlevel 1 (
    echo [ERROR] Build failed.
    popd
    pause
    exit /b 1
)

echo.
echo =============================================
echo [OK] Build complete!
echo [OK] Output: dist\FileMonitorV2\FileMonitorV2.exe
echo.
echo To run:
echo   cd dist\FileMonitorV2
echo   FileMonitorV2.exe
echo =============================================

popd
pause