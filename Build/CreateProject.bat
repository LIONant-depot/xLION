@echo off
setlocal enabledelayedexpansion

:: Save current directory
set "ORIG_DIR=%CD%"

:: Check for admin
>nul 2>&1 fsutil dirty query %systemdrive% && goto :gotAdmin

:: Relaunch elevated, passing original dir as arg
powershell -Command "Start-Process '%~f0' -ArgumentList '%ORIG_DIR%' -Verb RunAs"
exit /b

:gotAdmin
:: If relaunched, restore original dir (from arg) if provided
if "%~1" neq "" cd /d "%~1"

:: READY TO WORK!!!!

rmdir /s /q xLION.vs2022
rem rmdir /s /q ..\dependencies

:: Unlike xGPU's own CreateProject.bat, no imgui-node-editor post-patch step is needed here -
:: xLION's own CMakeLists.txt already applies both upstream patches (GetKeyIndex shim,
:: operator*(float, ImVec2) removal) idempotently during configure itself.
cmake ../ -G "Visual Studio 17 2022" -A x64 -B xLION.vs2022
if errorlevel 1 (
    echo Error: Cmake failed
    goto :ERROR
)

endlocal
pause
exit /b 0

:ERROR
endlocal
pause
exit /b 1
