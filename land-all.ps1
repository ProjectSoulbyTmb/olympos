<#
LAND-ALL - commit (and optionally push) both fleets' drift.
Generated 2026-08-25 for the VOLTAGE / Creative Control OS session.

Usage:
  .\land-all.ps1                 # commit Olympos + VOLTAGE (no push)
  .\land-all.ps1 -Push           # commit and push each to its origin
  .\land-all.ps1 -Target voltage # just the sovereign tree
  .\land-all.ps1 -Target olympos # just this authoring tree

Pre-gates (skippable with -SkipGates):
  Olympos : python safeguards\check.py --strict <changed files>
  Voltage : python verify_secrets.py

transfer\ is a transport artifact and is deliberately NOT committed.
#>
param(
    [ValidateSet('both', 'olympos', 'voltage')] [string]$Target = 'both',
    [switch]$Push,
    [switch]$SkipGates
)

$ErrorActionPreference = 'Continue'
$olympos = Split-Path -Parent $MyInvocation.MyCommand.Path
$voltage = (python (Join-Path $olympos 'boundary.py') 'foreign-root')

$MSG_OLYMPOS = @'
voltage authoring stack: Creative Control OS blueprints + closure docs

Scope: ONLY the voltage authoring session files listed explicitly
below - parallel-lane work in this checkout is deliberately excluded.

- apollo-os command plane blueprint (grammar/rights/sessions/dispatch/
  witness/seals + drop-in extension protocol) with gate + breakers
- studio tier: kinema-host, riley-bridge, media-lane, ent-composer,
  game-domain blueprints (B7 digests, relay-parity keys, containment)
- mind tier: know-gateway, learn-gateway, muse-curriculum (organ-law
  conforming MUSE-### schema), voltage-tasks installer blueprint
- hardening: ops-domain single-use confirms, session-seal chains,
  sla-pulse injected-clock SLOs, voltage-packager release law
- tools: muster_launch.py harness, voltage_export.py seeder
- docs: ADR-0005, command-spec v1, roadmap V6-V9 status, DESIGN log
- muster-fleet.ps1 continuation command + land-all.ps1 itself
'@

$OLYMPOS_PATHS = @(
    'daedalus/blueprint_apollo.py',
    'daedalus/blueprint_kinemahost.py',
    'daedalus/blueprint_rileybridge.py',
    'daedalus/blueprint_medialane.py',
    'daedalus/blueprint_entcomposer.py',
    'daedalus/blueprint_gamedomain.py',
    'daedalus/blueprint_knowgateway.py',
    'daedalus/blueprint_learngateway.py',
    'daedalus/blueprint_muse.py',
    'daedalus/blueprint_voltagetasks.py',
    'daedalus/blueprint_opsdomain.py',
    'daedalus/blueprint_sealchain.py',
    'daedalus/blueprint_slapulse.py',
    'daedalus/blueprint_packager.py',
    'daedalus/blueprints.py',
    'tools/muster_launch.py',
    'tools/voltage_export.py',
    'docs/adr/0005-voltage-creative-control-os.md',
    'docs/contracts/voltage-command-spec-v1.md',
    'docs/plans/project-voltage-roadmap.md',
    'DESIGN.md',
    'muster-fleet.ps1',
    'land-all.ps1'
)

$MSG_VOLTAGE = @'
commissioning: drive manifest green through C1 + promote P-phase

- per-blueprint gate ceilings (gate_timeout_s) ending shared-60s stalls
- boundary jail: temp-sandbox exemption wired at coordinator arming;
  GIT_CONFIG_GLOBAL exported so scrubbed-env git trusts scratch repos
- norn gate: sanctioned Skip state for unseeded vulcan integrations
- sentinel infra-gate list trimmed to seeded membership
- gaia test invocation fixed to real test file
- P-phase: payload install w/ digest proof (organ/incoming),
  apollo-os commissioned at organ/apollo-os, live :44120 healthz probe
- registry rows apollo/44120, kinema-host/44130, riley-engine/44128;
  ratatosk command-plane catalogue constants; doctor SUITES += apollo
- C1 arming: voltage-sentinel/gaia/zeus cadences registered (Ready);
  push lane stays manual by law until auto-commit policy exists
- evidence: docs/evidence/{A*,B*,C1,P1,P2}.json + coordinator.jsonl
'@

function Land([string]$root, [string]$msg, [string]$label,
              [string[]]$exclude) {
    Write-Host "== landing $label ($root) =="
    if (-not (Test-Path (Join-Path $root '.git'))) {
        Write-Host "  SKIP: no .git at $root"; return
    }
    foreach ($e in $exclude) {
        $gi = Join-Path $root '.gitignore'
        if ((Test-Path $gi) -and
            -not (Select-String -Path $gi -SimpleMatch -Quiet $e)) {
            Add-Content $gi "`n# transport artifact`n$e/"
            Write-Host "  gitignore += $e/"
        }
    }
    if ($label -eq 'olympos') {
        # explicit manifest: this checkout carries parallel-lane work
        # that must NOT ride under this commit message
        git -C $root add -- @($OLYMPOS_PATHS)
    } else {
        git -C $root add -A
    }
    if ($LASTEXITCODE -ne 0) { Write-Host '  add FAILED'; $script:bad = $true; return }
    git -C $root commit -m $msg
    if ($LASTEXITCODE -eq 0) { Write-Host '  committed' }
    else { Write-Host '  nothing to commit or commit refused'; return }
    if ($Push) {
        git -C $root push
        Write-Host ("  push exit: {0}" -f $LASTEXITCODE)
    }
}

$script:bad = $false

if ($Target -in ('both', 'olympos')) {
    if (-not $SkipGates) {
        python safeguards\check.py --strict muster-fleet.ps1 `
            daedalus\blueprint_apollo.py daedalus\blueprint_muse.py `
            docs\plans\project-voltage-roadmap.md DESIGN.md
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'OLYMPOS GATES RED - refusing to land'; return
        }
    }
    Land $olympos $MSG_OLYMPOS 'olympos' @('transfer')
}

if ($Target -in ('both', 'voltage')) {
    if (-not $SkipGates) {
        Push-Location $voltage
        python verify_secrets.py | Select-Object -Last 2
        $secretsOk = ($LASTEXITCODE -eq 0)
        Pop-Location
        if (-not $secretsOk) {
            Write-Host 'VOLTAGE SECRETS RED - refusing to land'; return
        }
    }
    Land $voltage $MSG_VOLTAGE 'voltage' @()
}

Write-Host ''
if ($script:bad) { Write-Host 'LANDING HAD FAILURES'; exit 1 }
Write-Host 'LANDING COMPLETE'
