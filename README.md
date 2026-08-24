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
| `ratatosk/` | Filesystem communication network: organ mailboxes under `data/post/`, atomic letters with per-sender sequence numbers, broadcast topics with consumer cursors, heartbeats. No ports, no daemons. `python -m ratatosk status` / `demo` |
| `zeus/` | Protection kernel: process sentinel, filesystem-churn oracle, integrity baseline (aegis), quarantine + bolt enforcement, circuit breakers around its own subsystems, JSON-lines server |
| `hades/` | Provenance realm: SHA-256 seals with HMAC-signed manifests + independent anchor files, hash-chained audit trail, ghost detection via structural fingerprints, watermarks |
| `norn/` | Shared machinery wired through every realm: capability rights profiles enforced at Zeus/Vulcan dispatch, beat-paced organs with SLO quarantine (pulse) driving the Vulcan tick heart, ZEUS patrols and Hades scans, attestation journals (witness) recording every mutating verb, injected clock/RNG determinism seam (clockwork), engine-agnostic replay seeder (`norn/replay.py`). Gate: `python norn/verify_norn.py` |
| `vulcan/` | Smart-building automation sandbox: thermal simulation, rules engine with schema gates, warden self-healing, authoritative JSON-lines server - the proving ground for autonomous build-and-verify loops |
| `gaia/` | Ops kernel watching the whole organism: git sync state, CI verdicts, patrol loops (`node gaia.mjs`) |
| `hypnos/` | Silent task organ: task letters in `data/post/hypnos/inbox` (or `*.task.json` drop-ins) are claimed, executed headless (argv runs, file ops, cross-organ mail), retried with backoff, resumed after crashes, and fed back to the live system as reply letters, topic broadcasts and verify-gate build reports. Host: `python -m hypnos.daemon` - status: `python -m hypnos status` - verify: `python hypnos/verify_hypnos.py` |
| `thoth-private/` | Operator kernel doctrines: federation, stabilization points, knowledge entries, repair contracts |
| `realms/` | Declarative registry of component endpoints (ports/paths/kinds) |
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

# NORN integration gate (rights, witness, pulse, replay)
python norn/verify_norn.py

# silent task organ: verify, host it, watch it
python hypnos/verify_hypnos.py
python -m hypnos.daemon            # or: register-hypnos-task.ps1
python -m hypnos status

# ops kernel vitals
cd gaia && node gaia.mjs pulse --once
```

## Doctrine

- **Verify suites are hard gates**: every behavioral change ships a
  check; suites run standalone and exit non-zero on any failure.
- **Bus failures never crash hosts**: wiring helpers swallow and
  degrade.
- **Quarantine, never destroy**; ledgers record every automated action.
- Design guidance lives in [`knowledge/architecture-playbook.md`](knowledge/architecture-playbook.md)
  and [`knowledge/engineering-rules.md`](knowledge/engineering-rules.md);
  the machine-readable corpus is [`knowledge/lessons.json`](knowledge/lessons.json).
