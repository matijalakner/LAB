@echo off
rem Install the lab equipment on Windows (see install.ps1 for what it does).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
