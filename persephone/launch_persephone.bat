@echo off
rem PERSEPHONE guardian - detached launch
start "persephone" /min cmd /c "python -u "%~dp0persephone.py""
