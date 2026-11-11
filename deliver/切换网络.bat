@echo off
chcp 65001 >nul
rem Switch the active network between wired and WiFi. A UAC prompt will appear.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0NetSwitch.ps1" -Toggle
