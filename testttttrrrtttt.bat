@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ============================================================
::   LOG AND VIDEO RECORDER TOOL
:: ============================================================

echo.
echo  ============================================================
echo       LOG AND VIDEO RECORDER TOOL
echo  ============================================================
echo.

:: ============================================================
::  SECTION 1 - FOLDER SETUP
:: ============================================================

set /p D= Enter Session Name: 
if "!D!"=="" (
    echo  [ERROR] No name entered. Exiting...
    pause
    exit /b
)

for %%F in ("!D!" "!D!\Bugreport" "!D!\Video" "!D!\Logcat" "!D!\HS_Logs" "!D!\Maker_Logs" "!D!\MCU") do (
    mkdir %%F >nul 2>&1
)

echo.
echo  [OK] Session folder created: !D!

:: ============================================================
::  SECTION 2 - DEVICE CONNECTION
:: ============================================================

echo.
echo  ============================================================
echo   SECTION 2 - DEVICE CONNECTION
echo  ============================================================
echo.
echo  Waiting for device...

adb wait-for-device

set DEVICE=
for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" set DEVICE=%%A
)

if "!DEVICE!"=="" (
    echo  [ERROR] No device detected. Exiting...
    pause
    exit /b
)

echo  [OK] Device Connected : !DEVICE!

:: ============================================================
::  SECTION 3 - VIDEO RECORDING
:: ============================================================

echo.
echo  ============================================================
echo   SECTION 3 - VIDEO RECORDING
echo  ============================================================
echo.
echo  Recording will start automatically.
echo  Each IGN OFF stops the clip. Each IGN ON starts a new clip.
echo  Press Q at any time to stop recording and collect logs.
echo.

set STOP_FLAG=0
set CLIP_COUNT=0

:RECORD_LOOP

    :: Build timestamp
    set RAW_TIME=%time%
    set RAW_TIME=!RAW_TIME: =0!
    for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set STAMP=%%d-%%b-%%c
    for /f "tokens=1-3 delims=:." %%a in ("!RAW_TIME!") do set STAMP=!STAMP!_%%a-%%b-%%c

    set /a CLIP_COUNT+=1
    set FILE_NAME=!D!_!STAMP!

    echo  ----------------------------------------------------------
    echo   Clip !CLIP_COUNT! Started  ^|  File: !FILE_NAME!.mkv
    echo  ----------------------------------------------------------

    start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "!D!\Video\!FILE_NAME!.mkv"

    timeout /t 3 >nul

    :POLL_LOOP

        tasklist /FI "IMAGENAME eq scrcpy.exe" 2>nul | find /I "scrcpy.exe" >nul
        if errorlevel 1 (
            echo.
            echo  [INFO] Device disconnected - Clip !CLIP_COUNT! saved.
            goto :AFTER_POLL
        )

        choice /C QN /N /T 1 /D N >nul 2>&1
        if errorlevel 2 goto :POLL_LOOP
        if errorlevel 1 (
            echo.
            echo  [STOP] Q pressed - Ending recording session...
            set STOP_FLAG=1
            goto :AFTER_POLL
        )

    goto :POLL_LOOP
    :AFTER_POLL

    taskkill /IM scrcpy.exe /F >nul 2>&1

    if "!STOP_FLAG!"=="1" goto :COLLECT_LOGS

    echo  [INFO] Waiting for device to reconnect (IGN ON)...
    adb wait-for-device
    timeout /t 2 >nul

goto :RECORD_LOOP

:: ============================================================
::  SECTION 4 - LOG COLLECTION
:: ============================================================

:COLLECT_LOGS
echo.
echo  ============================================================
echo   SECTION 4 - LOG COLLECTION
echo  ============================================================
echo.

echo  [1/4] Pulling bugreport...
adb -s !DEVICE! bugreport "!D!"

echo  [2/4] Pulling logcat...
adb -s !DEVICE! logcat -d > "!D!\Logcat\logcat.txt"

echo  [3/4] Exporting Honda logs via broadcast...
adb -s !DEVICE! shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0
timeout /t 5 >nul

echo  [4/4] Pulling ICB logs from device...
adb -s !DEVICE! pull /sdcard/ICB_Log "!D!" >nul 2>&1

:: ============================================================
::  SECTION 5 - ORGANIZING LOGS
:: ============================================================

echo.
echo  ============================================================
echo   SECTION 5 - ORGANIZING LOGS
echo  ============================================================
echo.

echo  [INFO] Moving bugreport to Bugreport folder...
move "!D!\bugreport*.zip" "!D!\Bugreport\" >nul 2>&1

echo  [INFO] Moving latest HS log to HS_Logs folder...
for /f "delims=" %%F in ('dir "!D!\ICB_Log\hw_err_*" /ad /b /o-n 2^>nul') do (
    move "!D!\ICB_Log\%%F" "!D!\HS_Logs\" >nul
    goto :hw_done
)
:hw_done

echo  [INFO] Moving latest Maker log to Maker_Logs folder...
for /f "delims=" %%F in ('dir "!D!\ICB_Log\makerLog_*" /ad /b /o-n 2^>nul') do (
    move "!D!\ICB_Log\%%F" "!D!\Maker_Logs\" >nul
    goto :mk_done
)
:mk_done

rd /s /q "!D!\ICB_Log" >nul 2>&1
echo  [OK] ICB_Log temp folder cleaned up.

:: ============================================================
::  SECTION 6 - ZIPPING LOGS
:: ============================================================

echo.
echo  ============================================================
echo   SECTION 6 - ZIPPING LOGS
echo  ============================================================
echo.

echo  [INFO] Creating zip archive...
powershell -Command "Compress-Archive -Path '!D!\Bugreport','!D!\Logcat','!D!\HS_Logs','!D!\Maker_Logs' -DestinationPath '!D!\!D!.zip' -Force"

if exist "!D!\!D!.zip" (
    echo  [OK] Zip created successfully.
) else (
    echo  [ERROR] Zip creation failed!
)

:: ============================================================
::  DONE
:: ============================================================

echo.
echo  ============================================================
echo   SESSION COMPLETE
echo  ============================================================
echo.
echo   Session Name  : !D!
echo   Total Clips   : !CLIP_COUNT!
echo   Videos Folder : !D!\Video\
echo   Logs ZIP      : !D!\!D!.zip
echo.
echo  ============================================================
echo.
pause
exit /b