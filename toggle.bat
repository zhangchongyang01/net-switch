@echo off
chcp 65001 >nul
rem One-click switch between wired and WiFi (UAC prompt will appear).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0NetSwitch.ps1" -Toggle
