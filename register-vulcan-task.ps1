# Register (or remove) the VULCAN building sandbox as a Windows Scheduled
# Task: hosts the authoritative JSON-lines server (auto-tick, warden
# self-healing) continuously, surviving logon/restart.
#
#   powershell -ExecutionPolicy Bypass -File register-vulcan-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-vulcan-task.ps1 -Unregister

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos Vulcan Sandbox"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$kernel = Join-Path $here "vulcan\host.py"
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python.exe" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "vulcan task removed"
    exit 0
}

# Long-lived daemon: no execution-time limit; restart on failure.
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-u `"$kernel`"" `
    -WorkingDirectory (Join-Path $here "vulcan")
$trigger = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "vulcan registered: server hosts at 127.0.0.1:43901 on logon"
Write-Host "next steps:"
Write-Host "  start now:        vulcan\launch_vulcan.bat"
Write-Host "  console:          python -m vulcan"
Write-Host "  connect:          python -m vulcan.cli --connect 127.0.0.1 43901"
Write-Host "  verify gate:      python vulcan/verify_vulcan.py"
