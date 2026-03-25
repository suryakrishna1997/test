@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ===== LOG FETCHER TOOL =====
echo.

:: ===== Input =====
set /p D=Enter folder name: 
if "%D%"=="" (
    echo Folder name cannot be empty!
    pause
    exit /b
)

:: ===== Create Folders =====
for %%F in ("%D%" "%D%\Bugreport" "%D%\Video" "%D%\Logcat" "%D%\HS_Logs" "%D%\Maker_Logs" "%D%\MCU") do (
    if not exist "%%~F" mkdir "%%~F"
)

:: ===== Detect Device =====
echo.
echo Detecting device...
for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" set DEVICE=%%A
)

if not defined DEVICE (
    echo No device detected! Check USB debugging.
    pause
    exit /b
)

echo Device: !DEVICE!
echo.

:: ===== Start Recording =====
echo Starting screen recording...
start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\%D%.mkv"

echo Press any key to stop recording...
pause >nul

taskkill /IM scrcpy.exe /F >nul 2>&1

:: ===== Collect Logs =====
echo.
echo Collecting logs...

echo [1/4] Bugreport...
adb -s !DEVICE! bugreport "%D%"

echo [2/4] Logcat...
adb -s !DEVICE! logcat -d > "%D%\Logcat\logcat.txt"

echo [3/4] Trigger Logs...
adb -s !DEVICE! shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0
timeout /t 5 >nul

echo [4/4] Pull Logs...
adb -s !DEVICE! pull /sdcard/ICB_Log "%D%" >nul 2>&1

:: ===== Move Bugreport =====
move "%D%\bugreport*.zip" "%D%\Bugreport\" >nul 2>&1

:: ===== Process Logs =====
if exist "%D%\ICB_Log\" (

    :: HW Logs
    for /f "delims=" %%F in ('dir "%D%\ICB_Log\hw_err_*" /ad /b /o-n 2^>nul') do (
        move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
        goto :SW
    )
)

:SW
if exist "%D%\ICB_Log\" (
    :: SW Logs
    for /f "delims=" %%F in ('dir "%D%\ICB_Log\sw_err_*" /ad /b /o-n 2^>nul') do (
        move "%D%\ICB_Log\%%F" "%D%\HS_Logs\" >nul
        goto :MAKER
    )
)

:MAKER
if exist "%D%\ICB_Log\" (
    :: Maker Logs
    for /f "delims=" %%F in ('dir "%D%\ICB_Log\makerLog_*" /ad /b /o-n 2^>nul') do (
        move "%D%\ICB_Log\%%F" "%D%\Maker_Logs\" >nul
        goto :CLEANUP
    )
)

:CLEANUP
rd /s /q "%D%\ICB_Log" >nul 2>&1

:: ===== ZIP =====
echo.
echo Creating ZIP...

powershell -Command ^
"Compress-Archive -Path '%D%\Bugreport','%D%\Logcat','%D%\HS_Logs','%D%\Maker_Logs','%D%\MCU' -DestinationPath '%D%\%D%.zip' -Force"

echo.
echo ===== DONE =====
echo Folder: %D%
echo ZIP: %D%\%D%.zip
echo.

pause