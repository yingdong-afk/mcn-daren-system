@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo 请先安装 Python 3.12，安装后重新双击本文件。
    echo 下载页面：https://www.python.org/downloads/release/python-31210/
    start "" "https://www.python.org/downloads/release/python-31210/"
    pause
    exit /b 1
)
py -3.12 scripts/local_launcher.py
if errorlevel 1 (
    echo 启动未完成，请保留上面的错误提示。
    pause
)
