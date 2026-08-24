# Registers POSEIDON - the tide kernel - as a Windows Scheduled Task
# so the commit/push workflow runs around the clock:
#
#   .\register-poseidon-task.ps1                  # tide every 5 minutes
#   .\register-poseidon-task.ps1 -AtLogon         # start at logon
#
# One-time registration must be run from an elevated PowerShell.
# Remove with: Unregister-ScheduledTask -TaskName "Yggdrasil POSEIDON Tide"

param(
    [int]$IntervalMinutes = 5,
    [switch]$AtLogon
)

$ErrorActionPreference = "Stop"

$taskName = "Yggdrasil POSEIDON Tide"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m poseidon watch --interval $($IntervalMinutes * 60)" `
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
Write-Output "registered task '$taskName' (tide every $IntervalMinutes min)"
