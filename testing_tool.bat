@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ==========================================
echo   Welcome to Log and Video Recorder Tool
echo ==========================================
echo.

set /p D=Please provide a Folder Name to capture Logs and Video: 
if "%D%"=="" (
    echo.
    echo No name entered.
    pause
    exit /b
)

echo.
mkdir "%D%" >nul 2>&1
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do mkdir "%D%\%%F" >nul 2>&1

echo.
echo Waiting for the device to establish an ADB connection...
echo.

adb devices

for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" set DEVICE=%%A
)

if not defined DEVICE (

    echo No device detected!...
    echo exiting the process, please turn ON the USB Debugging to capture Logs and Video.
    pause
    exit /b
)

echo.
echo Connection Established Successfully...
echo.

echo.
echo ==========================================
echo   Video Recording Started
echo ==========================================
echo.

pause

start "" "D:\adb 1\adb\scrcpy.exe" -s !DEVICE! --record "%D%\Video\%D%.mkv"

echo.
echo After execution, press any key to stop recording...
echo.
pause

echo.
echo Video recording is stopped and saved in "%D%" Video folder...
echo.

taskkill /IM scrcpy.exe /F >nul 2>nul

echo ==========================================
echo   Video Recording Ended
echo ==========================================


echo.
echo ==========================================
echo   Log Collection Started
echo ==========================================
echo.

echo [1/4] Bugreport...
adb -s !DEVICE! bugreport "%D%"
echo Bugreport collected successfully.
echo.

echo [2/4] Logcat...
adb -s !DEVICE! logcat -d > "%D%\Logcat\logcat.txt"
echo Logcat collected successfully.
echo.

echo [3/4] Broadcast Logs...
adb -s !DEVICE! shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0
echo Permission fetched successfully.
echo.

echo Waiting to store logs...
timeout /t 5 >nul

echo.
echo [4/4] Pulling Logs...
adb -s !DEVICE! pull /sdcard/ICB_Log "%D%" >nul 2>&1
echo.

echo ==========================================
echo   Log Collection Ended
echo ==========================================

echo Moving files to respective folders...
echo.

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
echo ==========================================
echo   Creating ZIP File started
echo ==========================================
echo.

powershell -Command ^
"Compress-Archive -Path '%D%\Bugreport','%D%\Logcat','%D%\HS_Logs','%D%\Maker_Logs' -DestinationPath '%D%\%D%.zip' -Force"

if exist "%D%\%D%.zip" (
    echo ZIP created successfully: %D%\%D%.zip
) else (
    echo ZIP creation failed!
)
echo.
echo ==========================================
echo   Creating ZIP File Ended
echo ==========================================
echo.

echo Logs and video are stored in: %D% folder
echo ZIP file: %D%\%D%.zip
echo.
echo.
echo ==========================================
echo   Process Completed Successfully
echo ==========================================
echo.

pause
exit /b
