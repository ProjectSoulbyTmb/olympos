# DAEDELUS system-update cycle launcher - runs one bounded workshop
# cycle headlessly via opencode, with cwd pinned to this repo root.
#
# Manual use:
#   .\daedalus-cycle.ps1                        # self-directed cycle
#   .\daedalus-cycle.ps1 "build jsonl-echo web1"    # focused commission
#
# Scheduled autonomy (one-time, from repo root in a normal PowerShell -
# the workshop owns no elevated surface):
#   powershell -ExecutionPolicy Bypass -File register-daedalus-task.ps1
#
# PATH note: if `opencode` is not on the SYSTEM PATH in scheduled context,
# install it machine-wide or point the invocation below at its absolute
# path.
#
# Cycle output is teed to docs\plans\updates\<date>-<hhmm>.md so every
# automated update leaves durable evidence behind.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$logDir = Join-Path $root "docs\plans\updates"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
$outFile = Join-Path $logDir "$stamp-daedalus.md"
"DAEDALUS update cycle started $stamp" | Set-Content -LiteralPath $outFile

& opencode run --agent daedalus @args 2>&1 |
    Add-Content -LiteralPath $outFile
exit $LASTEXITCODE
