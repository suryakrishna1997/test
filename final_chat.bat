@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ==========================================
echo   Welcome to Log and Video Recorder Tool
echo ==========================================
echo.

set /p D=Please provide a folder name to capture logs and Video: 
if "%D%"=="" (
    echo.
    echo No name entered.
    pause
    exit
)

echo.
mkdir "%D%"
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do mkdir "%D%\%%F"

echo.
echo Waiting for the device to establish an ADB connection...
echo.

adb devices

echo.
echo Connection Established Successfully...
echo.

echo Video Recording will start...
echo.
pause

for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" set DEVICE=%%A
)

echo.
echo Video recording is started...
echo.

start "" "D:\adb 1\adb\scrcpy.exe" -s %DEVICE% --record "%D%\Video\%D%.mkv"

echo.
echo After execution, press any key to stop recording...
echo.
pause

echo.
echo Video recording is stopped and saved in "%D%" folder...
echo.

taskkill /IM scrcpy.exe /F >nul 2>nul

echo.
echo ==========================================
echo   Log Collection Started
echo ==========================================
echo.

echo [1/4] Bugreport...
echo.
adb bugreport "%D%"
echo.
echo Bugreport collected successfully.
echo.

echo [2/4] Logcat...
echo.
adb logcat -d > "%D%\Logcat\logcat.txt"
echo.
echo Logcat collected successfully.
echo.

echo [3/4] Broadcast Logs...
echo.
adb shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0
echo.
echo Permission fetched successfully.
echo.

echo Waiting to store logs...
echo.
timeout /t 5 >nul

echo.
echo [4/4] Pulling Logs...
echo.
adb pull /sdcard/ICB_Log "%D%"
echo.

echo Moving files to respective folders...
echo.

move "%D%\bugreport*zip" "%D%\Bugreport\" >nul

for /f "delims=" %%F in ('dir "%D%\ICB_Log\hw_err_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\HS_Logs\"
    goto :hw_done
)
:hw_done

for /f "delims=" %%F in ('dir "%D%\ICB_Log\sw_err_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\HS_Logs\"
    goto :sw_done
)
:sw_done

for /f "delims=" %%F in ('dir "%D%\ICB_Log\makerLog_*" /ad /b /o-n 2^>nul') do (
    move "%D%\ICB_Log\%%F" "%D%\Maker_Logs\"
    goto :mk_done
)
:mk_done

rd /s /q "%D%\ICB_Log"

echo.
echo ==========================================
echo   Process Completed Successfully
echo ==========================================
echo.
echo Logs and video are stored in: %D%
echo.

pause