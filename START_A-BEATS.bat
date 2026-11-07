@echo off
setlocal
cd /d "%~dp0"
title A-BEATS Launcher
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_and_run.ps1"
if errorlevel 1 (
  echo.
  echo A-BEATS could not be started. See the message above.
  pause
)
endlocal
