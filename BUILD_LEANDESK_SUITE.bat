@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
    echo Usage: BUILD_LEANDESK_SUITE.bat ACCEPTED_SOURCE_TREE_ID
    exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0BUILD_LEANDESK_SUITE.ps1" -AcceptedSourceTreeId "%~1"
if errorlevel 1 (
    echo.
    echo LeanDesk Suite build failed.
    pause
    exit /b 1
)
echo.
echo LeanDesk Suite build completed successfully.
pause
