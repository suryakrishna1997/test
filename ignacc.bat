@echo off
setlocal EnableDelayedExpansion
mode con: cols=150 lines=40
title Log Fetcher Tool
cd /d "%~dp0"

echo ==========================================
echo   Log and Video Recorder Tool
echo ==========================================
echo.

:: ===== INPUT =====
set /p D=Enter folder name: 
if not defined D (
    echo No name entered
    pause
    exit
)

:: ===== CREATE FOLDERS =====
mkdir "%D%" 2>nul
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do mkdir "%D%\%%F"

:: ===== DEVICE DETECTION =====
call :wait_for_device
echo Using device: !DEVICE!
echo.

:: =====================================================
:: ===== FIRST RECORDING (BEFORE IGN) =====
:: =====================================================
echo Starting recording BEFORE IGN...
start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\part1.mkv"

echo.
echo Perform initial test...
echo Press any key BEFORE IGN OFF to stop recording
pause >nul

taskkill /IM scrcpy.exe /F >nul 2>nul

:: =====================================================
:: ===== IGN / ACC OFF =====
:: =====================================================
echo.
echo Perform IGN OFF / ACC OFF now...
pause

:: =====================================================
:: ===== WAIT FOR DEVICE RECONNECT =====
:: =====================================================
call :wait_for_device

:: =====================================================
:: ===== SECOND RECORDING (AFTER IGN) =====
:: =====================================================
echo Starting recording AFTER IGN...
start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\part2.mkv"

echo.
echo Continue test after IGN...
echo Press any key to stop recording
pause >nul

taskkill /IM scrcpy.exe /F >nul 2>nul

echo.
echo Recording completed.
echo.

:: =====================================================
:: ===== LOG COLLECTION =====
:: =====================================================
echo Collecting logs...

call :wait_for_device
adb bugreport "%D%"

call :wait_for_device
adb logcat -d > "%D%\Logcat\logcat.txt"

call :wait_for_device
adb shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0

echo Waiting for logs to be stored...
timeout /t 5 >nul

call :wait_for_device
adb pull /sdcard/ICB_Log "%D%" >nul 2>nul

:: =====================================================
:: ===== MOVE FILES =====
:: =====================================================
echo Organizing logs...

move "%D%\bugreport*zip" "%D%\Bugreport\" >nul 2>nul

if exist "%D%\ICB_Log\" (

    for %%T in (hw_err_* sw_err_*) do (
        for /f "delims=" %%F in ('dir "%D%\ICB_Log\%%T" /ad /b /o-n 2^>nul') do (
            move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
            goto :next
        )
    )
)

:next

if exist "%D%\ICB_Log\" (
    for /f "delims=" %%F in ('dir "%D%\ICB_Log\makerLog_*" /ad /b /o-n 2^>nul') do (
        move "%D%\ICB_Log\%%F" "%D%\Maker_Logs\" >nul
    )
)

rd /s /q "%D%\ICB_Log" >nul 2>nul

echo.
echo ==========================================
echo Logs and videos saved in: %D%
echo ==========================================
echo.

pause
exit /b

:: =====================================================
:: FUNCTION: WAIT FOR DEVICE (IGN SAFE)
:: =====================================================
:wait_for_device
set DEVICE=
echo Waiting for device...

adb wait-for-device

:loop
for /f "tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" set DEVICE=%%A
)

if not defined DEVICE (
    timeout /t 2 >nul
    goto loop
)

echo Device connected: !DEVICE!
exit /b