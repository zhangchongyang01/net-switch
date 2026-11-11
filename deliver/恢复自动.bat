@echo off
chcp 65001 >nul
rem Restore Windows automatic interface metrics. Run this when you stop using the tool.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0NetSwitch.ps1" -Reset
