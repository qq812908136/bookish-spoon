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

REM ---- 运行方式自适应：有 exe 走离线模式，否则用 Python 跑源码 ----
if exist "%~dp0督办系统.exe" goto :use_exe

REM 源码模式：优先用 WorkBuddy 托管 Python（依赖隔离），找不到则回退系统 python
set "PYTHON_EXE=C:\Users\王蓟冬\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "RUN_BIN=%PYTHON_EXE%"
set "RUN_ARGS=src\app.py"
goto :runner_ready

:use_exe
set "RUN_BIN=%~dp0督办系统.exe"
set "RUN_ARGS="

:runner_ready

"%RUN_BIN%" %RUN_ARGS% --seed-demo

echo.
pause
