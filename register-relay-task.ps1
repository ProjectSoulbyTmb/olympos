# Registers (or removes) a Windows Scheduled Task that keeps RELAY -
# the daedalus<->venus bridge - running continuously. Every cycle it
# forwards workshop build outcomes to the venus mailbox + `updates`
# topic, drains Venus intents (build / repair / status) from
# assistant/data/relay/to-fleet/, and publishes the constant fleet
# update stream with a heartbeat.
#
#   powershell -ExecutionPolicy Bypass -File register-relay-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-relay-task.ps1 -Unregister

param(
    [switch]$Unregister,
    [int]$Every = 60
)

$ErrorActionPreference = "Stop"
$taskName = "Olympos RELAY Bridge"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed scheduled task '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m relay watch --every $Every" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

# No RunLevel Highest: the bridge owns no elevated surface.
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName': python -m relay watch --every $Every"
Write-Output "run 'Start-ScheduledTask -TaskName $taskName' to start streaming now"
