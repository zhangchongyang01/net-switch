@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Building a single-file EXE for colleagues (needs internet for PyInstaller)...
echo.

py -3 -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo PyInstaller not found, installing...
    py -3 -m pip install pyinstaller
)

py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin --name NetSwitch --add-data "NetSwitch.ps1;." net_switch_gui.py

echo.
if exist "dist\NetSwitch.exe" (
    echo OK: dist\NetSwitch.exe
    echo Copy ONLY this EXE to your colleague. It already contains NetSwitch.ps1.
) else (
    echo Build failed. Fallback: send NetSwitch.ps1 + toggle.bat + status.bat instead.
)
pause
