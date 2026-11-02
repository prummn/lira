@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -X utf8 -B "%~dp0lira.py" stop %*
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0
