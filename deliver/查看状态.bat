@echo off
chcp 65001 >nul
rem Read-only: show adapters, metrics and the current active route.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0NetSwitch.ps1" -List
echo.
pause
