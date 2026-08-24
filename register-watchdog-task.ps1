# Registers (or removes) the Olympos guardian watchdog: a light
# scheduled task that every 5 minutes revives guardians left in
# Ready state and zombie-restarts HYPNOS on a stale heartbeat.
#
#   powershell -ExecutionPolicy Bypass -File register-watchdog-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-watchdog-task.ps1 -Unregister

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos Watchdog"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false `
        -ErrorAction SilentlyContinue
    Write-Output "removed '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\watchdog.ps1`"" `
    -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
# PS 5.1 rejects TimeSpan.Zero as "never stop"; an explicit long ISO
# duration is the accepted way to keep the sweep effectively endless
$trigger.Repetition.Duration = "P3650D"
$trigger.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName': watchdog sweep every 5 minutes"
Write-Output "log: $here\data\watchdog.jsonl"
