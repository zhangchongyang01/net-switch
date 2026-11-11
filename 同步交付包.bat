@echo off
chcp 65001 >nul
rem Refresh the delivery snapshot after editing NetSwitch.ps1 in the main folder.
copy /Y "%~dp0NetSwitch.ps1" "%~dp0deliver\NetSwitch.ps1" >nul
if errorlevel 1 (
    echo [ERROR] Failed to sync deliver\NetSwitch.ps1
) else (
    echo [OK] deliver\NetSwitch.ps1 is now up to date.
)
echo.
pause
