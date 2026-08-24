# Register (or remove) PERSEPHONE guardian as a Windows Scheduled Task:
# integrity + liveness sweeps every 5 minutes and at logon.
#
#   powershell -ExecutionPolicy Bypass -File register-persephone-task.ps1
#   powershell -ExecutionPolicy Bypass -File register-persephone-task.ps1 -Unregister

param(
    [switch]$Unregister,
    [int]$IntervalMinutes = 5
)

$ErrorActionPreference = "Stop"
$taskName = "Persephone Guardian"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$kernel = Join-Path $here "persephone\persephone.py"
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python.exe" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "persephone task removed"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-u `"$kernel`" --once" `
    -WorkingDirectory (Join-Path $here "persephone")
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger @($trigger, $logonTrigger) -Settings $settings -Force | Out-Null
Write-Host "persephone registered: sweep every $IntervalMinutes min + at logon"
Write-Host "next steps:"
Write-Host "  1. baseline vaults:  python persephone\persephone.py --snapshot"
Write-Host "  2. mint entitlements: python persephone\persephone.py --attest aphrodite --days 365"
Write-Host "                        python persephone\persephone.py --attest riley --days 365"
Write-Host "  3. continuous mode:   persephone\launch_persephone.bat"
