@echo off
title 督办系统（生产模式）
chcp 936 >nul 2>&1
cd /d %~dp0

echo ============================================
echo    督办系统 生产模式启动
echo ============================================
echo.

REM 启动前先备份一次数据，避免升级或异常导致数据损坏
echo [步骤1] 备份当前数据...
call 备份数据.bat nopause
echo.

REM ---- 生产配置（详见 docs/生产部署指南.md）----
REM 使用 Waitress 生产级 WSGI 服务器（需先 pip install waitress；未装会自动回退）
set SERVER=waitress

REM 监听端口（默认 5000，被占用改这里）
set PORT=5000

REM 监听地址：反向代理(Caddy/Nginx)后运行，只监听本机最安全
set HOST=127.0.0.1

REM 启用 HTTPS 后务必开启（否则会话 Cookie 明文传输，且可能无法登录）
REM set SESSION_COOKIE_SECURE=true

REM 反向代理后必须开启，TRUSTED_HOPS 必须等于实际代理层数（Caddy 为 1）
REM set BEHIND_PROXY=true
REM set BEHIND_PROXY_TRUSTED_HOPS=1

echo [步骤2] 以 Waitress 启动服务（HTTP 监听 %HOST%:%PORT%）...
echo [提示] 启动后请勿关闭此窗口；外部访问请经 Caddy/Nginx 反向代理转发
echo.

REM ---- 运行方式自适应：有 exe 走离线模式，否则用 Python 跑源码 ----
if exist "%~dp0督办系统.exe" goto :use_exe

set "PYTHON_EXE=C:\Users\王蓟冬\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
"%PYTHON_EXE%" src\app.py
goto :eof

:use_exe
"%~dp0督办系统.exe"
