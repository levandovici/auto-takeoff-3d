@echo off
REM Launcher for .toff files - opens a TakeOff roof plan in the modeler GUI.
setlocal
set "ROOT=%~dp0"
start "" pyw -3 "%ROOT%main.py" "%~1"
endlocal
