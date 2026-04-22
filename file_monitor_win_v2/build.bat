@echo off
chcp 65001 >nul
title File Monitor v2 - Build

echo.
echo =============================================
echo    File Monitor v2 - PyInstaller Build
echo =============================================
echo.

REM Try multiple Python commands
set PYTHON_CMD=
where python >nul 2>&1 && set PYTHON_CMD=python
if not defined PYTHON_CMD where python3 >nul 2>&1 && set PYTHON_CMD=python3
if not defined PYTHON_CMD where py >nul 2>&1 && set PYTHON_CMD=py
if not defined PYTHON_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python*" set PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python*\python.exe
    if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python*" set PYTHON_CMD=%USERPROFILE%\AppData\Local\Programs\Python\Python*\python.exe
)

if not defined PYTHON_CMD (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

echo [OK] Found Python

REM Install PyInstaller
echo [INFO] Installing PyInstaller...
"%PYTHON_CMD%" -m pip install pyinstaller -q
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

REM Build
echo [INFO] Building executable...
"%PYTHON_CMD%" -m PyInstaller file_monitor.spec --clean
if errorlevel 1 (
    echo [ERROR] Build failed.
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
pause