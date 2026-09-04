@echo off
title 督办系统
chcp 936 >nul 2>&1

echo ============================================
echo    督办系统 启动中...
echo ============================================
echo.

echo [模式] 本机访问 —— 只有这台电脑能打开（默认，最安全）
echo [启动] 请在浏览器打开: http://127.0.0.1:5000
echo.
echo [提示] 要让同事也能访问？
echo        1) 先以管理员身份运行一次「开启局域网访问.bat」放开防火墙
echo        2) 然后改用「局域网启动.bat」启动本系统
echo.
echo [提示] 启动后请勿关闭此窗口，关闭即停止服务
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

"%RUN_BIN%" %RUN_ARGS%

pause
