@echo off
chcp 65001 >nul
rem Read-only: list adapters, metrics and current default route.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0NetSwitch.ps1" -List
echo.
pause
