# ARES - Code Seal Kernel (vault-cipher) + v2 Vault Suite

Dual-factor in-place encryption for private source trees. Stdlib-only.
v2 adds an encrypted metadata vault, defense profiles, auto-lock,
a chain-aware audit viewer, device pairing and signed sync bundles.
The v1 `.ares` blob format is unchanged and fully compatible.

## Quick start (v1)
    python -m ares init                  # machine lock + recovery codex
    python -m ares seal thoth-private/ -r
    python -m ares unseal thoth-private/ # restores originals
    python -m ares rotate vault.ares --level 3
    python -m ares status

Unlock phrase = your passphrase OR the 64-hex recovery codex (any 3 of
5 paper shares reconstruct it via `python -c` + ares.shamir).

## Quick start (v2)
    python -m ares vault add api-notes --tags work,crown --notes "..." [--path file]
    python -m ares vault list | search term --tag crown | show <id|name> | rm <ref>
    python -m ares profile set night --level 3 --target some/dir --max-age 30
    python -m ares lock --profile night        # seals all targets, one prompt
    python -m ares audit --tail 20 [--op seal] [--since 7d] [--export r.txt]
    python -m ares pair-begin / pair-adopt FILE / pair-list / pair-revoke FP|--all
    python -m ares sync-pack DIR --out bundle.zip / sync-import bundle.zip --into DIR
    python -m ares sweep [--profile night]     # dry-run exposure report

The vault has its own passphrase (prompted as "vault passphrase");
reusing your seal passphrase is fine. Vault records live in one sealed
container (`data/ares/vault.v2`) whose previous generation is kept as
`.bak`; wrong passphrase fails closed before any write.

## The automation law

Unsealing is NEVER automated. Schedules can only tighten secrecy -
and even automated SEALING is refused, because it would need your
passphrase stored somewhere. `register-autolock.ps1` therefore
installs an exposure SWEEP: every 15 minutes it dry-runs the profile
and journals what is still unsealed to `data/ares/exposure.jsonl`.
You get visibility; the secret stays in your head.

    powershell -ExecutionPolicy Bypass -File register-autolock.ps1 [-Profile night] [-Unregister]

## Threat model covered
1. Repo copy stolen -> .ares inert off-machine (DPAPI binding).
2. Machine stolen WITH login session -> passphrase + scrypt still gate.
3. Offline brute force -> memory-hard KDF economics (L2/L3 brutalize).
4. Tamper/truncate/swap -> tag fails closed, nothing written.
5. Journal tamper -> HMAC chain breaks loudly on status/audit.
6. Vault tamper -> container refuses; previous generation recovers.
7. Sync tamper -> sha256 manifest + HMAC signature both must hold.
8. Wrong-device sync import -> signature refused unless paired.

## Pairing (multi-machine)

`pair-begin` exports this machine's key sealed under a one-time
128-bit code (shown once). On machine B, after its own `init`,
`pair-adopt FILE` + the code adds that key to B's ring: from then on
either machine opens blobs the other sealed. `pair-revoke` removes an
adoption locally.

## Honest gaps
- No AES-GCM in stdlib: HMAC-SHA512-CTR stream cipher instead (sound,
  non-standard suite).
- Pairing file + code together ARE your machine identity: store the
  printout like the codex. A copy that already left cannot be
  recalled - only adoption on the target can be revoked.
- Sync bundles are signed, not encrypted (the blobs inside are
  already inert without a ring key); metadata filenames travel
  in cleartext inside the zip.
- exposure.jsonl and the journal record plaintext paths of sealed
  files - metadata leakage is accepted by design.
- Vault rewrites the whole container per mutation: right for personal
  scale (thousands of records), wrong for millions.
- Python GC prevents guaranteed key zeroization; best effort.
- SSD secure delete is physics-limited: single-pass overwrite + fsync.
- Lose BOTH the passphrase AND 3+ codex shares => unrecoverable. That
  is the point; store the paper accordingly.

## Defense levels
L1 scrypt N=2^15 (32 MiB/guess, daily fast) | L2 N=2^18 (256 MiB) |
L3 N=2^20 (1 GiB/guess; OpenSSL signed-long maxmem ceiling keeps all
levels runnable in-process). Default L1 per operator order.

## Verify gate
    python verify_ares.py    # 19 checks; exit 0 = green
