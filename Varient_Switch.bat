@echo off
setlocal EnableDelayedExpansion

set /p VAR=Enter Variant Code: 

set FOUND=0
set LINE1=
set LINE2=
set TYPE=
set COUNT=0

:: Search in data.txt
for /f "delims=" %%A in (data.txt) do (

    if "!FOUND!"=="1" (
        if !COUNT!==0 set LINE1=%%A
        if !COUNT!==1 set LINE2=%%A
        set /a COUNT+=1
    )

    echo %%A | findstr /B /I "%VAR%" >nul
    if !errorlevel! == 0 (
        set FOUND=1
        set COUNT=0

        :: Extract type (Q, S, R1 etc)
        for /f "tokens=2 delims=()" %%T in ("%%A") do set TYPE=%%T
    )
)

:: If not found
if "%FOUND%"=="0" (
    echo.
    echo  Variant not found!
    pause
    exit /b
)

:: Display details
echo.
echo ==========================================
echo Variant: %VAR%
echo Type: %TYPE%
echo ==========================================
echo %LINE1%
echo %LINE2%

:: Extract HW value
for /f "tokens=6" %%H in ("%LINE2%") do set HW=%%H

echo.
echo ==========================================
echo   WARNING
echo ==========================================
echo Please verify the hardware variant type: %TYPE%
echo.
echo If the variant is incorrect,
echo.
echo ICB may display "Please consult your dealer" message.
echo.
echo Make sure you have selected the correct variant.
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
    echo  No device connected!
    echo Please connect device and enable USB debugging.
    pause
    exit /b
)

echo  Device connected.
echo.

:: Execute commands
echo Executing commands...

adb shell setprop vendor.apn.sys.set.hw.variation %HW%
adb shell setprop vendor.apn.sys.set.variant.code %VAR%

echo.
echo Variant switch completed successfully.
echo Your device will reboot in 5 seconds...
timeout /t 5 >nul

adb reboot

echo.
echo  Flashing completed successfully!
pause