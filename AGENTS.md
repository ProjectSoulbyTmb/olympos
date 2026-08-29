# AGENTS.md - standing orders for every session in this repo

## Operator directive 2026-08-25: ALL BUILDING IS DELEGATED TO THE MUSTER FLEET

Construction is executed by subagents, never inline by the primary
session. The primary plans, dispatches, verifies, integrates, commits;
the fleet builds.

- **Build work** (design -> code -> verify -> prove -> seal -> ship):
  dispatch to the Daedalus workshop lane - @daedalus (plan/build
  orchestration), @epeios (standard construction), @icarus
  (fault-injection flight tests), @talos (gates + health patrols),
  @perdix (new blueprints), @kourai (lane tending), @kerux (update
  stream), @trophonios (provenance certification).
- **Knowledge cycles**: dispatch to the learning subfleet - @metis,
  @argus, @logia - under `fleet-learning` budgets, or run
  `/muster-fleet` for the full coordinated sweep.
- If no fleet agent fits the task, ESCALATE TO THE OPERATOR instead of
  building inline. Do not silently absorb build work into the primary.
- Reading, drift checks, gate runs, commit/bookkeeping stay with the
  primary; anything that constructs or modifies organ code does not.

Doctrine of record: `INTEGRATION.md`, `DESIGN.md`,
`knowledge/engineering-rules.md`, `.opencode/skills/athena-codex/SKILL.md`.
Shipping: `FLOW.md`. Repo homes: one localside home on `D:\` (L033);
this OneDrive checkout stays uncommitted-except-by-operator-order.

## Quick commands

```powershell
# arm the full autopilot (idempotent; ZEUS asks for one elevated run)
powershell -ExecutionPolicy Bypass -File register-olympos-tasks.ps1

# pre-commit static gates + fast verify suites (CI-equivalent)
python safeguards/check.py --all --strict

# full stabilization: entrypoints, component gates, baselines, stale bytecode
python doctor.py --ci          # CI subset
python doctor.py               # full + safe auto-repairs
python doctor.py --quick       # boot check only

# autopilot contract (every organ wired?)
python verify_autopilot.py

# release: validate tag -> changelog -> doctor
python release_gate.py v1.16.0
```

## Running a single verify gate

Every organ ships `verify_<realm>.py`. Run one in isolation:

```bash
python <realm>/verify_<realm>.py
```

Key gates: `vulcan`, `zeus`, `ratatosk`, `hades`, `norn`, `hypnos`,
`ptah`, `atlas`, `daedalus`, `relay`, `poseidon`, `hebe`, `kinema`,
`sindri`, `forseti`, `harmonia`, `persephone`, `ares`, `haven`,
`artemis`, `learning`, `buskit`, `secrets`, `coverage`, `scope`,
`boundary`, `autopilot`, `system`, `mirror_sync`, `riley_satellite`,
`riley_studio`. Plus `knowledge/verify_knowledge.py` and
`verify_godot_blueprint.py`, `verify_deskmate.py`.

## Verification order

When shipping a change, run gates in this order - each is a hard gate,
exit non-zero means fix before proceeding:

1. `python safeguards/check.py --all --strict` - syntax, dupdefs, JSON, secrets
2. `python doctor.py --ci` - entrypoints, component gates, baselines
3. `python verify_autopilot.py` - autopilot contract
4. `python safeguards/gate.py --full --timeout 600` - parallel bounded gates
5. `python verify_system.py` - system seam (replay, witness, bus, ledger)

## Running a single test / suite

- **GAIA** (Node): `cd gaia && npm install --no-save && npm test`
- **PTAH**: `python -m ptah selfcheck` (automation) or `python -m ptah benchmark --backend ollama --runs 3 --json`
- **Learning**: `python -m learning report` (queue) / `python -m learning propose` (stage)
- **Poseidon**: `python -m poseidon once --dry-run` (plan) / `python -m poseidon watch --interval 300`
- **Ratatosk**: `python -m ratatosk status` / `python -m ratatosk demo`
- **Hades**: `python hades/cli.py seal` / `python hades/cli.py scan`
- **Hebe**: `python -m hebe dictate ...` / `python -m hebe advise licenses` / `python -m hebe once --dry-run`
- **Relay**: `python -m relay watch` / `python -m relay riley`

## Multi-agent git flow

- Root checkout (`D:\THOTH`) is an integration mirror: it pulls, never hosts commits.
- Each writer owns a worktree under `.worktrees/<name>` on branch `auto/<name>`.
- Ship via `powershell -File flow.ps1 ship -Name <you> -Message "..."`
  (commit -> push -> PR -> squash merge -> fast-forward mirror).
- Direct pushes to `main` are blocked by `hooks/pre-push`.
- Install guards: `powershell -File flow.ps1 install-hooks` and
  `powershell -File safeguards/install.ps1`.
- Before PRing, merge `main` into your branch:
  `powershell -File flow.ps1 sync -Name <you>`.

## Architecture constants

- **Python realms are stdlib-only**. Add pinned third-party deps to the realm's `package.json` (Node) or root `requirements.txt` only with operator sign-off.
- **Ports** are declared once in `realms/registry.json`. Core floor: vulcan `:43901`, zeus `:43902`, ptah `:43903`, daedalus `:43905`, haven `:43910`.
- **Tier model**: T0 infra (doctor, sentinel, CI), T1 kernels (zeus, gaia, thoth), T2 realms (vulcan, hades), T3 satellites (assistant, eidovara lineage - gitignored, self-gated).
- **Five guarantees**: deterministic replay, every mutation attested, least privilege by default, no partial reads (atomic `os.replace`), health claims require gates.
- **Data dirs** (`data/`, `zeus/data/`, `ptah/data/`, etc.) are gitignored runtime state.
- **`site/`** is gitignored; CI regenerates it on deploy.
- **`assistant/`, `mind/`, `eidovara/`, `project-soul/`, `project---soul/`, `live-soul/`** are nested repos or sibling projects, gitignored here.
- **Version**: single source at `VERSION` (currently `1.16.0`).

## OpenCode session wiring

- Agents: athena, argus, daedalus, epeios, icarus, kerux, kourai, logia, metis, perdix, talos, trophonios.
- Commands: `athena-cycle`, `daedalus-muster`, `muster-fleet`, `argus-cycle`, `logia-cycle`, `metis-cycle`.
- Skills: `athena-codex` (knowledge codex), `fleet-learning` (proposal pipeline doctrine).
- Launch with `/<command>` or the matching agent name.

## Gotchas

- **Windows text mode breaks hashes**: always use `newline=''` or binary mode for durable writes (L006).
- **Sys.modules pollution**: purge between same-named imports from different path roots (L020).
- **Never weaken a gate to go green**: a failing gate is information, not an obstacle.
- **Lessons.json is append-only**: deprecate, never delete or renumber L### ids.
- **Parallel agents keep disjoint lanes**: re-read files before editing, merge duplicate definitions.
- **One localside repo home: `D:\`** - clone/init/worktree-add outside `D:\` is refused by `safeguards/repo_home_profile.ps1` and `safeguards/repo_home_guard.py`.
