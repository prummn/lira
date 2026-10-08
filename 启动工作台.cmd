@echo off
chcp 65001 >nul
title Research Intelligence Workspace
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Check the logs in .local-runtime.
  pause
  exit /b 1
)
echo.
echo Workspace started. Browser: http://127.0.0.1:5173
pause
