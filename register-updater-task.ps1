# Registers (or removes) a Windows Scheduled Task that refreshes Yggdrasil
# live data every 30 minutes, whether you are logged in or not.
#
#   powershell -ExecutionPolicy Bypass -File register-updater-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-updater-task.ps1 -Unregister

param(
    [switch]$Unregister,
    [int]$IntervalMinutes = 30
)

$ErrorActionPreference = "Stop"
$taskName = "Yggdrasil Live Updater"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed scheduled task '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$here\osrs_updater.py`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# RunLevel Highest: the task runs elevated without per-run UAC prompts.
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Output "registered '$taskName': osrs_updater.py every $IntervalMinutes minutes"
Write-Output "run 'Start-ScheduledTask -TaskName $taskName' to fire it now"
