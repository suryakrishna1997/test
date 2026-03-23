@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo Welcome to log fetcher
echo.

:: ===== Folder Name Input =====
set /p D=Please Enter Folder Name to capture logs and video:- 

if "%D%"=="" (
    echo No name entered.
    pause
    exit /b
)

:: ===== Create Folder Structure =====
mkdir "%D%"
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do (
    mkdir "%D%\%%F"
)

echo.
echo Detecting device...
echo.

adb devices

echo.
pause

:: ===== Get Connected Device =====
for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" (
        set DEVICE=%%A
    )
)

:: ===== Validate Device =====
if "!DEVICE!"=="" (
    echo No device detected! Please connect device and enable USB debugging.
    pause
    exit /b
)

echo Device detected: !DEVICE!
echo.

:: ===== Start Screen Recording =====
echo Starting screen recording...
echo.

start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\%D%.mkv"

echo Press any key to STOP recording...
pause >nul

taskkill /IM scrcpy.exe /F >nul 2>nul

echo.
echo Collecting logs...
echo.

:: ===== [1/4] Bugreport =====
echo [1/4] Bugreport...
adb bugreport "%D%"

:: ===== [2/4] Logcat =====
echo [2/4] Logcat...
adb logcat -d > "%D%\Logcat\logcat.txt"

:: ===== [3/4] Broadcast Logs =====
echo [3/4] Broadcast Logs...
adb shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0

echo Waiting to store logs...
timeout /t 5 >nul

:: ===== [4/4] Pull Logs =====
echo [4/4] Pulling logs...
adb pull /sdcard/ICB_Log "%D%" >nul 2>nul

:: ===== Move Bugreport =====
move "%D%\bugreport*zip" "%D%\Bugreport\" >nul 2>nul

:: ===== Process Pulled Logs =====
if exist "%D%\ICB_Log\" (

    :: HW Logs
    for /f "delims=" %%F in ('dir "%D%\ICB_Log\hw_err_*" /ad /b /o-n 2^>nul') do (
        move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
        goto :hw_done
    )
)

:hw_done

if exist "%D%\ICB_Log\" (
    :: SW Logs
    for /f "delims=" %%F in ('dir "%D%\ICB_Log\sw_err_*" /ad /b /o-n 2^>nul') do (
        move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
        goto :sw_done
    )
)

:sw_done

if exist "%D%\ICB_Log\" (
    :: Maker Logs
    for /f "delims=" %%F in ('dir "%D%\ICB_Log\makerLog_*" /ad /b /o-n 2^>nul') do (
        move "%D%\ICB_Log\%%F" "%D%\Maker_Logs\" >nul
        goto :mk_done
    )


:mk_done

:: ===== Cleanup =====
rd /s /q "%D%\ICB_Log" >nul 2>nul

:: ===== ZIP Creation (Exclude Video) =====
echo.
echo Creating ZIP (excluding Video folder)...

powershell -Command ^
"Compress-Archive -Path '%D%\Bugreport','%D%\Logcat','%D%\HS_Logs','%D%\Maker_Logs','%D%\MCU' ^
-DestinationPath '%D%\%D%.zip' -Force"

echo ZIP created: %D%\%D%.zip

echo.
echo Done! Logs saved in folder: %D%
echo ZIP file: %D%.zip
echo.

pause
