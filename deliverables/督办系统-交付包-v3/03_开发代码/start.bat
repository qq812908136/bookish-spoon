@echo off
title 督办系统
chcp 936 >nul 2>&1

echo ============================================
echo    督办系统 启动中...
echo ============================================
echo.

cd /d %~dp0

REM 获取局域网IP：先用ipconfig过滤出IPv4行，再提取地址（避免wmic的IPv6数组问题）
ipconfig | findstr /i "IPv4" > %TEMP%\db_ipv4.txt
for /f "tokens=2 delims=:" %%a in (%TEMP%\db_ipv4.txt) do (
    set LAN_IP=%%a
    goto :got_ip
)
:got_ip
set LAN_IP=%LAN_IP: =%

REM 优先使用 WorkBuddy 托管 Python（确保依赖隔离），找不到时 fallback 到系统 python
set "PYTHON_EXE=C:\Users\王蓟冬\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo [启动] 本机访问:   http://127.0.0.1:5000
echo [启动] 局域网访问: http://%LAN_IP%:5000
echo [提示] 启动后请勿关闭此窗口，关闭即停止服务
echo [提示] 把局域网地址发给同事，他们在浏览器输入即可访问
echo.

"%PYTHON_EXE%" app.py

pause
