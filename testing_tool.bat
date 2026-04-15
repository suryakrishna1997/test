@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ==========================================
echo   Log and Video Recorder Tool (Final)
echo ==========================================
echo.

:: ===== INPUT =====
set /p D=Enter Folder Name: 
if "%D%"=="" (
    echo No name entered. Exiting...
    pause
    exit /b
)

:: ===== FOLDERS =====
mkdir "%D%" >nul 2>&1
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do mkdir "%D%\%%F" >nul 2>&1

:: ===== DEVICE CHECK =====
echo Waiting for device...
adb wait-for-device

for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" set DEVICE=%%A
)

if not defined DEVICE (
    echo No device detected!
    pause
    exit /b
)

echo Device Connected: !DEVICE!

echo.
echo Press 'Q' anytime to STOP recording
echo.

:: ===== RECORD LOOP =====
:RECORD_LOOP

:: Timestamp
for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set DATE=%%d-%%b-%%c
for /f "tokens=1-3 delims=:." %%a in ("%time%") do set TIME=%%a-%%b-%%c

set FILE_NAME=%D%_!DATE!_!TIME!

echo.
echo [Recording Started] !FILE_NAME!.mkv

start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\!FILE_NAME!.mkv"

:: ===== MONITOR LOOP =====
:MONITOR_LOOP

:: Check if user pressed Q (non-blocking)
choice /C QN /N /T 1 /D N >nul
if errorlevel 1 if not errorlevel 2 (
    echo.
    echo Stopping recording by user...
    goto STOP_RECORDING
)

:: Check device state
set STATE=
for /f "tokens=2" %%S in ('adb -s !DEVICE! get-state 2^>nul') do set STATE=%%S

if not "!STATE!"=="device" (
    echo Device disconnected (IGN OFF)...

    taskkill /IM scrcpy.exe /F >nul 2>&1

    echo Waiting for reconnect...
    adb wait-for-device

    echo Device reconnected.
    timeout /t 2 >nul

    goto RECORD_LOOP
)

goto MONITOR_LOOP


:: ===== STOP =====
:STOP_RECORDING
taskkill /IM scrcpy.exe /F >nul 2>&1

echo.
echo ==========================================
echo   Merging Videos
echo ==========================================
echo.

:: ===== CREATE FILE LIST =====
del "%D%\Video\filelist.txt" >nul 2>&1

for %%F in ("%D%\Video\*.mkv") do (
    echo file '%%~fF' >> "%D%\Video\filelist.txt"
)

:: ===== MERGE VIDEOS =====
ffmpeg -f concat -safe 0 -i "%D%\Video\filelist.txt" -c copy "%D%\Video\Final_%D%.mkv"

if exist "%D%\Video\Final_%D%.mkv" (
    echo Final video created successfully.
) else (
    echo Video merge failed!
)

echo.

:: ===== LOG COLLECTION =====
echo ==========================================
echo   Log Collection Started
echo ==========================================
echo.

adb -s !DEVICE! bugreport "%D%"
adb -s !DEVICE! logcat -d > "%D%\Logcat\logcat.txt"
adb -s !DEVICE! shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0
timeout /t 5 >nul
adb -s !DEVICE! pull /sdcard/ICB_Log "%D%" >nul 2>&1

:: ===== ORGANIZE =====
move "%D%\bugreport*.zip" "%D%\Bugreport\" >nul 2>&1

for /f "delims=" %%F in ('dir "%D%\ICB_Log\hw_err_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
    goto :hw_done
)
:hw_done

for /f "delims=" %%F in ('dir "%D%\ICB_Log\makerLog_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\Maker_Logs\" >nul
    goto :mk_done
)
:mk_done

rd /s /q "%D%\ICB_Log" >nul 2>&1

:: ===== ZIP CREATION =====
powershell -Command ^
"Compress-Archive -Path '%D%\Bugreport','%D%\Logcat','%D%\HS_Logs','%D%\Maker_Logs' -DestinationPath '%D%\%D%.zip' -Force"

echo.
echo ==========================================
echo   COMPLETED
echo ==========================================
echo.

echo Final Video: %D%\Video\Final_%D%.mkv
echo Logs ZIP: %D%\%D%.zip

pause
exit /b