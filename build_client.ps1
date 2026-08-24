# Builds the standalone playable client: Bifrost.exe
# Usage:  powershell -File build_client.ps1
$ErrorActionPreference = "Stop"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
Set-Location $PSScriptRoot

& $py -m PyInstaller --onefile --windowed --name Bifrost `
    --paths "osrs-llm-agent" `
    --hidden-import pygame --hidden-import numpy `
    --hidden-import server.rsps_server --hidden-import server.client `
    --hidden-import game.world --hidden-import game.sdk --hidden-import game.content `
    --distpath dist --workpath "$env:TEMP\opencode\pyi_play" `
    --specpath "$env:TEMP\opencode\pyi_play" play_rsps.py

Write-Host ""
Write-Host "Built dist\Bifrost.exe (keep it next to the osrs-llm-agent folder)"
