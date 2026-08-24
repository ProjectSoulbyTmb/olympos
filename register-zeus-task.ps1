# Registers (or removes) a Windows Scheduled Task that keeps ZEUS -
# the workspace protection kernel - hosting continuously. ZEUS then
# patrols processes, integrity and churn every 5 seconds around the
# clock, with its audit trail in zeus/data/audit.jsonl.
#
#   powershell -ExecutionPolicy Bypass -File register-zeus-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-zeus-task.ps1 -Unregister

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos ZEUS Guardian"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed scheduled task '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m zeus.server" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

# RunLevel Highest: the task runs elevated without per-run UAC prompts.
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Output "registered '$taskName': python -m zeus.server, always-on guardian"
Write-Output "run 'Start-ScheduledTask -TaskName $taskName' to fire it now"
Write-Output "audit trail: $here\zeus\data\audit.jsonl"
