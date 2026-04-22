@echo off
chcp 65001 >nul 2>&1
title File Monitor v2

pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot access directory.
    pause
    exit /b 1
)

echo.
echo ============================================
echo    Windows File Monitor v2
echo ============================================
echo.

python -c "import sys; exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python
    goto :install_deps
)

py -c "import sys; exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=py
    goto :install_deps
)

echo [INFO] Python 3.8+ not found on this system.
echo.

REM Detect CPU architecture
set ARCH_LABEL=x64
set WINGET_ID=Python.Python.3.11
set DOWNLOAD_URL=https://www.python.org/downloads/

if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set ARCH_LABEL=ARM64
    set WINGET_ID=Python.Python.3.11
    set DOWNLOAD_URL=https://www.python.org/downloads/
)
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" (
    if not defined PROCESSOR_ARCHITEW6432 (
        set ARCH_LABEL=x86 (32-bit)
        set WINGET_ID=Python.Python.3.11
        set DOWNLOAD_URL=https://www.python.org/downloads/
    )
)

echo [INFO] CPU architecture detected: %ARCH_LABEL%
echo.
echo   1 - Install Python 3.11 (%ARCH_LABEL%) via winget (recommended)
echo   2 - Open Python download page (manual)
echo   3 - Exit
echo.
set /p CHOICE=Choose (1/2/3):

if "%CHOICE%"=="1" goto :winget_install
if "%CHOICE%"=="2" goto :open_download
echo [INFO] Cancelled.
pause
exit /b 1

:winget_install
echo.
echo [INFO] Detected: %ARCH_LABEL%
echo [INFO] Installing %WINGET_ID% via winget, please wait...
echo.
winget install %WINGET_ID% --architecture %ARCH_LABEL% --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo [WARN] winget install with --architecture failed, retrying without flag...
    winget install %WINGET_ID% --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] winget install failed.
        echo [INFO] Please install manually: %DOWNLOAD_URL%
        pause
        exit /b 1
    )
)
echo.
echo [OK] Python installed successfully.
echo [INFO] Please close this window and run the script again to start the monitor.
pause
exit /b 0

:open_download
start %DOWNLOAD_URL%
echo [INFO] After installing Python, run this script again.
echo [INFO] Make sure to check "Add Python to PATH" during install.
pause
exit /b 0

:install_deps
echo [OK] Python: %PYTHON_CMD%
echo.
echo [INFO] Installing dependencies (flask / watchdog / psutil)...
%PYTHON_CMD% -m pip install flask watchdog psutil -q --disable-pip-version-check
if errorlevel 1 (
    echo [WARN] Some dependencies may have failed. Trying again...
    %PYTHON_CMD% -m pip install flask watchdog psutil
)
echo [OK] Dependencies ready.
echo.
echo [INFO] Starting File Monitor...
echo [INFO] Open http://localhost:5006 in your browser
echo [INFO] Press Ctrl+C to stop.
echo.
%PYTHON_CMD% app.py

popd
echo.
pause
