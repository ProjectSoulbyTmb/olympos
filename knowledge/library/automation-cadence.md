# Automation Cadence — watchdogs, schedules, and adaptive polling

## Layers of continuous assurance

1. CI on every push/PR: the same gates developers run, remotely, on a
   clean checkout. Fast subset first, doctor last.
2. Sentinel sweeps locally every N minutes: remediate safe artifacts →
   run all gates → append ledger. One remediated retry per red gate.
3. Nightly self-checks: heavier hygiene (store pruning, baseline
   rebuilds) with their own JSONL ledgers.
4. Adaptive cadence: watchdogs poll faster while findings are high and
   back off when calm; announce regressions the moment high-severity
   findings appear.

## Windows Scheduled Task craft

Explicit python path resolution (LOCALAPPDATA then PATH); WorkingDirectory
set to repo root; flags: -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
-StartWhenAvailable -MultipleInstances IgnoreNew; ExecutionTimeLimit just
above worst-case runtime. Unregister switch for clean removal. Tasks are
idempotent to re-register (-Force).

## What automation may do alone

Safe remediations only: purge stale bytecode, recreate missing data
dirs, rebuild stale integrity baselines, untrack build artifacts,
re-run gates after remediation. Code changes are REPORTED, never
auto-rewritten by shared infrastructure — each organ owns its own
repair brain.

## Escalation policy shape

Standing grants (L1) cover routine mutations with automatic safety
backups throttled per window; elevated (L2) operations demand an
authorized session per call and take backups before acting; a master
freeze switch stops everything except administrator resume. Autonomy
means diligence inside rails, not initiative outside scope.

## Heartbeats and liveness

Organs beat on a cadence (message-bus heartbeats or ledger touches);
watchdogs flag stale beats as attention items. Liveness data rides the
same bus as incidents so one sweep answers "what is alive, what needs
action, what regressed since last tick".

## Design-loop audits

Continuous architecture audits on push + schedule + local watch:
import cycles, seam violations, env-var drift against contracts, missing
license headers, oversized hotspots. Findings become severity-ranked
plans ("next") instead of tickets nobody reads.
