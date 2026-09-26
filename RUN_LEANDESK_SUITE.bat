@echo off
setlocal
cd /d "%~dp0"
if exist ".build_venv\Scripts\python.exe" (
    ".build_venv\Scripts\python.exe" lean_desk_suite.py
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 lean_desk_suite.py
    ) else (
        python lean_desk_suite.py
    )
)
if errorlevel 1 pause
