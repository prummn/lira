@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -X utf8 -B "%~dp0lira.py" start %*
if errorlevel 1 (
    echo.
    echo 启动失败。请把上面的错误信息发给提供此工具的同学。
    pause
    exit /b 1
)
exit /b 0
