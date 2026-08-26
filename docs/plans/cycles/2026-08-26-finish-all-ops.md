# Finish-all ops record - 2026-08-26 (Hermes lane)

Operator order: "finish all" (the three debts named in the ship report).
Executed through auto/hermes per FLOW.md. PRs: #104 (batch), #105
(boundary scrub, landed by a concurrent lane), #106 (repairs). Main at
a405e08 after this session's work.

## Debt 1: D:\VOLTAGE literals red in CI (ecosystem)

Root cause: land-all.ps1:25 + muster-fleet.ps1:9,63,64,79 hard-coded the
foreign root; verify_boundary.py's content scan forbids literals in
executables (ADR-0002 scope rule). Documented since volt-comm night as
needing operator adjudication; "finish all" authorized the W0-pattern fix.

Fix (landed via #104, re-landed independently as #105 by a concurrent
lane - contents equivalent):
- boundary.py gained the `foreign-root` CLI verb - the ONE allowlisted
  place speaking the literal becomes a resolution seam for scripts.
- land-all.ps1 + muster-fleet.ps1 resolve the root live through it.
- verify_boundary.py 12/12; muster-fleet -SovereignOnly -Quick GREEN.

Bug found while smoke-testing: `Select-Object -First 1` on a native
pipeline cancels upstream and poisons $LASTEXITCODE (-1 on success).
Both call sites drain fully before reading the exit code.

## Debt 2: flow.ps1 merged ahead of required checks (L046)

Three occurrences before truly fixed:
1. PR #101/#104: no gate existed; gh pr merge fired immediately.
2. First patch attempt landed on the MIRROR copy (D:\THOTH\flow.ps1)
   instead of the worktree - commit shipped the claim without code and
   its Wait-Checks raced the "no checks reported yet" window after
   gh pr create, treating it as pass-through.
3. PR #106: worktree v2 committed correctly but the EXECUTING copy was
   still pristine (mirror), so the merge raced again.

Final state (main a405e08): Wait-Checks requires checks to EXIST and
COMPLETE green; the registration window counts as pending;
-NoWaitChecks is the explicit operator bypass. The law now executes from
the mirror on every future ship.

## Debt 3: stranded godot-knowledge-db extras

Recovered from parked ref e960b73 into #104:
- build_godot_db.py hardened (multi-carrier date probes, author byline,
  release classifier table, argparse CLI, table-counted reports) -
  fixes real bugs in main's copy ("aintenance release" substring checks,
  always-true sponsor filter via `or True` precedence).
- query_godot_db.py + verify_godot_knowledge_db.py + README.md landed.
- godot_knowledge.db untracked as build product; .gitignore + requirements
  notes added. Hermetic gate 6/6 green offline.
- Registered as hypnos build gate per autopilot law (#106).

## Collateral repairs surfaced by CI

- kronos/verify_kronos.py was also missing from BUILD_GATES (rode in on
  fc2728c) - registered alongside godot (#106).
- daedalus watcher_cannot_approve_or_resize_on_wire red on this lineage:
  the plan_list/plan_show watcher-read rights fix existed only on the
  salvage lane (1fb4d9e). Ported to norn/rights.py -> daedalus 23/23
  (#106).

## Verification chain

doctor --ci STABLE at every landing; verify_boundary 12/12; godot gate
6/6; autopilot 6/6; hypnos 25/25; norn 6/6; daedalus 23/23; safeguards
pre-commit clean on all three commits; PowerShell parsers green.

## Known residue

- CI runner earth949-d (D:\actions-runner) died twice with
  "Exiting after unknown error code: -1" (found offline at ~09:34Z with
  orphaned queued jobs; crashed again after the 10:29 restart mid-job -
  GitHub marked the job failed via MarkJobAsFailedOnWorkerCrash with no
  failing step). Restarted interactively; jobs flow again and the rerun
  passed. Root cause unknown - recommend registering the runner under a
  scheduled task with restart-on-failure (register-watchdog-task.ps1
  pattern) so a dead listener self-heals.
- PRs #101/#104/#106 merged while their checks were pending (no
  server-side enforcement on the private repo); each landing was proven
  locally before and after. From a405e08 forward the client-side law is
  real; server-side rulesets still need GitHub Pro.
- DESIGN.md carries the same night-entry twice (:293/:425) - both now
  annotated with lineage attribution; dedupe decision left to operator.
- Mirror WIP snapshots preserved at Temp\opencode\20260826-mirror-wip\
  (knowledge.js editorial tweak awaiting its owner's lane).
