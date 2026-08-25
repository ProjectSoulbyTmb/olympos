# Registers (or removes) the OLYMPOS ARTEMIS huntress: a hidden,
# windowless scheduled task that sweeps the fleet every 5 minutes for
# specific known error signatures and applies bounded repairs.
#
#   powershell -ExecutionPolicy Bypass -File register-artemis-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-artemis-task.ps1 -Unregister
#
# The continuous always-on variant is installed by
# register-olympos-tasks.ps1 as "Olympos ARTEMIS Huntress"; both share
# one task name so re-running either refreshes the same definition.

param(
    [switch]$Unregister,
    [int]$EveryMinutes = 5
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos ARTEMIS Huntress"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false `
        -ErrorAction SilentlyContinue
    Write-Output "removed '$taskName'"
    exit 0
}

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m artemis --watch $($EveryMinutes * 60)" `
    -WorkingDirectory $here
# PS 5.1 rejects TimeSpan.Zero as "never stop"; an explicit long ISO
# duration keeps the patrol effectively endless (watchdog precedent)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$trigger.Repetition.Duration = "P3650D"
$trigger.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName': hunt sweep every $EveryMinutes minutes (hidden)"
Write-Output "ledger: $here\data\artemis\hunt.jsonl"
Start-ScheduledTask -TaskName $taskName
Write-Output "huntress armed."
