# Registers (or removes) the PTAH nightly self-check as a Windows
# Scheduled Task: verify gate + conversation-store hygiene + JSONL
# ledger, keeping the agent kernel honest around the clock.
#
#   powershell -ExecutionPolicy Bypass -File register-ptah-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-ptah-task.ps1 -Unregister

param(
    [switch]$Unregister,
    [int]$Hour = 3,
    [int]$Minute = 30
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos Ptah Selfcheck"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python.exe" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "ptah selfcheck task removed"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-u -m ptah selfcheck" `
    -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At ("{0:00}:{1:00}" -f $Hour, $Minute)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "ptah selfcheck registered: daily at $("{0:00}:{1:00}" -f $Hour, $Minute), ledger at ptah\data\selfcheck.jsonl"
