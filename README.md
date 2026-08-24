# Project Olympos

A local-first workspace for building autonomous software systems:
protection kernels, provenance sealing, a filesystem message bus,
capability rights, deterministic replay, and self-healing automation
organs - grown and hardened by building and operating complete
simulations end-to-end.

Everything here runs on your machine. No external game services, no
shipped scrapers - data arrives as operator-supplied snapshot files.

## Organs

| Path | What it is |
|---|---|
| `ratatosk/` | Filesystem communication network: organ mailboxes under `data/post/`, atomic letters with per-sender sequence numbers, correlated request/reply, priority lanes, broadcast topics with consumer cursors that survive rotation (continuous seqs), mailbox metrics, heartbeats. No ports, no daemons. `python -m ratatosk status` / `vitals --strict` / `demo` |
| `zeus/` | Protection kernel: process sentinel, filesystem-churn oracle, integrity baseline (aegis), quarantine + bolt enforcement, circuit breakers around its own subsystems, JSON-lines server |
| `hades/` | Provenance realm: SHA-256 seals with HMAC-signed manifests + independent anchor files, hash-chained audit trail, ghost detection via structural fingerprints, watermarks |
| `norn/` | Shared machinery: capability rights profiles, beat-paced organs with SLO quarantine (pulse), attestation journals (witness), injected clock/RNG determinism seam (clockwork) |
| `vulcan/` | Smart-building automation sandbox: thermal simulation, rules engine with schema gates, warden self-healing, authoritative JSON-lines server - the proving ground for autonomous build-and-verify loops |
| `gaia/` | Ops kernel watching the whole organism: git sync state, CI verdicts, patrol loops (`node gaia.mjs`) |
| `poseidon/` | **Tide kernel**: fully autonomous commit-and-push workflow - sweeps uncommitted drift into snapshot commits via a throwaway index (root tree never touched mid-cycle), carries them through the FLOW.md lane (`auto/poseidon` -> push -> PR -> squash merge) under FORSETI's push-lane lock, then settles the mirror. Quarantine breaker after repeated failures; JSONL tide ledger. Verify: `python poseidon/verify_poseidon.py` - arm: `python -m poseidon watch --interval 300` |
| `ptah/` | Software-engineering agent kernel: event-sourced reasoning-action loop over audited tools (terminal, file editor, grep, task tracker, verify-gate runner, memory), risk-classified actions with human confirmation gating, keyword-triggered skills, provider-agnostic LLM brain (OpenAI-compatible/Anthropic) or offline scripted brain, REST control plane on `127.0.0.1:43903`. Verify: `python ptah/verify_ptah.py` - nightly self-check: `python -m ptah selfcheck` |
| `atlas/` | **Hypervisor**: hosts jailed guest workspaces for builder agents - per-guest directory confinement, argv-only execution with hard timeouts + tree-kill, capped output capture, scrubbed environments, hash-chained audit, NORN rights on the wire (watchers observe; operators rent compute) on `127.0.0.1:43904`. Verify: `python atlas/verify_atlas.py` |
| `daedalus/` | **Workshop**: autonomous server builder over its ATLAS subfleet - blueprint designs woven into guest worlds, self-test gates run inside the jail, fault-injected builds converge via fix passes (verify-fix-retry), VULCAN-style schema gates + policy rules + warden self-healing (stuck lanes, failure storms quarantined), sealed+hashed artifacts on `127.0.0.1:43905`. Verify: `python daedalus/verify_daedalus.py` |
| `relay/` | **Bridge**: stable daedalus<->venus relays over the ratatosk bus - workshop build outcomes forwarded exactly-once to the venus mailbox + `updates` topic (persistent cursors survive restarts and rotation), Venus intents (build / repair / status) claimed from `assistant/data/relay/to-fleet/`, repair sweeps run doctor's check+fix pass with published proof, constant fleet update stream + heartbeat (`python -m relay watch`). Verify: `python relay/verify_relay.py` - deploy: `register-relay-task.ps1` |
| `thoth-private/` | Operator kernel doctrines: federation, stabilization points, knowledge entries, repair contracts |
| `knowledge/` | Distilled lessons database + architecture playbook + engineering rules extracted from everything built here |

## Quick start

```powershell
# arm the full autopilot: ZEUS guardian + HYPNOS dreamworker + GAIA pulse
# (idempotent; ZEUS asks for one elevated run so it may bolt processes)
powershell -ExecutionPolicy Bypass -File register-olympos-tasks.ps1

# automation contract: is everything still wired to run itself?
python verify_autopilot.py

# protection kernel status
python zeus/cli.py

# provenance: seal the tree, verify, scan
python hades/cli.py seal
python hades/cli.py scan

# post office: who is on the tree, what mail waits
python -m ratatosk status
python -m ratatosk demo

# building sandbox verify gate
python vulcan/verify_vulcan.py

# agent kernel: offline demo, then a real brain once PTAH_API_KEY is set
python -m ptah run --demo
python -m ptah serve --port 43903

# ops kernel vitals
cd gaia && node gaia.mjs pulse --once

# tide kernel: plan a sweep, then let the workflow move itself
python -m poseidon once --dry-run
python -m poseidon watch --interval 300

# subfleet: berth + sync a private worktree for every kernel
python -m poseidon fleet start
python -m poseidon fleet status
```

## Infrastructure

- `doctor.py` - one-command stabilization: entrypoint compilation,
  component gates (ZEUS, Vulcan, Hades, PTAH, Ratatosk), protected
  directories, integrity-baseline age, owned-port squatters, stale
  bytecode purge.
- `sentinel.py` - continuous watchdog: runs every product gate, applies
  safe automatic remediations first, appends incidents to
  `data/sentinel/incidents.jsonl` (mirrored to Ratatosk). Use
  `--watch N` to keep watching.
- `register-zeus-task.ps1`, `register-thoth-task.ps1`,
  `register-ptah-task.ps1`, `register-poseidon-task.ps1` -
  Windows Scheduled Task helpers that keep the kernels running
  around the clock.

## Multi-agent flow

Autonomous writers never share a checkout: each works in its own git
worktree under `.worktrees/<name>` on an `auto/<name>` branch, and all
changes reach `main` through squash-merged pull requests. The root
checkout is an integration mirror - it pulls, it does not host commits.
Protocol and helper: [`FLOW.md`](FLOW.md) / `flow.ps1`.

## Doctrine

- **Verify suites are hard gates**: every behavioral change ships a
  check; suites run standalone and exit non-zero on any failure.
- **Bus failures never crash hosts**: wiring helpers swallow and
  degrade.
- **Quarantine, never destroy**; ledgers record every automated action.
- Design guidance lives in [`knowledge/architecture-playbook.md`](knowledge/architecture-playbook.md)
  and [`knowledge/engineering-rules.md`](knowledge/engineering-rules.md);
  the machine-readable corpus is [`knowledge/lessons.json`](knowledge/lessons.json).
