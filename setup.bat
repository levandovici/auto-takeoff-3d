@echo off
REM Register Takeoff Auto 3D as the default program for .toff files.
REM Right-click this file and choose "Run as administrator".
setlocal enabledelayedexpansion
set "ROOT=%~dp0"

:: Require admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Please run this file as Administrator.
    pause
    exit /b 1
)

:: Ensure the Windows Python launcher is available
where pyw >nul 2>&1
if %errorlevel% neq 0 (
    echo Python launcher ^(pyw^) was not found in PATH.
    echo Install Python and make sure it is added to the system PATH, then run this script again.
    pause
    exit /b 1
)

:: Ensure the launcher exists
if not exist "%ROOT%open_toff.bat" (
    echo open_toff.bat not found in %ROOT%
    pause
    exit /b 1
)

:: Register ProgID in HKCR (machine-wide)
reg add "HKEY_CLASSES_ROOT\TakeOffRoofPlan" /ve /d "TakeOff Roof Plan" /f >nul 2>&1
reg add "HKEY_CLASSES_ROOT\TakeOffRoofPlan\DefaultIcon" /ve /d "\"%ROOT%auto_takeoff_3d.ico\"" /f >nul 2>&1
reg add "HKEY_CLASSES_ROOT\TakeOffRoofPlan\shell\open\command" /ve /d "\"%ROOT%open_toff.bat\" \"%%1\"" /f >nul 2>&1

:: Register ProgID in HKCU (user-specific, takes precedence over HKCR)
reg add "HKEY_CURRENT_USER\Software\Classes\TakeOffRoofPlan" /ve /d "TakeOff Roof Plan" /f >nul 2>&1
reg add "HKEY_CURRENT_USER\Software\Classes\TakeOffRoofPlan\DefaultIcon" /ve /d "\"%ROOT%auto_takeoff_3d.ico\"" /f >nul 2>&1
reg add "HKEY_CURRENT_USER\Software\Classes\TakeOffRoofPlan\shell\open\command" /ve /d "\"%ROOT%open_toff.bat\" \"%%1\"" /f >nul 2>&1

:: Bind .toff extension to TakeOffRoofPlan ProgID in both HKCR and HKCU
reg add "HKEY_CLASSES_ROOT\.toff" /ve /d "TakeOffRoofPlan" /f >nul 2>&1
reg add "HKEY_CURRENT_USER\Software\Classes\.toff" /ve /d "TakeOffRoofPlan" /f >nul 2>&1

:: Register our ProgID as an approved "Open with" choice
reg add "HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.toff\OpenWithProgids" /v "TakeOffRoofPlan" /t REG_NONE /f >nul 2>&1

:: Remove any old Windows "Open With" user choice / file-ext settings that block the association
reg delete "HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.toff" /f >nul 2>&1

:: Also run assoc/ftype so the live shell cache is updated
assoc .toff=TakeOffRoofPlan >nul 2>&1
ftype TakeOffRoofPlan="%ROOT%open_toff.bat" "%%1" >nul 2>&1

:: Refresh Explorer so the new icon/association appears immediately
ie4uinit.exe -show >nul 2>&1
powershell -NoProfile -Command "Add-Type -MemberDefinition '[DllImport(\"shell32.dll\")] public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);' -Name Shell32 -Namespace WinAPI -PassThru | Out-Null; [WinAPI.Shell32]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)" >nul 2>&1

echo .toff files are now associated with Takeoff Auto 3D.
echo You can double-click any .toff file to open it.
pause
