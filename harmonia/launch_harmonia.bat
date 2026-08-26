@echo off
rem HARMONIA - normalized studio viewer (standard viewing formats)
rem Serves the folder next to this script by default; pass a folder as %1.
setlocal
set ROOT=%~1
if "%ROOT%"=="" set ROOT=%~dp0
python "%~dp0server.py" --root "%ROOT%" --port 43908 --open
endlocal
