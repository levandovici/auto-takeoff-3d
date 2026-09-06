@echo off
setlocal
pushd "%~dp0"

REM --- Try pythonw first (no console), then python ---
set "PYW="
for /f "delims=" %%p in ('where pythonw.exe 2^>nul') do (
    echo %%p | findstr /i "WindowsApps" >nul || (
        set "PYW=%%p"
        goto :found
    )
)

set "PY="
for /f "delims=" %%p in ('where python.exe 2^>nul') do (
    echo %%p | findstr /i "WindowsApps" >nul || (
        set "PY=%%p"
        goto :found
    )
)

echo [!] Python not found. Install Python and add it to PATH.
pause
exit /b 1

:found
if defined PYW (
    set "EXE=%PYW%"
    set "HIDDEN="
) else (
    set "EXE=%PY%"
    set "HIDDEN=-WindowStyle Hidden"
)

echo [i] Starting Auto Takeoff 3D modeler...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$proc=Start-Process -FilePath '%EXE%' -ArgumentList '%~dp0modeler.py' %HIDDEN% -PassThru;" ^
    "$sw=[Diagnostics.Stopwatch]::StartNew();" ^
    "while ($sw.Elapsed.TotalSeconds -lt 30 -and -not $proc.HasExited) {" ^
    "  $w=Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle -like '*Auto Takeoff 3D*'};" ^
    "  if ($w) { exit 0 };" ^
    "  Start-Sleep -Milliseconds 300" ^
    "};" ^
    "if ($proc.HasExited) { exit 1 };" ^
    "exit 0"

if errorlevel 1 echo [!] Modeler failed to start or exited before opening.
popd
exit /b 0
