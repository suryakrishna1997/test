@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
set /p VAR=Enter Variant Code: 

set FOUND=0
set TYPE=
set LINE1=
set LINE2=

echo.
echo Searching variant...

:: Fast search using findstr (case-insensitive)
for /f "delims=" %%A in ('findstr /I /B "%VAR%" data.txt') do (
    set FOUND=1
    set MATCH_LINE=%%A

    :: Extract TYPE (inside brackets)
    for /f "tokens=2 delims=()" %%T in ("%%A") do set TYPE=%%T
)

:: If not found
if "%FOUND%"=="0" (
    echo.
    echo Variant not found!
    pause
    exit /b
)

:: Get next two lines after match
set COUNT=0
for /f "delims=" %%A in (data.txt) do (
    if defined MATCH_LINE (
        if "%%A"=="!MATCH_LINE!" (
            set COUNT=1
        ) else if !COUNT! GEQ 1 (
            if !COUNT!==1 set LINE1=%%A
            if !COUNT!==2 set LINE2=%%A
            set /a COUNT+=1
        )
    )
)

:: Extract HW from LINE2
for /f "tokens=6" %%H in ("%LINE2%") do set HW=%%H

:: Display info
echo.
echo ==========================================
echo Variant: %VAR%
echo Type: %TYPE%
echo ==========================================
echo %LINE1%
echo %LINE2%

echo.
echo ==========================================
echo   WARNING
echo ==========================================
echo Please verify the hardware variant type: %TYPE%
echo.
echo If the variant is incorrect,
echo ICB may display "Please consult your dealer".
echo ==========================================
echo.

set /p CONFIRM=Proceed with flashing? (Y/N): 

if /I "%CONFIRM%" NEQ "Y" (
    echo.
    echo Operation cancelled.
    pause
    exit /b
)

:: Check device
echo.
echo Checking device connection...

adb devices | findstr /R /C:"device$" >nul

if errorlevel 1 (
    echo No device connected!
    pause
    exit /b
)

echo Device connected.
echo.

:: Execute commands
echo Executing commands...

adb shell setprop vendor.apn.sys.set.hw.variation %HW%
adb shell setprop vendor.apn.sys.set.variant.code %VAR%

echo.
echo Variant switch completed successfully.
echo Rebooting in 5 seconds...
timeout /t 5 >nul

adb reboot

echo.
echo Flashing completed successfully!
pause