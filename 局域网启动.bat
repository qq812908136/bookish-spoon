@echo off
title 督办系统 - 局域网模式
chcp 936 >nul 2>&1

echo ============================================
echo    督办系统 启动中（局域网模式）...
echo ============================================
echo.

echo [注意] 本模式会把系统开放给同一网络内的所有设备。
echo        请确认当前网络可信（公司内网 / 家庭网络），
echo        不要在公共 WiFi 或不信任的网络下使用。
echo.

REM 获取局域网 IP：先用 ipconfig 过滤出 IPv4 行，再提取地址
ipconfig | findstr /i "IPv4" > %TEMP%\db_ipv4.txt
for /f "tokens=2 delims=:" %%a in (%TEMP%\db_ipv4.txt) do (
    set LAN_IP=%%a
    goto :got_ip
)
:got_ip
set LAN_IP=%LAN_IP: =%

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

echo [模式] 局域网访问
echo [启动] 本机访问:   http://127.0.0.1:5000
echo [启动] 局域网访问: http://%LAN_IP%:5000
echo.
echo [提示] 同事打不开？多半是防火墙没放行
echo        请以管理员身份运行一次「开启局域网访问.bat」
echo [提示] 启动后请勿关闭此窗口，关闭即停止服务
echo.

REM 关键一步：显式把监听地址开放到所有网卡
set HOST=0.0.0.0

"%RUN_BIN%" %RUN_ARGS%

pause
