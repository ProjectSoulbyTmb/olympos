# SAFEGUARDS install - wire the pre-commit gate into this checkout.
# Run:  powershell -ExecutionPolicy Bypass -File safeguards\install.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$hooks = Join-Path $root ".git\hooks"
New-Item -ItemType Directory -Force -Path $hooks | Out-Null
$py = (Get-Command python).Source

$hook = Join-Path $hooks "pre-commit"
@"
#!/bin/sh
# installed by safeguards/install.ps1 - staged-file gates
python "$( ($root -replace '\\', '/') )/safeguards/check.py" --strict
"@ | Set-Content -Path $hook -Encoding ASCII -NoNewline

Write-Host "pre-commit hook installed: $hook"
Write-Host "python resolved to:       $py"
Write-Host "test with:                python safeguards\check.py --strict"
