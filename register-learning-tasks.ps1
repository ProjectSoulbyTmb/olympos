# Registers the ATHENA learning subfleet as staggered weekly Windows
# Scheduled Tasks, so knowledge harvesting runs unattended:
#
#   metis  - Mondays    03:00 local (mine incidents/audits)
#   argus  - Thursdays  03:00 local (drift audit)
#   logia  - Saturdays  03:00 local (synthesis)
#
# One-time install from repo root in an elevated PowerShell:
#   .\register-learning-tasks.ps1
#
# Remove later with: Unregister-ScheduledTask -TaskName <name> -Confirm:$false

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$opencode = (Get-Command opencode -ErrorAction SilentlyContinue).Source
if (-not $opencode) {
    throw "opencode not on PATH; install machine-wide or edit this script"
}

function Register-Learner {
    param(
        [string]$Agent, [int]$DayOfWeek,
        [string]$Time = "03:00", [string]$Description = ""
    )
    # DayOfWeek: 1=Monday .. 6=Saturday, 0=Sunday (ScheduleService style)
    $action = New-ScheduledTaskAction -Execute $opencode `
        -Argument "run --agent $Agent" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek ([System.DayOfWeek] $DayOfWeek) -At $Time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopOnIdleEnd
    Register-ScheduledTask -TaskName "Athena Learning - $Agent" `
        -Action $action -Trigger $trigger -Settings $settings `
        -Description $Description -Force | Out-Null
    Write-Host "registered: Athena Learning - $Agent ($DayOfWeek @ $Time)"
}

Register-Learner -Agent metis -DayOfWeek 1 `
    -Description "Mine incidents/audits into lesson proposals"
Register-Learner -Agent argus -DayOfWeek 4 `
    -Description "Doc-vs-disk drift audit"
Register-Learner -Agent logia -DayOfWeek 6 `
    -Description "Synthesize patterns into playbook/rule amendments"

Write-Host @"
Learning subfleet scheduled. Consumption stays human-gated:
  python -m learning report   # what did they find?
"@
