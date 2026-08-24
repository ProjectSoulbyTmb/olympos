# Registers ANY command as an elevated Windows Scheduled Task so Thoth
# automation can run with admin rights without per-run UAC prompts.
#
#   .\register-thoth-task.ps1 -Name "Thoth Nightly Build" `
#       -Command "python" -Args "build.py" -IntervalMinutes 1440
#
# One-time registration must be run from an elevated PowerShell.
# Remove with: Unregister-ScheduledTask -TaskName "<name>"

param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$Command,
    [string]$Args = "",
    [int]$IntervalMinutes = 60,
    [switch]$AtLogon
)

$ErrorActionPreference = "Stop"

$action = New-ScheduledTaskAction -Execute $Command -Argument $Args
if ($AtLogon) {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
} else {
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries

Register-ScheduledTask -TaskName $Name -Action $action `
    -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Output "registered elevated task '$Name'"
