@echo off
title 开启局域网访问权限
chcp 936 >nul 2>&1

echo ============================================
echo    开启局域网访问权限（防火墙放行）
echo ============================================
echo.

echo 本脚本只做一件事：在 Windows 防火墙上放行 5000 端口。
echo 它是「一次性」的，每台电脑运行一次即可。
echo.

REM 检查是否以管理员身份运行
net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 需要以管理员身份运行！
    echo.
    echo 请右键点击此文件，选择"以管理员身份运行"
    echo.
    pause
    exit /b 1
)

echo [1/2] 正在添加防火墙规则...
netsh advfirewall firewall delete rule name="督办系统-端口5000" >nul 2>&1
netsh advfirewall firewall add rule name="督办系统-端口5000" dir=in action=allow protocol=TCP localport=5000
if errorlevel 1 (
    echo [失败] 防火墙规则添加失败
    pause
    exit /b 1
)
echo [完成] 防火墙规则已添加

echo.
echo [2/2] 正在获取局域网 IP 地址...
ipconfig | findstr /i "IPv4" > %TEMP%\db_ipv4.txt
for /f "tokens=2 delims=:" %%a in (%TEMP%\db_ipv4.txt) do (
    set LAN_IP=%%a
    goto :got_ip
)
:got_ip
set LAN_IP=%LAN_IP: =%

echo.
echo ============================================
echo  防火墙已放行，接下来这样启动：
echo ============================================
echo.
echo   请关闭本窗口，然后双击「局域网启动.bat」
echo   （直接双击 start.bat 是本机模式，同事访问不到）
echo.
echo  启动后把下面这个地址发给同事：
echo.
echo      http://%LAN_IP%:5000
echo.
echo  前提：同事和你需要在同一个 WiFi / 局域网下
echo.
pause
