# ATHENA autonomous cycle launcher - runs one bounded planning cycle
# headlessly via opencode, with cwd pinned to this repo root.
#
# Manual use:
#   .\athena-cycle.ps1                        # self-directed cycle
#   .\athena-cycle.ps1 "restore realms registry"   # focused cycle
#
# Scheduled autonomy (one-time, from repo root in an elevated PowerShell),
# every 12h:
#   .\register-thoth-task.ps1 -Name "Athena Planning Cycle" `
#       -Command "powershell" `
#       -Args "-NoProfile -ExecutionPolicy Bypass -File `"$((Get-Location).Path)\athena-cycle.ps1`"" `
#       -IntervalMinutes 720
#
# PATH note: if `opencode` is not on the SYSTEM PATH in scheduled context,
# install it machine-wide or point -Command at its absolute path.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$logDir = Join-Path $root "docs\plans\cycles"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

& opencode run --agent athena @args
exit $LASTEXITCODE
