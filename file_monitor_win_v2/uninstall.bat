@echo off
chcp 65001 >nul
title File Monitor v2 - Uninstall

echo.
echo =============================================
echo    File Monitor v2 - Uninstall Tool
echo =============================================
echo.

set "SCRIPT_DIR=%~dp0"

:: Kill running process
echo [1/5] Checking if FileMonitor is running...
taskkill /F /IM FileMonitorV2.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
echo     Done.

:: Remove build artifacts
echo [2/5] Removing build cache...
if exist "%SCRIPT_DIR%build" rmdir /S /Q "%SCRIPT_DIR%build"
if exist "%SCRIPT_DIR%__pycache__" rmdir /S /Q "%SCRIPT_DIR%__pycache__"
for /d %%i in ("%SCRIPT_DIR%__pycache__*") do rmdir /S /Q "%%i"
if exist "%SCRIPT_DIR%dist" rmdir /S /Q "%SCRIPT_DIR%dist"
if exist "%SCRIPT_DIR%file_monitor.spec" del /Q "%SCRIPT_DIR%file_monitor.spec"
echo     Done.

:: Remove compiled Python files
echo [3/5] Removing Python cache...
if exist "%SCRIPT_DIR%.git" (
    for /r "%SCRIPT_DIR%" %%f in (*.pyc) do del "%%f" 2>nul
    for /r "%SCRIPT_DIR%" %%d in (__pycache__) do rmdir /S /Q "%%d" 2>nul
)
echo     Done.

:: Remove logs folder
echo [4/5] Removing logs...
set "LOG_DIR=%USERPROFILE%\Documents\FileMonitorLogs"
if exist "%LOG_DIR%" rmdir /S /Q "%LOG_DIR%"
echo     Done.

:: Ask about Python dependencies
echo [5/5] Remove Python dependencies?
echo.
echo     flask, watchdog, psutil will be removed.
echo.
set /p choice="Remove Python packages? (y/n): "
if /i "%choice%"=="y" (
    python -m pip uninstall flask watchdog psutil -y >nul 2>&1
    echo.
    echo     Python packages removed.
) else (
    echo.
    echo     Python packages kept.
)

echo.
echo =============================================
echo   Uninstall Complete!
echo =============================================
echo.
pause