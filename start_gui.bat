@echo off
cd /d "%~dp0"
set "GUI=%~dp0net_switch_gui.py"
rem Prefer the py launcher: it resolves to the system Python that ships tkinter.
rem WorkBuddy's bundled Python has no tkinter, so avoid a silent pythonw failure.
where py >nul 2>nul
if errorlevel 1 goto NOPY
py -3 -c "import tkinter" >nul 2>nul
if errorlevel 1 goto NOTK

:NOPY
where pyw >nul 2>nul
if errorlevel 1 goto NOPYW
start "" pyw -3 "%GUI%"
goto :EOF

:NOPYW
where pythonw >nul 2>nul
if errorlevel 1 goto NOPYTHONW
start "" pythonw "%GUI%"
goto :EOF

:NOPYTHONW
python "%GUI%"
goto :EOF

:NOTK
echo [ERROR] tkinter is missing in the current Python 3.
echo         Use the system Python, or just run status.bat / toggle.bat / reset.bat.
pause
