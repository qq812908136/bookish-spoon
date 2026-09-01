@echo off
title 督办系统 - 打包

echo ============================================
echo    督办系统 打包工具 (PyInstaller)
echo ============================================
echo.

cd /d %~dp0

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 安装打包依赖
echo [步骤 1/3] 检查并安装依赖...
pip install -r requirements.txt
echo.

REM 使用 PyInstaller 打包（onedir 模式，生成文件夹）
echo [步骤 2/3] 开始打包 (onedir 模式)...
pyinstaller --noconfirm --onedir --name 督办系统 ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --hidden-import flask ^
    --hidden-import openpyxl ^
    app.py

echo.
echo [步骤 3/3] 打包完成！
echo 输出目录: dist\督办系统\
echo.
echo 使用方法: 将 dist\督办系统\ 文件夹复制到目标电脑，
echo 双击其中的 督办系统.exe 即可运行。
echo.
pause
