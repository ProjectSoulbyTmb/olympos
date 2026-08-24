# Registers HEBE - the Legal & Document Scribe - as a Windows
# Scheduled Task so dictation, legal record-keeping and the
# commit/push lane run around the clock:
#
#   .\register-hebe-task.ps1                    # cycle every 5 minutes
#   .\register-hebe-task.ps1 -AtLogon           # start at logon
#
# One-time registration must be run from an elevated PowerShell.
# Remove with: Unregister-ScheduledTask -TaskName "Yggdrasil HEBE Scribe"

param(
    [int]$IntervalMinutes = 5,
    [switch]$AtLogon
)

$ErrorActionPreference = "Stop"

$taskName = "Yggdrasil HEBE Scribe"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m hebe watch --interval $($IntervalMinutes * 60)" `
    -WorkingDirectory $here
if ($AtLogon) {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
} else {
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Output "registered task '$taskName' (decree every $IntervalMinutes min)"
