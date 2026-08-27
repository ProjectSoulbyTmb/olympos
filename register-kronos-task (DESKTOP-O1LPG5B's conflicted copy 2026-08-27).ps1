# Registers (or removes) a Windows Scheduled Task that keeps KRONOS -
# the resource governor - watching continuously. When RAM holds above
# the strain line, the deferrable patrol tasks are stopped; when calm
# returns, they are started again. The ZEUS guardians stay on through
# any hold.
#
#   powershell -ExecutionPolicy Bypass -File register-kronos-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-kronos-task.ps1 -Unregister

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos KRONOS Governor"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed scheduled task '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m kronos" -WorkingDirectory $here
$once = New-ScheduledTaskTrigger -Once -At (Get-Date)
$logon = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

# RunLevel Highest, per elevate-bootstrap doctrine: every guardian on
# this box runs highest under silent admin-consent, and an elevated
# governor can manage even elevated fleet tasks. ZEUS stays safe by
# law, not by luck: the manifest whitelist plus the controller's
# ZEUS-marker veto refuse such stops in code, proven by the gate.
# Hidden: the watch loop is silent - no console window, ever.
$settings.Hidden = $true
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $once, $logon -Settings $settings `
    -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

Write-Output "registered and started '$taskName': python -m kronos"
Write-Output "status:      python -m kronos status"
Write-Output "event log:   $here\kronos\data\events.jsonl"
