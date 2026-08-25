# PERSEPHONE — guardian layer for offline products

Standalone stabilization + protection daemon for **APHRODITE**
(`D:\Aphrodite`, port 43904), **RILEY** (`D:\riley`, port 43907), and
the **whole `D:\` volume**. Python stdlib only; zero pip dependencies;
loopback-only; zero network egress. Architecturally separate from all
protected targets: it observes over HTTP health endpoints, filesystem
hashes, and lightweight inventories, and owns no shared state with them.

## Guards

| Guard      | Scope   | Mechanism |
|------------|---------|-----------|
| INTEGRITY  | product | SHA-256 manifest of protected files; tamper/deletion auto-restored from vault |
| LIVENESS   | product | loopback health probe each sweep; dead product relaunched with exponential backoff |
| CRASH-LOOP | product | circuit breaker: 4+ failed relaunches in 10 min -> stand down until healthy again |
| LOOPBACK   | product | listener on a product port must bind `127.0.0.1`; violations logged + recorded |
| DATA       | product | hourly snapshot of user-state dirs (ratings/tags/jobs); manual `--restore-data` only |
| DISK       | global  | free-space floor; vault writes pause below it |
| SELF       | self    | guardian hashes its own kernel + config; drift flagged mid-run |
| ATTESTATION| product | HMAC entitlement bound to machine; unattested products monitored but never resurrected |
| LOG        | self    | log rotates at 5 MB; history capped at 500 events |
| DRIVE      | D:\     | mounted check + free-space floor (5 GB default) |
| HEALTH     | disks   | SMART HealthStatus of physical disks via Get-PhysicalDisk, refreshed hourly |
| STRUCTURE  | D:\ roots | hourly inventory of key roots (`D:\new`, products); mass loss/growth (>10%) flagged without hashing media |
| RANSOM     | D:\     | suspicious extensions (.locked etc.) or mass-loss trip a full alarm: relaunches FROZEN until `--clear-alarm` |

House rules inherited from the Olympos watchdogs:

* if a port is owned by a process that does not answer the product's
  health endpoint, PERSEPHONE stands down (never fights foreign services)
* all state lives under the state root `PERSEPHONE_STATE`
  (default `D:\persephone\state`; override the env var to relocate):
  `vault\`, `attest\`, `persephone.log`, `history.jsonl`.
  NOTE: older docs said `%LOCALAPPDATA%\PERSEPHONE` — that path is
  stale; if it exists on your machine it is a dead relic.

## Setup

```powershell
# one-time: baseline manifests + refresh last-known-good vault copies
python persephone\persephone.py --snapshot

# mint offline entitlements (renew anytime with the same command)
python persephone\persephone.py --attest aphrodite --days 365
python persephone\persephone.py --attest riley --days 365

# after a LEGITIMATE upgrade/edit of a product (or to re-baseline all):
python persephone\persephone.py --promote aphrodite

# if ransom alarm tripped, after manual resolution:
python persephone\persephone.py --clear-alarm

# continuous guardian in its own console
persephone\launch_persephone.bat

# or as a scheduled task (sweep every 5 min + at logon)
powershell -ExecutionPolicy Bypass -File register-persephone-task.ps1
```

## Status

```powershell
python persephone\persephone.py --once      # single sweep, print table
curl http://127.0.0.1:43909/api/status      # live JSON while running
Get-Content D:\persephone\state\persephone.log -Tail 20
```

## Configuration

`products.json` registers products. Each entry:

```jsonc
{
  "name": "aphrodite",
  "port": 43904,
  "health_url": "http://127.0.0.1:43904/api/health",
  "launch": "D:\\Aphrodite\\launch_aphrodite.bat",
  "launch_flags": ["--quiet"],
  "files": [ { "path": "D:\\Aphrodite\\server.py" }, ... ]
}
```

Add any future product by appending an entry and re-running `--snapshot`.

## Verify gate

```powershell
python persephone\verify_persephone.py
```

Boots a sandboxed fixture product, asserts baseline manifest creation,
tamper-then-vault-restore repair, and attestation round-trip. Exits
non-zero on any failure.

## Relationship to APHRODITE / RILEY

PERSEPHONE is a separate process watching separate state. It modifies a
product only in two cases: restoring a protected file from its own vault
copy, or invoking the product's launcher when the health endpoint stays
down past backoff. It reads nothing else and shares no code, config, or
data directories with either product.
