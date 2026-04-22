@echo off
chcp 65001 >nul
title File Monitor v2 - Uninstall

echo.
echo =============================================
echo    File Monitor v2 - Uninstall Tool
echo =============================================
echo.

set "SCRIPT_DIR=%~dp0"

REM =============================================
REM Step 1: Kill running process
REM =============================================
echo [1/5] Stopping FileMonitor...
taskkill /F /IM FileMonitorV2.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
echo     Done.

REM =============================================
REM Step 2: Remove build artifacts
REM =============================================
echo [2/5] Removing build cache...
if exist "%SCRIPT_DIR%build" rmdir /S /Q "%SCRIPT_DIR%build"
if exist "%SCRIPT_DIR%__pycache__" rmdir /S /Q "%SCRIPT_DIR%__pycache__"
for /d %%i in ("%SCRIPT_DIR%__pycache__*") do rmdir /S /Q "%%i"
if exist "%SCRIPT_DIR%dist" rmdir /S /Q "%SCRIPT_DIR%dist"
if exist "%SCRIPT_DIR%file_monitor.spec" del /Q "%SCRIPT_DIR%file_monitor.spec"
echo     Done.

REM =============================================
REM Step 3: Remove Python cache files
REM =============================================
echo [3/5] Removing Python cache...
for /r "%SCRIPT_DIR%" %%f in (*.pyc) do del "%%f" 2>nul
for /r "%SCRIPT_DIR%" %%d in (__pycache__) do rmdir /S /Q "%%d" 2>nul
echo     Done.

REM =============================================
REM Step 4: Remove logs folder
REM =============================================
echo [4/5] Removing logs...
set "LOG_DIR=%USERPROFILE%\Documents\FileMonitorLogs"
if exist "%LOG_DIR%" rmdir /S /Q "%LOG_DIR%"
echo     Done.

REM =============================================
REM Step 5: Ask about Python packages
REM =============================================
echo [5/5] Remove Python packages?
echo.
echo     This will uninstall: flask, watchdog, psutil
echo     Python itself will remain installed.
echo.
set /p choice="Remove Python packages? (y/n): "
if /i "%choice%"=="y" (
    REM Try to find Python
    set PYTHON_CMD=
    where python >nul 2>&1 && set PYTHON_CMD=python
    if not defined PYTHON_CMD where py >nul 2>&1 && set PYTHON_CMD=py

    if defined PYTHON_CMD (
        echo.
        echo [INFO] Uninstalling Python packages...
        "%PYTHON_CMD%" -m pip uninstall flask watchdog psutil -y >nul 2>&1
        echo [OK] Python packages removed.
    ) else (
        echo [INFO] Python not found, skipping package removal.
    )
) else (
    echo [INFO] Python packages kept.
)

echo.
echo =============================================
echo   Uninstall Complete!
echo =============================================
echo.
echo Note: To completely remove Python, use Windows Settings
echo       > Apps > Python > Uninstall
echo.
pause