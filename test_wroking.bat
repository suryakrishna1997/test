@echo off
setlocal enabledelayedeexpansion
cd /d "%~dp0"

@echo off 
setlocal EnableDelayedExpansion

echo.
echo Welcome to log fetcher
echo.

set /p D=Please Enter Folder Name to capture a logs and video:- 

if "%D%"=="" (echo No name entered. & pause & exit)

mkdir "%D%"
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do mkdir "%D%\%%F"

echo.
echo Detecting device...
echo.

adb devices

echo.
pause

for /f "skip=1 tokens=1, 2" %%A in ('adb devices') do (if "%%B"=="device" (set DEVICE=%%A))

echo Device detected: %DEVICE%
echo.

echo starting screen recording
echo.

start "" "D:\adb 1\adb\scrcpy.exe" -s %DEVICE% --record "%D%\Video\%D%.mkv"
pause

taskkill /IM scrcpy.exe /F >nul 2>nul
echo Please press Enter to stop the recording and collect the logs.
echo.

echo [1/4] Bugreport... 
adb bugreport "%D%"

echo [2/4] Logcat... 
adb logcat -d all > "%D%\Logcat\logcat.txt"

echo [3/4] Broadcast Logs...
adb shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0

echo Wating to Store Logs...
timeout /t 5 >nul

echo [4/4] Logs Pulling...
adb pull /sdcard/ICB_Log "%D%"

move "%D%\bugreport*zip" "%D%\Bugreport\" > nul

for /f "delims=" %%F in ('dir "%D%\ICB_Log\hw_err_*" /ad /b /o-n') do (
    move "%D%\ICB_Log\%%F" "%D%\HS_Logs\"
    goto :hw_done
)
:hw_done

for /f "delims=" %%F in ('dir "%D%\ICB_Log\sw_err_*" /ad /b /o-n') do (
    move "%D%\ICB_Log\%%F" "%D%\HS_Logs\"
    goto :sw_done
)
:sw_done

for /f "delims=" %%F in ('dir "%D%\ICB_Log\makerLog_*" /ad /b /o-n') do (
    move "%D%\ICB_Log\%%F" "%D%\Maker_Logs\"
    goto :mk_done
)
:mk_done

rd /s /q "%D%\ICB_Log"

echo Done! Logs saved in: %D%
pause
