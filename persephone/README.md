# PERSEPHONE — guardian layer for offline products

Standalone stabilization + protection daemon for **APHRODITE**
(`D:\Aphrodite`, port 43904) and **RILEY** (`D:\riley`, port 43907).
Python stdlib only; zero pip dependencies; loopback-only; zero network
egress. Architecturally separate from both products: it observes them
over HTTP health endpoints and filesystem hashes, and owns no shared
state with them.

## Guarantees

| Guarantee  | Mechanism |
|------------|-----------|
| INTEGRITY  | SHA-256 manifest of protected files; tamper or deletion is auto-restored from the vault |
| LIVENESS   | Loopback health probe each sweep; dead product is relaunched with exponential backoff (max 10 min) |
| ATTESTATION| HMAC-SHA256 entitlement bound to this machine; an unattested product is monitored but never resurrected |

House rules inherited from the Olympos watchdogs:

* if a port is owned by a process that does not answer the product's
  health endpoint, PERSEPHONE stands down (never fights foreign services)
* all state lives under `%LOCALAPPDATA%\PERSEPHONE`
  (`vault\`, `attest\`, `persephone.log`, `history.jsonl`)

## Setup

```powershell
# one-time: baseline manifests + refresh last-known-good vault copies
python persephone\persephone.py --snapshot

# mint offline entitlements (renew anytime with the same command)
python persephone\persephone.py --attest aphrodite --days 365
python persephone\persephone.py --attest riley --days 365

# continuous guardian in its own console
persephone\launch_persephone.bat

# or as a scheduled task (sweep every 5 min + at logon)
powershell -ExecutionPolicy Bypass -File register-persephone-task.ps1
```

## Status

```powershell
python persephone\persephone.py --once      # single sweep, print table
curl http://127.0.0.1:43909/api/status      # live JSON while running
Get-Content $env:LOCALAPPDATA\PERSEPHONE\persephone.log -Tail 20
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
