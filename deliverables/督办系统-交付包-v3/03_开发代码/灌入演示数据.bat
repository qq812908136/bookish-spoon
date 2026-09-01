@echo off
title 灌入演示数据
chcp 936 >nul 2>&1

echo ============================================
echo    督办系统 - 灌入演示数据
echo ============================================
echo.
echo [提示] 此操作将清空现有数据并灌入演示数据
echo [提示] 演示数据包含: 9个用户 + 45个任务 + 67条消息通知
echo.

cd /d %~dp0

REM 优先使用 WorkBuddy 托管 Python（确保依赖隔离）
set "PYTHON_EXE=C:\Users\王蓟冬\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

"%PYTHON_EXE%" app.py --seed-demo

echo.
pause
