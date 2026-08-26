# Registers (or removes) a Windows Scheduled Task that keeps DAEDELUS -
# the fleet's official system updater - cycling unattended. Every cycle
# the workshop takes queued build intents, commissions full blueprint
# constructions through the ATLAS-gated pipeline, verifies results, and
# publishes the update stream; output logs to docs/plans/updates/.
#
#   powershell -ExecutionPolicy Bypass -File register-daedalus-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-daedalus-task.ps1 -Unregister
#
# No RunLevel Highest: the workshop owns no elevated surface.

param(
    [switch]$Unregister,
    [int]$Every = 180
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos DAEDELUS Workshop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ps = (Get-Command powershell).Source

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed scheduled task '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $ps `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\daedalus-cycle.ps1`"" `
    -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $Every)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName': daedalus-cycle.ps1 every $Every minutes"
Write-Output "run 'Start-ScheduledTask -TaskName $taskName' to commission an update cycle now"
