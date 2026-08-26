# Registers (or removes) the ARES exposure sweep: a scheduled task
# that dry-runs the auto-lock profile and journals what is still
# unsealed. It deliberately stores NO secrets - unattended sealing
# would need your passphrase, which ARES refuses by design.
#
#   powershell -ExecutionPolicy Bypass -File register-autolock.ps1
#   powershell -ExecutionPolicy Bypass -File register-autolock.ps1 -Profile work
#   powershell -ExecutionPolicy Bypass -File register-autolock.ps1 -Unregister

param(
    [switch]$Unregister,
    [string]$Profile = "night"
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos ARES Exposure Sweep"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false `
        -ErrorAction SilentlyContinue
    Write-Output "removed '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute "python.exe" `
    -Argument "-m ares sweep --profile $Profile" `
    -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
$trigger.Repetition.Duration = "P3650D"
$trigger.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName': exposure sweep every 15 minutes (profile '$Profile')"
Write-Output "log: $here\data\ares\exposure.jsonl"
Write-Output "note: sweep reports only; run 'ares lock --profile $Profile' to actually seal"
