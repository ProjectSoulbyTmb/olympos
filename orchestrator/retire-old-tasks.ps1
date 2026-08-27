param(
    [switch]$Delete,
    [switch]$SkipSweep
)

$ErrorActionPreference = 'Continue'
$names = @(
    'voltage-gaia', 'voltage-sentinel', 'voltage-zeus',
    'Persephone Guardian', 'EidovaraThothWatchdog',
    'Olympos ARES Exposure Sweep', 'Olympos ARTEMIS Huntress',
    'Olympos HYPNOS Dreamworker', 'Olympos KRONOS Governor',
    'Olympos POSEIDON Tide', 'Olympos RELAY Bridge',
    'Olympos ZEUS Guardian',
    'Yggdrasil HEBE Scribe', 'Yggdrasil HYPNOS Dreamworker',
    'Yggdrasil ZEUS Guardian'
)

if ($Delete) {
    foreach ($n in $names) {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if ($t) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            Write-Output "DELETED: $n"
        }
    }
    Write-Output "phase B complete"
    return
}

$backupDir = 'C:\Users\Earth949\.thoth-private\task-backup-2026-08-25'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
foreach ($n in $names) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $t) { Write-Output "SKIP (missing): $n"; continue }
    $f = Join-Path $backupDir (($n -replace ' ', '_') + '.xml')
    if (-not (Test-Path $f)) {
        Export-ScheduledTask -TaskName $n | Set-Content -LiteralPath $f -Encoding Unicode
    }
    Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $n | Out-Null
    Write-Output "DISABLED: $n"
}

if ($SkipSweep) { Write-Output "sweep skipped"; return }

Start-Sleep -Seconds 2

$mypid = $PID
$patterns = @(
    '-m\s+zeus\.server',
    '-m\s+hypnos\.daemon',
    '-m\s+relay\s+watch',
    '-m\s+artemis\b',
    '-m\s+poseidon\s+watch',
    '-m\s+kronos\b',
    '-m\s+hebe\s+watch',
    'sentinel\.py',
    'persephone\.py',
    'gaia\.mjs',
    'zeus[/\\]cli\.py',
    '-m\s+ares\s+sweep',
    'actions-runner'
)
$regex = ($patterns -join '|')
$victims = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $mypid -and
        $_.CommandLine -and
        $_.CommandLine -match $regex -and
        $_.Name -match '^(python|pythonw|node|cmd|pwsh|powershell|Runner)'
    }
foreach ($v in $victims) {
    try {
        Stop-Process -Id $v.ProcessId -Force -ErrorAction Stop
        Write-Output ("KILLED ORPHAN: pid={0} name={1} :: {2}" -f $v.ProcessId, $v.Name, $v.CommandLine.Substring(0, [Math]::Min(100, $v.CommandLine.Length)))
    } catch {
        Write-Output "could not kill pid=$($v.ProcessId): $_"
    }
}
Write-Output "phase A complete: disabled + swept"
