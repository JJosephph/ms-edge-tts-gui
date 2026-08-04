@echo off
chcp 65001 >nul
title Edge TTS 语音合成助手
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [首次运行] 正在创建虚拟环境...
    py -3 -m venv .venv
    echo [首次运行] 正在安装依赖，请稍候...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo 启动 Edge TTS 语音合成助手...
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
