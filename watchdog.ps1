# Olympos guardian watchdog - the fix for "Running but dead".
#
# Task Scheduler restarts a task on FAILURE, but a daemon that exits
# cleanly (or gets stopped mid-reorganization) leaves the task in
# Ready and nothing revives it - HYPNOS went dark exactly that way.
# This watchdog closes the gap on two levels:
#
#   1. task state: any Olympos guardian not Running gets started;
#   2. liveness: HYPNOS reporting Running with a stale heartbeat is
#      a zombie - stop it, then start it fresh.
#
# Registered by register-watchdog-task.ps1 every 5 minutes; logs to
# data/watchdog.jsonl (ignored runtime state). Safe to run manually.

$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $here "data\watchdog.jsonl"
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

function Write-Log([string]$event, [string]$detail) {
    try {
        $rec = @{ t = (Get-Date -Format o); event = $event;
                  detail = $detail } | ConvertTo-Json -Compress
        Add-Content -Path $log -Value $rec -ErrorAction SilentlyContinue
    } catch { }
}

# --- level 2 probe first: is HYPNOS actually alive inside its task? ---
$hypnosStale = $false
try {
    Push-Location $here
    $age = & $python -c "import sys; sys.path.insert(0,'.');`nfrom ratatosk.bus import Post;`na = Post().heartbeat_age('hypnos');`nprint(-1 if a is None else a)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $null -ne $age) {
        $ageNum = [double]$age
        if ($ageNum -lt 0 -or $ageNum -gt 300) { $hypnosStale = $true }
    }
} catch { }
finally { Pop-Location }

foreach ($name in @("Olympos ZEUS Guardian",
                    "Olympos HYPNOS Dreamworker",
                    "Olympos GAIA Pulse")) {
    try {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
        $running = ($task.State -eq "Running")

        if (-not $running) {
            Start-ScheduledTask -TaskName $name
            Write-Log "revived" "$name was $($task.State)"
            continue
        }
        if ($name -like "*HYPNOS*" -and $hypnosStale) {
            Stop-ScheduledTask -TaskName $name
            Start-Sleep -Seconds 2
            Start-ScheduledTask -TaskName $name
            Write-Log "zombie-restart" "$name heartbeat stale >300s"
        }
    }
    catch {
        # task not registered at all - nothing this run can do beyond
        # noting it; register-olympos-tasks.ps1 is the installer of record
        Write-Log "missing" "$name not registered"
    }
}

# --- escalation: a guardian flapping >=3 revives/hour is an incident,
# --- broadcast on the bus so the rest of the organism sees it
try {
    $cutoff = (Get-Date).AddHours(-1).ToString("o")
    $revives = Get-Content $log -ErrorAction SilentlyContinue |
        ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } |
        Where-Object { $_ -and $_.event -eq "revived" -and $_.t -ge $cutoff }
    $flaps = $revives | Group-Object detail |
        Where-Object { $_.Count -ge 3 }
    foreach ($g in $flaps) {
        & $python -c "import sys; sys.path.insert(0, '.'); from ratatosk.bus import publish; publish('incidents', {'kind': 'watchdog-flap', 'organ': sys.argv[1], 'revives_last_hour': int(sys.argv[2])}, frm='watchdog')" $g.Name $g.Count 2>$null
        Write-Log "flap-alert" "$($g.Name): $($g.Count) revives in the last hour"
    }
} catch { }
