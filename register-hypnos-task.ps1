# Registers (or removes) a Windows Scheduled Task that keeps HYPNOS -
# the silent task-handling organ - hosting continuously. Task letters
# dropped into data/post/hypnos/inbox (or *.task.json files into
# hypnos/data/dropin) are claimed, executed headless, retried on
# failure, resumed after crashes, and fed back to the live system as
# reply letters, topic broadcasts and verify-gate build reports.
#
#   powershell -ExecutionPolicy Bypass -File register-hypnos-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-hypnos-task.ps1 -Unregister

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "Yggdrasil HYPNOS Dreamworker"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed scheduled task '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m hypnos.daemon" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

# No RunLevel Highest: the sleeper needs no elevation, so it runs at
# the default limited level - quieter and safer.
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName': python -m hypnos.daemon, always-on dreamworker"
Write-Output "run 'Start-ScheduledTask -TaskName $taskName' to wake it now"
Write-Output "audit trail: $here\hypnos\data\audit.jsonl"
Write-Output "status:      python -m hypnos status"
