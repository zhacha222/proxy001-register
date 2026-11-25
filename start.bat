@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ========================================================
echo   proxy001 一键注册机
echo ========================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 找不到 python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [*] 检查依赖...
python -c "import requests, cryptography" >nul 2>&1
if errorlevel 1 (
    echo [*] 首次运行，安装依赖...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

echo.
python run.py %*

echo.
pause
