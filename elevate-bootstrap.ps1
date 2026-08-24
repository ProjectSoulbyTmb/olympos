# One-time elevation bootstrap - the LAST UAC prompt you will ever
# answer on this machine. Run me once, click Accept, and from then on:
#
#   - every Yggdrasil guardian runs ELEVATED via Task Scheduler with
#     no prompt (scheduled tasks with RunLevel Highest never trigger
#     UAC at start time), and
#   - Windows admin-consent policy is switched to silent, so any other
#     elevated launch on this box stops prompting too.
#
#   powershell -ExecutionPolicy Bypass -File elevate-bootstrap.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) { $node = "node" }

Write-Output "[1/3] registering all guardians at RunLevel Highest..."
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$pairs = @(
    @{ Name = "Yggdrasil ZEUS Guardian";
       Exe = $python; Args = "-m zeus.server"; Work = $here },
    @{ Name = "Yggdrasil HYPNOS Dreamworker";
       Exe = $python; Args = "-m hypnos.daemon"; Work = $here },
    @{ Name = "Yggdrasil GAIA Pulse";
       Exe = $node; Args = "gaia.mjs pulse --watch --every 15m";
       Work = (Join-Path $here "gaia") }
)
foreach ($p in $pairs) {
    $action = New-ScheduledTaskAction -Execute $p.Exe `
        -Argument $p.Args -WorkingDirectory $p.Work
    Register-ScheduledTask -TaskName $p.Name -Action $action `
        -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date)) `
        -Settings $settings -RunLevel Highest -Force | Out-Null
    Write-Output ("  highest: {0}" -f $p.Name)
}

Write-Output "[2/3] switching Windows admin-consent to silent..."
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "ConsentPromptBehaviorAdmin" -Value 0 -Type DWord
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "PromptOnSecureDesktop" -Value 0 -Type DWord

Write-Output "[3/3] restarting guardians on their new level..."
foreach ($p in $pairs) {
    Stop-ScheduledTask -TaskName $p.Name -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    Start-ScheduledTask -TaskName $p.Name
}

Write-Output ""
Write-Output "bootstrap complete: elevated, unattended, prompt-free."
