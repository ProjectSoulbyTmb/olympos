# Advanced Code Inventory - Olympos three-plane sweep (2026-08-26)

Compiled by Hermes primary from three surveyor lanes (kernel/verification,
nervous/data, build/automation). Every citation verified by direct file read
in this workspace. Purpose: teaching reference for fleet agents + candidate
list for future learning cycles. Read alongside INTEGRATION.md (contracts)
and DESIGN.md (structure); this document records *how* the code earns its
guarantees.

Status at compile time: 45 vaulted lessons (L001-L045), 12 proposals queued
(metis x5, argus x4, logia x3) awaiting Athena validation + operator
sign-off.

---

## 1. Kernel / verification plane

### ZEUS (`zeus/`) - patrol kernel
- Per-subsystem circuit breakers: trip at 3 consecutive fails, auto-revive
  after 6 ticks; trip/revive are audited events (`zeus/kernel.py:39-79`,
  tunables `zeus/content.py:102-103`).
- Hash-chained rotating audit trail: `prev`+`sha` canonical-JSON links,
  `hmac.compare_digest` verification walk reporting `(ok, count,
  first_bad_seq)`; rotation via `os.replace` with chain reset to genesis;
  cross-restart tail resume by seeking last non-empty line
  (`zeus/kernel.py:162-221`, verify `verify_zeus.py:480-499`).
- Boot-rotated capability token: fresh 256-bit `secrets.token_hex` per boot
  written `O_CREAT|O_TRUNC` mode 0o600; strangers degrade to read-only
  watchers (`zeus/kernel.py:197-207`, `zeus/sdk.py:185-208`,
  `zeus/server.py:250-261`).
- Ransomware-shaped churn oracle: per-hot-dir `(mtime_ns, size)` mutation
  signatures over a 3-tick sliding window plus a synthetic-staging
  classifier (share of newly-added files >= 0.6 flags staging shape)
  (`zeus/oracle.py:30-99`).
- Stdlib-only Windows process introspection: raw ctypes Psapi/Kernel32,
  growth-loop `EnumProcesses`, "alive but dark" ACCESS_DENIED semantics,
  CPU% from kernel+user deltas normalized by core count, TCP owner table
  via `GetExtendedTcpTable` with rc=122 buffer retry, kill exit code 137
  (`zeus/procsys.py` throughout).
- Enforcement rails (bolt): protected pids {0,4}, self-refusal,
  `%SystemRoot%`-derived path rails, quarantine-moves-never-deletes with
  restore + double-restore refusal (`zeus/bolt.py:27-106`).
- Runaway latch state machine: soft/hard sample counts, fires exactly
  once, re-arms on recovery; separate hysteresis latch for memory
  (`zeus/sentinel.py:130-174`).
- Hardened localhost server: deliberately NO `SO_REUSEADDR` on Windows
  (permits silent double-binds; collision must fail loud into a 10-port
  retry), rolling-window flood control, server-side rights checks where
  `assume` may only narrow (`zeus/server.py:99-117, 186-248`).
- Dual-face SDK with machine-checked surface lockstep:
  `ZeusSDK`/`ZeusClient` expose identical verbs; `wire_client()` asserts
  lockstep and the gate verifies it (`zeus/sdk.py:241-260`,
  `verify_zeus.py:357-362`).

### NORN (`norn/`) - determinism + attestation substrate
- Seeded Clockwork seam: one object bundles seeded RNG + logical tick
  mirror; wall epoch derived from ticks (0.6 s MMO convention); live and
  sim modes byte-identical (`norn/clockwork.py`).
- Seed-file replay asserting state-digest equality: JSONL meta/verb/
  invariant scenario format; final state hashed canonical-JSON SHA-256;
  divergence raises; invariants evaluated in a sandbox exposing only
  len/set/min/max/sum/sorted/all/any; errors are part of the record;
  endorsement test = different seed must diverge (`norn/replay.py`;
  `norn/verify_norn.py:225-232`).
- XNU-style cadence SLOs: organs on beat multiples, quarantine after
  sustained SLO breach, auto-revive after cooldown; injectable clock for
  fake-clock tests (`norn/pulse.py:43-87`).
- Capability ladder: sessions hold frozenset rights; `can_narrow` permits
  only subset-narrowing; escalation only through audited grant verb
  (`norn/rights.py:93-100`).
- Witness attestation journals: every mutating call journalled with tick,
  actor, args digest, ok/error, world deltas; failures journalled then
  re-raised ("attestation IS replay with provenance", `norn/witness.py:1-9,
  54-130`).

### HADES (`hades/`) - provenance sealing
- Triple-authenticated seal: per-file manifest + HMAC-SHA256 sig under a
  0o600 key + independent anchor file pinning the payload hash; load
  verifies all three, any failure logs `forge_attempt` and raises with
  tri-state diagnosis (`hades/kernel.py:267-347`).
- AST structural fingerprints surviving rebranding: strict hash (shape +
  literals) catches renamed copies; loose hash (shape only, identifier
  fields blanked) catches string-swapped disguises; per-def/class + whole
  module so single-function theft is caught; noise floors reject trivial
  matches (`hades/fingerprint.py`). Ghost hunt excludes legit-manifest
  hashes and grades evidence (`hades/kernel.py:401-460`).
- Invisible watermarks: zero-width character encoding of truncated-HMAC
  tags; constant-time authenticate; embed strips prior marks
  (`hades/watermark.py`).
- Operator override authority: secret lives OUTSIDE the repo
  (`%LOCALAPPDATA%\HADES`), repo keeps fingerprint only; privileged ops =
  signed single-use tokens gated fingerprint -> signature -> expiry ->
  nonce replay ledger; every attempt audited; reserved DENIED exit code 3
  (`hades/authority.py`, `hades/cli.py:47`).
- Password gate: PBKDF2-HMAC-SHA256 @200k iters; exponential backoff spent
  BEFORE hashing work (delay doubles after 3 free failures, cap 900 s);
  fail-closed on corrupt credential state (`hades/auth.py:36-38, 172-184,
  75-89`).

### Gates + health plane (repo root)
- sentinel.py: absolute-path interpreter discipline (`PY = sys.executable`),
  registry-derived gate membership, tier-routed severity (T3 informational),
  remediated retry reusing exact command spec, spawner failures become data
  rows not crashes, versioned ledger tolerant of legacy v1 rows
  (`sentinel.py:30, 129-203, 245-324`).
- doctor.py: convention-over-registration discovery of
  `knowledge/verify_*.py`, registry-union port floor, settle-and-retry-once
  for timing-sensitive suites, fix-proof pairing (purge followed by
  recompile re-check), exit 0 only when nothing remains broken
  (`doctor.py:64-105, 151-190, 284-297`).
- watchdog.ps1: two-level liveness (task state + heartbeat age via bus),
  flap escalation publishing `watchdog-flap` after >=3 revives/hour
  (`watchdog.ps1:29-81`).

### Safeguards + boundary
- safeguards/check.py: incident-born commit gate; denylist-default text
  scanning ("allowlists are how key.pem slipped past"); AST duplicate-def
  shadowing detector; mixed-state warning (staged AND unstaged = lane
  corruption signal) (`check.py:55-204`).
- safeguards/gate.py: zero-upkeep suite discovery, thread pool with hard
  per-suite timeout, Windows `CREATE_NO_WINDOW`, failure-output retention
  (10-line tails / 8 KB artifacts), most-diagnostic-line selection
  (`gate.py:35-117`).
- safeguards/safe_commit.py: isolated-index commits via `GIT_INDEX_FILE`
  seeded from HEAD - commits exactly given paths without touching shared
  index (`safe_commit.py:80-91`).
- safeguards/tree_repair.py: stale-ref-lock repair with live-git-process
  veto + age grace; hot-dir protection reads sibling mtimes NOT dir mtime
  (deletion bumps dir mtime); squash-duplicate detection via `git cherry`
  (`tree_repair.py:147-282`).
- safeguards/repo_home_guard.py + profile shim: git destination prediction
  from raw argv, UNC denial, PowerShell `git` function shim emulating
  `$LASTEXITCODE = 128` on refusal (`repo_home_guard.py:76-167`,
  `repo_home_profile.ps1:92-114`).
- boundary.py: posture-derived polarity - ONE canonical file both fleets
  run; `$VOLTAGE_ROOT` arms the jail and disables side A; prefix hygiene
  defeats the sibling-prefix trap (`D:\VOLTAGEx` is not inside
  `D:\VOLTAGE`); env read fresh every call so tests arm/disarm without
  reloads (`boundary.py:1-48, 65-72`).
- Verify-suite authoring pattern (the house style): CHECKS registry +
  decorator runner OR named-tuple list OR immediate-exec ledger; throwaway
  fixtures per check; env-var seams for machine state; must-act AND
  must-refuse double-exercise; fault injection via designed seams
  (FakeTable, flaky patrol fns, fake clocks); security posture tests
  first-class (stranger-read-only, forged tokens, flood control);
  self-skipping hygiene (fixtures assembled so suites never trip their own
  scanners).

## 2. Nervous / data plane

### RATATOSK (`ratatosk/bus.py`) - filesystem post office
- Atomic delivery: temp file created in destination dir then `os.replace`
  - readers never see partial letters (`bus.py:168-181`).
- Per-sender FIFO seq counters under strong lock (mandatory, bounded
  backoff, raises rather than corrupting seq density; degraded unlocked
  bump safe because uuid tokens keep ids unique) (`bus.py:224-264,
  493-514`).
- Priority lanes by filename sort: `"!."` prefix delivers high-priority
  letters first lexicographically while preserving sender-seq order
  (`bus.py:16-19, 358-360`; proven `verify_ratatosk.py:394`).
- Corrupt-letter quarantine instead of queue-blockage (`bus.py:540-548`).
- Request/reply correlation via `corr` uuid + `"<kind>.reply"` polling
  (`bus.py:365-417`).
- Topic seq counters persistent and NEVER reset - survive size-based
  rotation into `.1/.2/.3`; legacy migration seeds counter from
  max(explicit record, total lines) covering pre-counter files
  (`bus.py:560-597, 622-642`).
- Cursor-based consume on explicit seqs, never line numbers
  (`bus.py:674-750`).
- Oversize guard (8 MiB) + `fit_payload()` truncation-to-reference-note;
  never-raise wiring helpers `safe_send/publish/beat/deadman` (deadman
  defaults True when heartbeat missing = fail-safe liveness)
  (`bus.py:94-97, 835-887`).
- Windows spinlock nuance: `PermissionError` treated as normal
  delete-pending contention, not fatal (`bus.py:199-203`).

### RELAY (`relay/`) - exactly-once crossing streams
- Exactly-once forwarding across restarts via persistent ratatosk cursors;
  "a killed daemon resumes with no duplicates and no gaps"
  (`relay/bridge.py:53-101`; proven `relay/verify_relay.py:187`).
- Intent lanes as single-writer directories with claim->execute->file-away
  semantics; urgent intents jump queue via sort key; TTL expiry; duplicate
  id dedupe against pruned seen-ledger where crash replays get explicit
  acks ("silence reads as loss") ; per-drain caps
  (`relay/bridge.py:135-205, 373-452`).
- Delivery spool `pending/ sent/ rejected/`: order parked durably before
  first dial; dark studio costs retries, never losses
  (`relay/riley_stream.py:175-249`).
- Idempotent-by-construction orders: seed derived from sha256(job_id) so
  duplicate POST renders identical asset (`riley_stream.py:59-77`).
- Tri-state verdicts: transient (5xx/408/429/dark) vs permanent refusals
  filed without retry storms (`riley_stream.py:91-120`).

### BUSKIT (`buskit/`) - message contracts as data
- Envelope law: error-always-present; XOR addressing (exactly one of
  to/topic); topic catalogue as importable dict; two-phase id
  (unsequenced make -> stamp_seq after bus allocates); lint CLI exit codes
  0/1/2 (`envelope.py`, `lint.py`).
- llmlog: witness-for-LLM - sha256[:16] digests + char counts + latency;
  "enough to prove identity, small enough to keep forever"; failure-is-
  evidence (`llmlog.py`).

### THOTH-private (operator kernel, JS)
- Three-class grant ladder at process boundary; L2 elevated NEVER
  grantable (per-call only); break-glass session-scoped admin; automatic
  safety backup before destructive tools, throttled 1-per-5-min, refusal
  if backup fails (`thoth-private/kernel.js:21-237`).
- Federation incident memory: stable fingerprint ids persisting across
  sweeps; clean sweeps bank MTTR samples; median/worst MTTR first-class
  (`federation.js:179-296`).
- Autonomic loop applies AT MOST ONE permitted action per tick; stable
  trees do not consume the budget (`autonomic.js:51-113`).
- Stabilizer foundations declare scan/apply/verify with byte-exact
  snapshot/restore; failed verification rolls back byte-for-byte
  (`stabilize.js`).
- Scribe: single shared inventory feeds audit AND rewrite so they cannot
  disagree; applyDocFixes refuses zero-or-multi-occurrence replacements
  (`scribe.js:230-381`).

### MIND (`mind/`) - production control organ
- Minimal RFC 6455 WebSocket codec stdlib-only with RFC accept-vector
  self-test (`wire.py`).
- requestId-correlated pending-future table; reader resolves replies by
  peek-not-pop so requesting thread owns removal; close() wakes all
  pending requesters (`client.py:117-227`).
- Bounded per-subscriber queues with shed-oldest backpressure - publisher
  never blocks on slow overlay (`bus.py:24-38`).
- Journal seq recovered as max(existing max, line count) on reopen -
  rotation/pre-counter files migrate without collision (cites L026)
  (`journal.py:30-51`).
- Rule-executor thread deliberately cannot share a stack with socket
  reader (executor waits on replies only reader can deliver)
  (`director.py:168-173`); reconnect backoff ladder (1,2,4,8,15,30)s.

### HAVEN / HARMONIA / HERMOD / INGEST
- Haven: external-content FTS5 kept in sync by triggers, bm25+snippet
  search, cumulative UPSERT keyed UNIQUE(domain,title) so rebuilds never
  drop knowledge, capability-token law where the token FILE is delivery
  truth with self-heal + rotate (`haven/build_haven_db.py`,
  `haven/server.py`).
- Harmonia: normalization planner copy|gdi|remux|transcode; stale-proof
  artifact naming embedding sha1(rel|mtime_ns|size|mode) so changed
  sources can never be masked by stale artifacts; async worker keeps HTTP
  handlers off ffmpeg (`harmonia/server.py`).
- Hermod: content-hash dedupe independent of delivery id; corrupt bundles
  park as corrupt-* + why-txt sidecar; restart-safe seen-set rebuild
  (`hermod/kernel.py`).
- Ingest: magic-byte sniff cached by (mtime,size); hashing-budget clone
  detection (size-group candidates, head+tail sample digest); polite
  crawler with jittered per-host throttle + exponential retry; resumable
  .part + fsync + os.replace downloads; catalog state machine merged
  across rediscoveries (`ingest/media_ingest.py`, `media_scanner.py`,
  `video_audit.py`, `web_search.py`).

## 3. Build / automation plane

### VULCAN (`vulcan/`) - building sandbox reference implementation
- Validate-at-the-door + lenient-audit-for-saves: recursive rule validator
  with bounded depth and human-readable refusals; unknown keys in saves
  warn-and-keep for forward compat (`schema.py:17, 105-182`).
- Grammar ownership: kind sets in one place; adding a kind touches exactly
  three places (`rules.py:23-31`, `schema.py:7-9`).
- Self-healing rule engine: invalid saved rules quarantined with reason
  instead of poisoning engine; circuit breaker trips after 3 fails,
  auto-revives after 60 ticks (`rules.py:202-342`).
- Warden patrol catalog: impossible-sensor clamping, stuck-sensor
  estimation, escalating load-shed widening by device class with alert
  damper (`warden.py:67-207`).

### DAEDALUS (`daedalus/`) - workshop factory
- Blueprint format FILES + FAULTS + gate: injecting a fault makes the gate
  fail ON PURPOSE until repair restores canonical text; deliberately-
  innocent faults prove culprit isolation doesn't blind-restore
  (`blueprints.py:467-541`).
- Fault-injection flight tests at scale: five faults each targeting a
  distinct security property (tamper matrix, nonce collision, Shamir
  threshold, journal chain) (`blueprint_ares.py:953-1237`).
- Culprit-isolation repair pass: restore one suspect at a time and
  re-gate (cap 3 regates); single restoration turning gate green
  identifies culprit WITH EVIDENCE (`kernel.py:185-229`).
- Lane pool: self-provisioning lanes adopting stale dirs; self-heal
  purges + reweaves corrupted worlds; consecutive-failure cooldown
  (3 fails => 45 s out); affinity dispatch warm-lane > streak > fewest
  fails; drain-then-retire resize respecting ATLAS guest ceiling
  (`fleet.py`).
- Cross-process hash-chained audit: msvcrt/fcntl `.lock` with tail reread
  INSIDE the OS lock so parallel writers cannot fork the chain
  (`kernel.py:431-525`; same contract `atlas/kernel.py:59-183`).
- Planning station: durable signed work orders draft->approved->
  commissioned->done|rejected|quarantined; operator sign-off requires
  {who, how}; commissioning converts steps to jobs idempotently; build
  completion callbacks close waiting plan steps carrying artifact_sha256
  (`planning.py`, `kernel.py:344-366`).
- Gate-bites proof doctrine: muster_launch injects a fault and REQUIRES
  red - verdicts GATE GREEN (clean) / BREAKER CONFIRMED / FAULT SURVIVED -
  GATE DID NOT BITE (`tools/muster_launch.py:60-74`).

### ATLAS (`atlas/`) - jailed execution
- Guest = jailed dir + at most one process; orphan adoption at boot.
- Exec hardening: argv-only (never shell), resolve_within escape refusal,
  denylist-scrubbed env (secret-shaped keys dropped; TEMP redirected into
  guest; comment explains why allowlisting breaks Winsock), hard timeout
  with taskkill tree-kill, ABSOLUTE ceiling min(timeout, MAX_GUEST_TIMEOUT_S)
  regardless of caller (`atlas/kernel.py:185-387`).

### PTAH (`ptah/`) - LLM builder brain
- One confirmed turn executes exactly ONE privileged action then the
  confirmation gate re-arms; DENIED patterns execute never even under
  confirmation (`agent.py:15-20`, `security.py:111-120`).
- Stuck detection: N identical action signatures stops the run
  (`agent.py:351-358`); protocol self-correction allows exactly one
  corrective nudge then hard failure (`agent.py:315-328`).
- Risk classes SAFE/ELEVATED/DESTRUCTIVE/DENIED mapped to L0/L1/L2/DENY
  over rendered tool+args regex tables (`security.py:21-100`).
- FallbackLLM chain: ONLY transient failures advance the chain; auth/bad-
  request burn no fallbacks; reply records which brain served
  (`fallback.py:34-66`).
- Context condenser: deterministic head+tail, first user message always
  preserved, raw event log stays pure (`condenser.py`).
- VerifyGateTool law: "Never claim success without a green gate"
  (`tools.py:312-347`); file_editor has NO delete op (fail-safe) and
  str_replace refuses ambiguous matches (`tools.py:16-213`).
- Workspace jail rejects absolute paths, drive letters, `..` climbs with
  case-insensitive containment check; MCP tools namespaced under
  `mcp__server__tool` so the SAME security analyzer classifies them
  (`workspace.py:37-54`, `mcp.py`).

### Root automation scripts
- flow.ps1 ship: one lane-safe step add->commit->push->PR->squash merge ->
  mirror fast-forward; post-merge proof loop NEVER undoes the merge
  (doctor --ci, one sentinel cycle if still red, residual red lands in
  incidents ledger but ship succeeds) (`flow.ps1:59-131`).
- land-all.ps1: dual-tree landing refusing to land on red; explicit path
  manifests so parallel-lane drift cannot ride under a commit message
  (`land-all.ps1:46-145`).
- Scheduled-task family: least-privilege tiering (workshop registers
  WITHOUT RunLevel Highest); PS 5.1 workaround P3650D duration because
  TimeSpan.Zero is rejected; MultipleInstances IgnoreNew; weekly learner
  stagger metis Mon / argus Thu / logia Sat 03:00 (`register-*.ps1`).
- learning package: append-only vault with monotonic L### allocator,
  proposals staged as separate files never touching lessons.json; Jaccard
  dedupe (best_match implemented but uncalled - see stubs); evidence
  readers degrade silently on quiet streams (`learning/vault.py`,
  `dedupe.py`, `evidence.py`).
- knowledge/engine.py: pure-stdlib TF-IDF inverted index; convention-based
  product-DB self-registration ("dropping the directory is the whole act
  of onboarding"); self-invalidating cache keyed on corpus fingerprint
  folded with _ENGINE_VERSION so old-code caches can never serve
  (`knowledge/engine.py:32-43, 181-246`).

## 4. Cross-cutting patterns worth teaching fleet-wide

1. Atomic-write discipline: tmp-in-destination-dir + os.replace is THE
   universal mutation primitive (aegis, hades, auth, authority, mirror,
   ratatosk, relay, hermod, thoth).
2. Hash-chained ledger schema, four instances of one idea: zeus audit,
   hades audit, daedalus/atlas chains, tree_repair ledger - each with its
   own tamper-detection gate.
3. Constant-time comparison everywhere secrets/digests are judged.
4. Error taxonomy with reserved exit codes (DENIED=3 distinct from
   error=2; sentinel 1=gate-failed vs 2=environment-broken).
5. Env-var test seams as architecture: RATATOSK_ROOT, VOLTAGE_ROOT,
   HADES_AUTHORITY_DIR, MIRROR_HOME, SENTINEL_DRILL_T3... production
   policy stays in content tables; env vars exist for tests/deploy only.
6. One-remediated-retry-before-red convention, triplicated with matching
   rationale comments (sentinel/doctor/gate).
7. Tier-routed severity: T3 satellites are normal life, informational not
   blocking.
8. Convention-over-registration discovery: gates, doctor suites, realms,
   knowledge DBs join "by existing," never by list edits.
9. Best-effort side channels that can never affect the primary duty
   (auditing never kills patrols; bus mirrors blanket-excepted).
10. Quarantine-with-revival as universal failure posture (vulcan rules,
    daedalus blueprints/plans, zeus breakers, bus corrupt letters).
11. Budgets-before-loops: every retry/pool/timeout is a named constant in
    one content table, never inline magic numbers.
12. Dual-face SDK + machine-checked surface lockstep.
13. Gate-bites proof: every gate paired with a negative test proving it
    fails when it should.
14. Least privilege as layered rails, not one gate (token AND profile AND
    bolt rails AND bounds-checked policy).

## 5. Verified stubs / drift / overclaims (candidate findings for NEXT cycle)

These were found by the surveyors WITH citations but budgets for this
cycle were already consumed by the subfleet. Recorded here as evidence
pointers; do not treat as proposals until staged through the pipeline.

| Item | Evidence |
|---|---|
| fleet.render-done emitted on updates but missing from buskit TOPICS["updates"] | relay/content.py:17, relay/riley_stream.py:140-146, INTEGRATION.md:231 vs buskit/envelope.py:54-55 |
| KIND_FLEET_PLAN missing from INTEGRATION sec6 catalogue | bus.py:137, daedalus/planning.py:167 |
| Ratatosk raw letters lack rights/error/topic fields that sec4.1 declares universal | ratatosk/bus.py:351-357 vs INTEGRATION.md:125-137 |
| grants topic catalogued but zero in-repo producers | grep across *.py |
| realms "schema v2"/realms.load() naming overclaims; loader exposes only all_realms/realm/port | realms/__init__.py:14-41 |
| NORN witness rotation does not rotate - _reopen appends same path, grows unbounded past rotate_bytes | norn/witness.py:8, 16-17, 83-88 |
| Pulse last_ms measured from shared beat-start t0 - later organs absorb earlier organs' runtime into their SLO | norn/pulse.py:54-72 |
| Zeus restart lane plumbed but unreachable - nothing sets restart_cmd | zeus/sentinel.py:115 |
| Zeus quarantine ledger memory-only; restore-after-restart impossible | zeus/bolt.py:76-77 |
| Zeus watch manifest minimal; multi-pid matches collapse to pids[0] | zeus/content.py:76-79, zeus/sentinel.py:76 |
| Doctor --fix-deps machinery fully built but REQUIREMENTS_IMPORTS empty | doctor.py:106, 192-213 |
| Sentinel has exactly one remediator despite plural claim | sentinel.py:129-144 |
| Watchdog interpreter hardcoded to LOCALAPPDATA Python312 | watchdog.ps1:18-19 |
| Hades status version import-order fallback "1.0.0" | hades/kernel.py:595-599 |
| Daedalus rules engine defined but never executed; kernel docstring implies otherwise | daedalus/rules.py:61-98 vs kernel.py:7, 87 |
| KNOWN_FAULTS registry empty/unused - fault names validated only as strings | daedalus/rules.py:16, 41-45 |
| Atlas authed capability set reserved/unimplemented; rate-limit knobs absent from content | atlas/server.py:57, 214-216 |
| learning.dedupe.best_match implemented, never called | learning/dedupe.py:29-45 |
| Hermod AUDIT_PATH declared never written; feeds topic uncatalogued | hermod/content.py:22-23 |
| Mind SSE docstring promises backlog flush not implemented | mind/server.py:183 |
| Harmonia stale "registry row pending" comment though row exists | harmonia/server.py:27-28 |
| Vulcan CLI rule_add uses restricted eval - outlier vs parse-don't-eval style | vulcan/cli.py:141 |
| Sindri FS scoping gap documented honestly | sindri/forge.py:18-20 |

## 6. Cycle bookkeeping

- Subfleet logs: docs/plans/learning/2026-08-26-0140-metis.md,
  2026-08-26-0150-argus.md, 2026-08-26-0155-logia.md
- Proposals queue after cycle: 12 (see python -m learning report)
- Vault: unchanged at 45 lessons - promotion awaits Athena validation +
  operator yes/no per fleet-learning doctrine
- No git operations performed (OneDrive checkout uncommitted except by
  operator order)
