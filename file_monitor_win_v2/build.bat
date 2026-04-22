@echo off
chcp 65001 >nul
title File Monitor v2 - Build

echo.
echo =============================================
echo    File Monitor v2 - PyInstaller Build
echo =============================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

REM Install PyInstaller
echo [INFO] Installing PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

REM Create spec file
echo [INFO] Creating spec file...
(
echo # -*- mode: python ; coding: utf-8 -*-
echo import sys
echo import os
echo 
echo # Add templates folder
echo TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))), 'templates')
echo 
echo a = Analysis(
echo     ['app.py'],
echo     pathex=[],
echo     binaries=[],
echo     datas=[
echo         (TEMPLATES, 'templates'),
echo     ],
echo     hiddenimports=[],
echo     hookspath=[],
echo     hooksconfig={},
echo     runtime_hooks=[],
echo     excludes=[],
echo     noarchive=False,
echo )
echo 
echo pyz = PYZ(a.pure)
echo 
echo exe = EXE(
echo     pyz,
echo     a.scripts,
echo     [],
echo     exclude_binaries=True,
echo     name='FileMonitorV2',
echo     debug=False,
echo     bootloader_ignore_signals=False,
echo     strip=False,
echo     upx=True,
echo     console=True,
echo     disable_windowed_traceback=False,
echo )
echo 
echo coll = COLLECT(
echo     exe,
echo     a.binaries,
echo     a.datas,
echo     strip=False,
echo     upx=True,
echo     upx_exclude=[],
echo     name='FileMonitorV2',
echo )
) > file_monitor.spec

REM Build
echo [INFO] Building executable...
python -m PyInstaller file_monitor.spec --clean
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