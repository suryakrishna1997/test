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

set STOP_FLAG=0

:: ===== RECORD LOOP =====
:RECORD_LOOP

if "!STOP_FLAG!"=="1" goto STOP_RECORDING

:: Timestamp
for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set DATE=%%d-%%b-%%c
for /f "tokens=1-3 delims=:. " %%a in ("%time%") do set TIME=%%a-%%b-%%c

set FILE_NAME=%D%_!DATE!_!TIME!

echo [Recording] !FILE_NAME!.mkv

start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\!FILE_NAME!.mkv"

:: ===== WAIT LOOP: poll Q while waiting for disconnect =====
:WAIT_LOOP
    :: Check if scrcpy is still running
    tasklist /FI "IMAGENAME eq scrcpy.exe" 2>nul | find /I "scrcpy.exe" >nul
    if errorlevel 1 (
        echo scrcpy stopped (device disconnected or closed^)
        goto AFTER_WAIT
    )

    :: Check for Q key press (1 second timeout)
    choice /C QN /N /T 1 /D N >nul
    if errorlevel 1 if not errorlevel 2 (
        echo Stopping recording...
        set STOP_FLAG=1
        goto AFTER_WAIT
    )

goto WAIT_LOOP

:AFTER_WAIT

taskkill /IM scrcpy.exe /F >nul 2>&1

if "!STOP_FLAG!"=="1" goto STOP_RECORDING

:: Wait for IGN ON (next cycle)
echo Waiting for device reconnect...
adb wait-for-device
timeout /t 2 >nul

goto RECORD_LOOP


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

:: ===== MERGE =====
ffmpeg -f concat -safe 0 -i "%D%\Video\filelist.txt" -c copy "%D%\Video\Final_%D%.mkv"

if exist "%D%\Video\Final_%D%.mkv" (
    echo Final video created: %D%\Video\Final_%D%.mkv
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

:: ===== ZIP =====
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