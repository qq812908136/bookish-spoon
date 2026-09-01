@echo off
title 清除所有数据
chcp 936 >nul 2>&1

echo ============================================
echo    督办系统 - 清除所有数据
echo ============================================
echo.

echo [警告] 此操作将删除所有用户、任务、消息数据！
echo [警告] 清除后系统将恢复到初始状态（需重新创建管理员）
echo.
echo 确认要清除吗？按 Ctrl+C 取消，或按任意键继续...
pause >nul

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

"%RUN_BIN%" %RUN_ARGS% --clear-demo

echo.
pause
