<#
MUSTER-FLEET - one-command continuation for the VOLTAGE build op.

Runs both halves of the fleet and reports a single verdict:

  Phase authoring : every registered DAEDALUS blueprint weaves +
                    passes its self-test gate (clean; breakers are
                    proven separately via tools/muster_launch.py).
  Phase sovereign : the sovereign coordinator (root declared by
                    boundary.py foreign-root) replays its manifest -
                    idempotent orders advance only on green, choke
                    halts cleanly.

Usage:
  .\muster-fleet.ps1                 # full fleet sweep
  .\muster-fleet.ps1 -Quick          # apollo-os muster + coord dry-run
  .\muster-fleet.ps1 -SovereignOnly  # just the manifest pump
  .\muster-fleet.ps1 -SkipSovereign  # just the authoring sweep
  .\muster-fleet.ps1 -FailFast       # stop authoring sweep on first red

Exit 0 only when every recorded check is green.
NOTE: the full sovereign pump can run several minutes on first
advance; launch from a normal console (not a tight timeout window)
or let the voltage-* cadences carry routine verification.
#>
param(
    [switch]$Quick,
    [switch]$SovereignOnly,
    [switch]$SkipSovereign,
    [switch]$FailFast
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$results = [System.Collections.Generic.List[object]]::new()

function Record($phase, $name, $ok, $detail) {
    $results.Add([pscustomobject]@{ Phase = $phase; Name = $name
                                    Green = [bool]$ok; Detail = $detail })
    $tag = if ($ok) { 'GREEN' } else { 'RED  ' }
    Write-Host ("[{0}] {1,-22} {2}" -f $tag, $phase, $detail)
}

# ------------------------------------------------- phase 1: authoring
if (-not $SovereignOnly) {
    $names = python -c "import sys; sys.path.insert(0,'.'); from daedalus.blueprints import blueprint_names as b; print(' '.join(b()))"
    if ($LASTEXITCODE -ne 0) {
        Record 'authoring' 'blueprint-registry' $false 'unreadable'
    } else {
        foreach ($bp in ($names -split ' ')) {
            if ($Quick -and $bp -ne 'apollo-os') { continue }
            $out = python tools\muster_launch.py $bp 2>&1
            $ok = ($LASTEXITCODE -eq 0)
            $tail = ([string]($out | Select-Object -Last 1))
            Record 'authoring' $bp $ok $tail
            if ($FailFast -and -not $ok) { break }
        }
    }
}

# ------------------------------------------------ phase 2: sovereign
if (-not $SkipSovereign) {
    # Drain fully before reading $LASTEXITCODE (Select-Object -First
    # cancels upstream and poisons the native exit code).
    $vraw = & python (Join-Path $here 'boundary.py') foreign-root
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace("$vraw")) {
        Record 'sovereign' 'boundary' $false `
            ('foreign-root unresolved (boundary.py exit {0})' -f `
                $LASTEXITCODE)
    } else {
        $vroot = @($vraw)[0].ToString().Trim()
        if (Test-Path (Join-Path $vroot 'ops\coordinator.py')) {
            Push-Location $vroot
            try {
                if ($Quick) {
                    $out = python ops\coordinator.py --dry-run 2>&1
                    $ok = ($LASTEXITCODE -eq 0)
                    Record 'sovereign' 'coordinator(dry)' $ok `
                        ([string]($out | Select-Object -First 1))
                } else {
                    $out = python ops\coordinator.py 2>&1
                    $ok = ($LASTEXITCODE -eq 0)
                    $tail = ([string](($out | Select-Object -Last 2) -join ' | '))
                    Record 'sovereign' 'manifest-pump' $ok $tail
                }
            } finally { Pop-Location }
        } else {
            Record 'sovereign' 'coordinator' $false "$vroot missing"
        }
    }
}

# ------------------------------------------------------------ verdict
$red = @($results | Where-Object { -not $_.Green })
Write-Host ''
Write-Host ("== MUSTER FLEET: {0}/{1} green ==" -f `
        ($results.Count - $red.Count), $results.Count)
foreach ($r in $red) {
    Write-Host ("   RED: {0} / {1}" -f $r.Phase, $r.Name)
}
if ($red.Count -eq 0) { exit 0 } else { exit 1 }
