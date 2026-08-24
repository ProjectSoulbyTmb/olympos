# Registers (or removes) the Yggdrasil Sentinel as a Windows Scheduled
# Task: remediation + full gate sweep every 30 minutes, whether you are
# logged in or not. Mirrors register-updater-task.ps1 conventions.
#
#   powershell -ExecutionPolicy Bypass -File register-sentinel-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-sentinel-task.ps1 -Unregister

param(
    [switch]$Unregister,
    [int]$IntervalMinutes = 30
)

$ErrorActionPreference = "Stop"
$taskName = "Yggdrasil Sentinel"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python.exe" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "sentinel task removed"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-u `"(Join-Path $here 'sentinel.py')`"" `
    -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 25)
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "sentinel registered: every $IntervalMinutes min, ledger at data\sentinel\incidents.jsonl"
