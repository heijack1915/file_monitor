@echo off
chcp 65001 >nul
title File Monitor v2 - Uninstall

REM Change to script directory (support UNC paths)
pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot access script directory.
    pause
    exit /b 1
)

echo.
echo =============================================
echo    File Monitor v2 - Uninstall Tool
echo =============================================
echo.

REM Kill running process
echo [1/5] Stopping FileMonitor...
taskkill /F /IM FileMonitorV2.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
echo     Done.

REM Remove build artifacts
echo [2/5] Removing build cache...
if exist "build" rmdir /S /Q "build"
if exist "__pycache__" rmdir /S /Q "__pycache__"
for /d %%i in ("__pycache__*") do rmdir /S /Q "%%i"
if exist "dist" rmdir /S /Q "dist"
if exist "file_monitor.spec" del /Q "file_monitor.spec"
echo     Done.

REM Remove Python cache files
echo [3/5] Removing Python cache...
for /r "." %%f in (*.pyc) do del "%%f" 2>nul
for /r "." %%d in (__pycache__) do rmdir /S /Q "%%d" 2>nul
echo     Done.

REM Remove logs folder
echo [4/5] Removing logs...
set "LOG_DIR=%USERPROFILE%\Documents\FileMonitorLogs"
if exist "%LOG_DIR%" rmdir /S /Q "%LOG_DIR%"
echo     Done.

REM Remove this script folder
echo [5/5] Removing program folder...
popd
cd /d "%~dp0"
echo.
echo This will delete the FileMonitor folder.
set /p confirm="Continue? (y/n): "
if /i "!confirm!"=="y" (
    cd /d "%USERPROFILE%"
    rmdir /S /Q "%~dp0"
    echo [OK] Folder removed.
) else (
    echo Cancelled.
)

echo.
echo =============================================
echo   Uninstall Complete!
echo =============================================
pause