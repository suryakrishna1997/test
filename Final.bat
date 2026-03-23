@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"


echo.
echo Welcome to Log and Video Recorder Tool
echo.

set /p D= Please provide a folder name to capture a logs and Video: 
if "%D%"=="" (echo No name entered. & pause & exit)

mkdir "%D%"
for %%F in (Bugreport Video Logcat HS_Logs Maker_Logs MCU) do mkdir "%D%\%%F"

echo Waiting for the device to establish an ADB connection...

adb devices

echo Connection Established Successfully . . .
echo.
echo Video Recording will start . . .
echo.
pause

for /f "skip=1 tokens=1, 2" %%A in ('adb devices') do (if "%%B"=="device" (set DEVICE=%%A))
echo.
echo Video recording is started ...

start "" "D:\adb 1\adb\scrcpy.exe" -s %DEVICE% --record "%D%\Video\%D%.mkv"

echo.

echo After execution, press any key to stop recording...

echo.

pause

echo.
echo Video recording is stoped and saved in "%D%" folder ...

taskkill /IM scrcpy.exe /F >nul 2>nul

echo.

echo Log collection has started...

echo [1/4] Bugreport... 
adb bugreport "%D%"
echo Collected Bugreport Sucessfully...

echo.

echo [2/4] Logcat... 
adb logcat -d all > "%D%\Logcat\logcat.txt"
echo Collected Logcat Sucessfully...

echo.

echo [3/4] Broadcast Logs...
adb shell am broadcast -a com.honda.auto.action.EXPORT_LOGS --user 0
echo Fetched Permission Sucessfully...

echo.

echo Waiting to Store Logs...
timeout /t 5 >nul

echo.

echo [4/4] Logs Pulling...
adb pull /sdcard/ICB_Log "%D%"

echo.

echo Moving the files to the Specific folders...
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

echo The process has completed, and the logs and video have been stored in the %D% folder...
pause

