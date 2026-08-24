# Engineering Rules

Rules that prevent repeat failures in this workspace. Each cites its
lesson id in `lessons.json`.

## Files & data

1. **Atomic or nothing.** Temp file + `os.replace` for every durable
   write (L006). Checksummed artifacts are written binary or with
   `newline=''` - Windows text mode silently converts LF to CRLF and
   permanently breaks stored hashes.
2. **Validate on load, tolerate the future.** Schema gates reject wrong
   shapes with key+type precision; unknown keys warn; missing keys take
   defaults; versions bump on format change (L010).
3. **Bound every appendable** at creation: `deque(maxlen=...)`,
   save-time slices, rotation by size/count (L019).

## Concurrency

4. **One writer for mutable state.** All cross-entity mutations
   serialize on a single lock; readers use immutable snapshots (L018).
5. **Windows locks retry EACCES.** `O_CREAT|O_EXCL` raises
   PermissionError during delete-pending windows; lock loops treat it
   as "retry", not fatal, and take over stale locks by mtime (L005).
6. **Purge sys.modules between same-named imports** from different
   path roots, or load via importlib spec under unique names (L020).

## Reliability

7. **Breakers around every remote/failing subsystem**, with visible
   state and automatic half-open revival (L007).
8. **SLOs + quarantine for periodic work**; vitals queryable; revival
   after cool-down (L008).
9. **Quarantine, never destroy.** Automated remediation moves evidence
   aside, records actions, escalates judgment (L009).

## Process

10. **Every behavior change ships a verifier check**, and verifiers
    only touch temp fixtures - never live data dirs (L014).
11. **Retire completely**: code, menu flows, docs, CI jobs, scheduled
    tasks, verify expectations - grep the name before declaring done
    (L021).
12. **No shipped external fetchers.** Define snapshot-directory
    contracts the operator populates; engines read read-only and
    degrade gracefully (L023).
13. **Parallel agents keep disjoint lanes**, re-read files immediately
    before editing, and merge duplicate definitions rather than
    deleting them (L025).
14. **Trademark hygiene while small**: public names avoid third-party
    marks; disclaimers live in the README; internal identifiers stay
    (L024).
15. **Shared checkout => private index.** Commit with an isolated
    GIT_INDEX_FILE staging only your declared paths; run gates on
    those paths before the commit lands (L028).
16. **Gate every commit mechanically**: syntax compile, duplicate
    top-level def scan, JSON validity - `safeguards/check.py` wired
    as a pre-commit hook exists because each of these failures
    already happened once.
17. **Gate suites run bounded and observable**: parallel execution
    with hard per-suite timeouts (one hung probe must not stall the
    gate), machine-readable reports on disk, and every result
    broadcast onto the bus so failures are seen, not felt.
18. **Security scanners denylist binaries, allowlist nothing**:
    scanning "text extensions" only is how a `.pem` private key
    slips past; scan everything except known-binary formats.

## Security

19. **Capability check per verb** from one declared table; profiles
    narrow; escalation is admin-only and logged (L013).
20. **Hash-chain all audit trails**; seal manifests with HMAC plus an
    independent anchor (L011).
