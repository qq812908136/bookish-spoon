@echo off
title 督办系统 - 数据备份
chcp 936 >nul 2>&1
cd /d %~dp0

echo ============================================
echo    督办系统 数据备份
echo ============================================
echo.

REM 用 PowerShell 取本地时间戳（跨区域格式稳定），形如 20260901_135622
for /f "tokens=*" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"

set "SRC=data"
set "DST=backups\%STAMP%"

if not exist "%SRC%\" (
    echo [错误] 未找到 data 目录，请在督办系统所在目录运行本脚本
    pause
    exit /b 1
)

if not exist "%DST%\" mkdir "%DST%"

set "N=0"
if exist "%SRC%\supervision.db" (
    copy /Y "%SRC%\supervision.db" "%DST%\supervision.db" >nul
    set /a N+=1
)
if exist "%SRC%\secret.key" (
    copy /Y "%SRC%\secret.key" "%DST%\secret.key" >nul
    set /a N+=1
)

echo [完成] 已备份 %N% 个文件到: %DST%
echo [说明] supervision.db = 业务数据(用户/任务/消息)
echo         secret.key    = 会话签名密钥(丢了只需重新登录，不丢数据)
echo [提示] 用 Windows 任务计划程序定时调用本脚本即可实现定期备份
echo         计划任务里请写成: 备份数据.bat nopause
echo.
if "%~1"=="nopause" goto :eof
pause
