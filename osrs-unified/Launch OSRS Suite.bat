@echo off
setlocal
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PY%" for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do set "PY=%%P"
if not exist "%PY%" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
start "OSRS Suite" "%PY%" "%~dp0osrs_app.py"
