# Registers (or removes) the full SOUL autopilot: every always-on
# organ as an elevated, restart-on-failure Windows Scheduled Task.
# One command turns a fresh machine into a self-guarding,
# self-verifying organism:
#
#   ZEUS    - 5s protection patrols (processes/integrity/churn)
#   HYPNOS  - silent task worker + continuous verify-gate builds
#   GAIA    - fleet-health pulse scoring every organ, history kept
#
#   powershell -ExecutionPolicy Bypass -File register-soul-tasks.ps1
#   powershell -ExecutionPolicy Bypass -File register-soul-tasks.ps1 -Unregister
#
# Idempotent: re-running refreshes definitions (-Force). Individual
# per-organ scripts keep working; task names match theirs.

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) { $node = "node" }

function Install-OrganTask {
    param([string]$Name, [string]$Exe, [string]$ArgList,
          [string]$WorkDir, [bool]$Elevated)
    if ($Unregister) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false `
            -ErrorAction SilentlyContinue
        Write-Output "removed '$Name'"
        return
    }
    $action = New-ScheduledTaskAction -Execute $Exe -Argument $ArgList `
        -WorkingDirectory $WorkDir
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    $level = if ($Elevated) { "Highest" } else { "Limited" }
    Register-ScheduledTask -TaskName $Name -Action $action `
        -Trigger $trigger -Settings $settings -RunLevel $level `
        -Force | Out-Null
    Write-Output "registered '$Name' -> $Exe $ArgList"
}

Install-OrganTask "Yggdrasil ZEUS Guardian" $python `
    "-m zeus.server" $here $true
Install-OrganTask "Yggdrasil HYPNOS Dreamworker" $python `
    "-m hypnos.daemon" $here $false
Install-OrganTask "Yggdrasil GAIA Pulse" $node `
    "gaia.mjs pulse --watch --every 15m" (Join-Path $here "gaia") $false

if ($Unregister) { exit 0 }

Write-Output ""
Write-Output "autopilot armed. starting all three now..."
Start-ScheduledTask -TaskName "Yggdrasil ZEUS Guardian"
Start-ScheduledTask -TaskName "Yggdrasil HYPNOS Dreamworker"
Start-ScheduledTask -TaskName "Yggdrasil GAIA Pulse"
Write-Output ""
Write-Output "observe the organism:"
Write-Output "  python -m ratatosk status          # organ heartbeats + mail"
Write-Output "  type hypnos\data\build.json        # latest self-verification"
Write-Output "  zeus\data\audit.jsonl              # protection trail"
