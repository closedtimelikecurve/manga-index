@echo off
rem ============================================================
rem dispatch_apk.bat - dispatch Android APP package (enforce single package in app_releases)
rem Usage:
rem     dispatch_apk.bat <full-path-to-new-APK>
rem Behavior:
rem     1) delete every *.apk in app_releases (remove old package)
rem     2) copy the new APK into app_releases
rem   Result: at most 1 dispatch package exists in app_releases at any time.
rem
rem New APK filename MUST look like: Index-v<versionName>-<versionCode>.apk
rem   (the trailing versionCode is the monotonic build number; server /api/app-version
rem    uses it to dispatch and compare; the phone only compares the integer to decide update)
rem   A non-conforming filename only triggers a warning, not a block.
rem
rem Project rule (CHANGELOG "submit discipline" section): app_releases holds exactly 1
rem   dispatch package; every dispatch must delete/overwrite the old one. This script
rem   is the enforcement point (del *.apk then copy new). Manual drops must follow too.
rem ============================================================
setlocal EnableExtensions

if "%~1"=="" (
    echo Usage: dispatch_apk.bat ^<full-path-to-new-APK^>
    exit /b 1
)

rem normalize the incoming path to a full Windows path (handles /d/... from Git Bash too)
for %%I in ("%~1") do set "SRC=%%~fI"
if not exist "%SRC%" (
    echo [ERROR] source APK not found: %SRC%
    exit /b 1
)

rem locate app_releases (this script lives in _app/scripts/, parent is _app)
set "RELDIR=%~dp0.."
set "RELDIR=%RELDIR%\app_releases"
for %%I in ("%RELDIR%") do set "RELDIR=%%~fI"
if not exist "%RELDIR%\" (
    echo [ERROR] app_releases dir not found: %RELDIR%
    exit /b 1
)

set "NAME=%~nx1"

rem filename convention check (warning only, no block). Pure substring test avoids
rem findstr /b /e quirks on this locale.
set "BAD=0"
if not "%NAME:~0,7%"=="Index-v" set "BAD=1"
if not "%NAME:~-4%"==".apk" set "BAD=1"
if "%BAD%"=="1" (
    echo [WARN] filename "%NAME%" does not match Index-vX-Y.apk pattern, still dispatching.
)

echo [dispatch] clearing old packages in app_releases...
del /q "%RELDIR%\*.apk" 2>nul

echo [dispatch] placing new package: %NAME%
copy /y "%SRC%" "%RELDIR%\%NAME%" >nul
if errorlevel 1 (
    echo [ERROR] copy failed
    exit /b 1
)

echo [dispatch] done. app_releases now contains:
dir /b "%RELDIR%\*.apk"
endlocal
