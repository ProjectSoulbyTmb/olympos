@echo off
title OSRS LAB Launcher
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    echo Starting the Easy Runner...
    python runner.py
) else (
    echo Python not found - launching the desktop app instead.
    start "" "%~dp0OsrsLab.exe"
)
pause
