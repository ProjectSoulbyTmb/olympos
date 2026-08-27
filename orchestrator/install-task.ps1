$ErrorActionPreference = 'Stop'
$pythonDir = 'C:\Users\Earth949\AppData\Local\Programs\Python\Python312'
$pywExe = Join-Path $pythonDir 'pythonw.exe'
if (-not (Test-Path $pywExe)) { throw "pythonw.exe not found at $pywExe" }

$action = New-ScheduledTaskAction `
    -Execute $pywExe `
    -Argument '"D:\olympos\orchestrator\orchestrator.pyw"' `
    -WorkingDirectory 'D:\olympos\orchestrator'

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName 'Olympus Orchestrator' `
    -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName 'Olympus Orchestrator'
Write-Output "registered + started \Olympus Orchestrator"
