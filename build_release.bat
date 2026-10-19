@echo off
rem SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
rem SPDX-License-Identifier: GPL-3.0-or-later
chcp 65001 >nul
cd /d "%~dp0"

set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCC where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC (
    echo Inno Setup was not found. Installing with winget...
    winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements --silent
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    echo ERROR: Inno Setup compiler is unavailable.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)

".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt

 echo Building application directory...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name "EdgeTTSGui" --icon "assets\app.ico" --collect-all tkinterdnd2 --hidden-import docx --hidden-import pypdf --hidden-import miniaudio --hidden-import lameenc --hidden-import cffi --hidden-import _cffi_backend app.py
if errorlevel 1 exit /b 1
if not exist "dist\EdgeTTSGui\EdgeTTSGui.exe" exit /b 1

 echo Building portable executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name "EdgeTTSGui-Portable" --icon "assets\app.ico" --collect-all tkinterdnd2 --hidden-import docx --hidden-import pypdf --hidden-import miniaudio --hidden-import lameenc --hidden-import cffi --hidden-import _cffi_backend app.py
if errorlevel 1 exit /b 1
if not exist "dist\EdgeTTSGui-Portable.exe" exit /b 1

 echo Building installer...
"%ISCC%" "installer\EdgeTTSGui.iss"
if errorlevel 1 exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\generate_checksums.ps1"
if errorlevel 1 exit /b 1

echo Build complete.
echo Installer: dist\EdgeTTSGui-Setup.exe
echo Portable:  dist\EdgeTTSGui-Portable.exe
echo Checksums: dist\SHA256SUMS.txt
