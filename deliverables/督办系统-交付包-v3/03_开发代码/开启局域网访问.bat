@echo off
title 开启局域网访问权限
chcp 936 >nul 2>&1

echo ============================================
echo    开启局域网访问权限
echo ============================================
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

REM 添加防火墙规则
echo [1/2] 正在添加防火墙规则...
netsh advfirewall firewall delete rule name="督办系统-端口5000" >nul 2>&1
netsh advfirewall firewall add rule name="督办系统-端口5000" dir=in action=allow protocol=TCP localport=5000
if errorlevel 1 (
    echo [失败] 防火墙规则添加失败
    pause
    exit /b 1
)
echo [完成] 防火墙规则已添加

REM 获取局域网IP：先用ipconfig过滤出IPv4行，再提取地址
echo.
echo [2/2] 正在获取局域网IP地址...

ipconfig | findstr /i "IPv4" > %TEMP%\db_ipv4.txt
for /f "tokens=2 delims=:" %%a in (%TEMP%\db_ipv4.txt) do (
    set LAN_IP=%%a
    goto :got_ip
)
:got_ip
set LAN_IP=%LAN_IP: =%

echo.
echo ============================================
echo  局域网访问已开启！
echo ============================================
echo.
echo  本机访问:   http://127.0.0.1:5000
echo  局域网访问: http://%LAN_IP%:5000
echo.
echo  把"局域网访问"这个地址发给同事
echo  他们在浏览器输入即可打开系统
echo.
echo  前提: 你的电脑要先启动督办系统
echo  且同事和你需要在同一个WiFi/局域网下
echo.
pause
