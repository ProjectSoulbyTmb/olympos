@echo off
title APHRODITE studio
rem ============================================================
rem  APHRODITE - standalone offline studio media viewer
rem  Library root : D:\new      Port : 43904 (loopback only)
rem  Override any default, e.g.:
rem     launch_aphrodite.bat --root "E:\photos" --port 43914
rem ============================================================
setlocal
set "ROOT=D:\new"
set "PORT=43904"

where py >nul 2>nul
if %errorlevel%==0 (set "PYLAUNCH=py -3") else (set "PYLAUNCH=python")

%PYLAUNCH% "%~dp0server.py" --root "%ROOT%" --port %PORT% --open --quiet %*
if errorlevel 1 pause
endlocal
