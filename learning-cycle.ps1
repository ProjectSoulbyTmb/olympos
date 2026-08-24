# ATHENA learning subfleet - one-shot runner
#
# Runs the three learners in sequence (metis -> argus -> logia), each
# headlessly via opencode with cwd pinned to this repo root. Individual
# failures do not abort the fleet; a summary prints at the end.
#
# Manual use:
#   .\learning-cycle.ps1                     # full subfleet sweep
#   .\learning-cycle.ps1 -Focus "port drift" # steers all three
#
# Scheduled autonomy (weekly stagger) - see register-learning-tasks.ps1.

param(
    [string]$Focus = ""
)

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$logDir = Join-Path $root "docs\plans\learning"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$fleet = @("metis", "argus", "logia")
$stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
$results = @()

foreach ($agent in $fleet) {
    Write-Host "== learning subfleet: $agent =="
    & opencode run --agent $agent $Focus 2>&1 |
        Tee-Object -FilePath (Join-Path $logDir "$stamp-$agent.md")
    $results += "$agent=$LASTEXITCODE"
}

Write-Host "== subfleet summary =="
$results | ForEach-Object Write-Host

$failed = ($results | Where-Object { $_ -match "=([1-9]\d*)$" }).Count
if ($failed -ge $fleet.Count) {
    Write-Error "entire learning subfleet failed"
    exit 1
}
exit 0
