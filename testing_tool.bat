@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ==========================================
echo   Welcome to Log and Video Recorder Tool
echo ==========================================
echo.

:: ===== USER INPUT =====
set /p D=Enter Folder Name to capture Logs and Video: 
if "%D%"=="" (
    echo No name entered. Exiting...
    pause
    exit /b
)

:: ===== CREATE FOLDERS =====
mkdir "%D%" >nul 2>&1
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do mkdir "%D%\%%F" >nul 2>&1

:: ===== DEVICE CHECK =====
echo.
echo Waiting for ADB device...
adb wait-for-device

for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" set DEVICE=%%A
)

if not defined DEVICE (
    echo No device detected! Enable USB debugging.
    pause
    exit /b
)

echo Device Connected: !DEVICE!
echo.

:: ===== VIDEO RECORDING LOOP =====
echo ==========================================
echo   Auto Video Recording Started
echo ==========================================
echo.

:RECORD_LOOP

:: Generate timestamp (safe for filename)
for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set DATE=%%d-%%b-%%c
for /f "tokens=1-3 delims=:." %%a in ("%time%") do set TIME=%%a-%%b-%%c

set FILE_NAME=%D%_!DATE!_!TIME!

echo.
echo [Recording Started] !FILE_NAME!.mkv

start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\!FILE_NAME!.mkv"

:: Wait for disconnect (IGN OFF)
adb -s !DEVICE! wait-for-disconnect

echo.
echo Device disconnected (IGN OFF)...

:: Kill scrcpy safely
taskkill /IM scrcpy.exe /F >nul 2>&1

:: Wait for reconnect (IGN ON)
echo Waiting for device reconnect...
adb wait-for-device

echo Device reconnected.

:: Small delay for stability
timeout /t 3 >nul

goto RECORD_LOOP


:: ===== MANUAL EXIT POINT =====
:: (Use CTRL+C to break recording loop)


:: ===== LOG COLLECTION =====
echo.
echo ==========================================
echo   Log Collection Started
echo ==========================================
echo.

echo [1/4] Bugreport...
adb -s !DEVICE! bugreport "%D%"
echo Done.

echo [2/4] Logcat...
adb -s !DEVICE! logcat -d > "%D%\Logcat\logcat.txt"
echo Done.

echo [3/4] Broadcast Logs...
adb -s !DEVICE! shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0
timeout /t 5 >nul

echo [4/4] Pull Logs...
adb -s !DEVICE! pull /sdcard/ICB_Log "%D%" >nul 2>&1
echo Done.

:: ===== FILE ORGANIZATION =====
move "%D%\bugreport*.zip" "%D%\Bugreport\" >nul 2>&1

for /f "delims=" %%F in ('dir "%D%\ICB_Log\hw_err_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
    goto :hw_done
)
:hw_done

for /f "delims=" %%F in ('dir "%D%\ICB_Log\sw_err_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
    goto :sw_done
)
:sw_done

for /f "delims=" %%F in ('dir "%D%\ICB_Log\makerLog_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\Maker_Logs\" >nul
    goto :mk_done
)
:mk_done

rd /s /q "%D%\ICB_Log" >nul 2>&1

:: ===== ZIP CREATION =====
echo.
echo Creating ZIP...

powershell -Command ^
"Compress-Archive -Path '%D%\Bugreport','%D%\Logcat','%D%\HS_Logs','%D%\Maker_Logs' -DestinationPath '%D%\%D%.zip' -Force"

if exist "%D%\%D%.zip" (
    echo ZIP Created: %D%\%D%.zip
) else (
    echo ZIP Failed!
)

echo.
echo ==========================================
echo   Process Completed
echo ==========================================
pause
exit /b