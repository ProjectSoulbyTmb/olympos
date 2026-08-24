# Soul Platform

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
| `ptah/` | Software-engineering agent kernel: event-sourced reasoning-action loop over audited tools (terminal, file editor, grep, task tracker, verify-gate runner, memory), risk-classified actions with human confirmation gating, keyword-triggered skills, provider-agnostic LLM brain (OpenAI-compatible/Anthropic) or offline scripted brain, REST control plane on `127.0.0.1:43903`. Verify: `python ptah/verify_ptah.py` - nightly self-check: `python -m ptah selfcheck` |
| `thoth-private/` | Operator kernel doctrines: federation, stabilization points, knowledge entries, repair contracts |
| `knowledge/` | Distilled lessons database + architecture playbook + engineering rules extracted from everything built here |

## Quick start

```powershell
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
  `register-ptah-task.ps1` - Windows Scheduled Task helpers that keep
  the kernels running around the clock.

## Doctrine

- **Verify suites are hard gates**: every behavioral change ships a
  check; suites run standalone and exit non-zero on any failure.
- **Bus failures never crash hosts**: wiring helpers swallow and
  degrade.
- **Quarantine, never destroy**; ledgers record every automated action.
- Design guidance lives in [`knowledge/architecture-playbook.md`](knowledge/architecture-playbook.md)
  and [`knowledge/engineering-rules.md`](knowledge/engineering-rules.md);
  the machine-readable corpus is [`knowledge/lessons.json`](knowledge/lessons.json).
