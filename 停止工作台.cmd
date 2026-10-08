@echo off
chcp 65001 >nul
title Stop Research Intelligence Workspace
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
if errorlevel 1 (
  echo.
  echo Stop failed. Check the logs in .local-runtime.
  pause
  exit /b 1
)
echo.
pause
