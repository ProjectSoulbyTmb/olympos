# VOLTAGE Command Spec v1 (APOLLO)

Contract of record for the command plane. The machine-readable source
is the woven `apollo_rights_map` module; this document describes it
and defers to it. UI surfaces MUST render from `/catalog`, never from
hand-copied tables.

## 1. Grammar (EBNF)

```
line        := "voltage" ( session_cmd | command )
session_cmd := "session" ( "start" [--profile NAME] | "seal" [SID] | "status" )
command     := DOMAIN VERB [TARGET] { "--" FLAG [VALUE] }
DOMAIN      := fleet | know | media | image | game | learn | entertain |
               video | build | ops | demo
NAME        := guest | editor | admin
```

Parsing rules: tokens split POSIX-style; unknown domain or verb is a
grammar refusal (envelope `error`, exit 1); flags without values are
boolean; `--json` selects raw envelope output.

## 2. Envelope (wire)

Every response - HTTP status 200 or 4xx - passes the single choke:

```json
{"v":1,"kind":"reply","ts":"...","payload":{...},"error":null}
```

`error` is present always; non-null means refused/failed. Refusals are
lawful outputs, not crashes.

## 3. Sessions

| State | Meaning |
|---|---|
| ACTIVE | capabilities held; commands transcribe here |
| SEALED | transcript frozen; sha256 recorded; verification available |

Crash recovery: an ACTIVE session found after restart is stale; the
same profile may adopt it, and adoption is itself transcribed.

## 4. Rights law (summary; `/catalog` is the source)

L0 observe < L1 act < L2 administer. Dispatch order: grammar -> ladder
-> executor -> seeded digest -> witness (mutating successes only, exactly
one line) -> envelope. Sample rows:

| Domain.Verb | Class |
|---|---|
| fleet status / know search / entertain play | L0 |
| video produce / image generate / learn propose | L1 |
| build ship / game weave / ops grant / learn promote | L2 |

## 5. Server surface (:44120 production; ephemeral in tests)

| Route | Body | Returns |
|---|---|---|
| GET /healthz | - | `{ok, version}` |
| GET /catalog | - | domains + full verb law |
| POST /run | `{line, session}` | reply envelope |
| POST /session/start | `{profile}` | `{session:{id,level,profile}}` |
| POST /session/seal | `{session}` | `{sealed, transcript_sha256}` |
| GET /session/status?session=S | - | state + seal verification |

Boot writes `port.txt` after binding (stale file removed first);
startup banner `apollo up on <port>` is the discovery signal.

## 6. Acceptance matrix B1-B10

| # | Criterion | Proven by |
|---|---|---|
| B1 | L0 cannot invoke mutating verbs | no_ladder breaker red; clean refusals green |
| B2 | every mutation witnessed, digest carried | unwitnessed breaker red; count==1 check |
| B3 | envelope `error` everywhere | error_stripped breaker red; call() asserts |
| B4 | network-off studio matrix | Batch V7 gate (pending) |
| B5 | 441xx boot sweep fails loud | commissioning gate (pending) |
| B6 | two-sided boundary guard | export/scope probes (pending) |
| B7 | same seed => identical artifact digests | Batch V7 double-run checks (pending) |
| B8 | session seal verifies; byte-flip breaks it | gate tamper probe (shipped, green) |
| B9 | promotions cite evidence + operator gate | Batch V8 refusal tests (pending) |
| B10 | doctor --ci green at full membership | release gate (pending) |

## 7. Fault catalogue (gate-bite proof harness)

| Fault | Breaker effect |
|---|---|
| silent_start | banner silenced -> gate readline watchdog times out red |
| error_stripped | choke disabled -> first response lacks `error` -> red |
| no_ladder | authorize bypassed -> L0 mutation succeeds -> B1 assert red |
| unwitnessed | witness append skipped -> attestation count check red |

Run: `python tools/muster_launch.py [--fault NAME]`.

## 8. Extension protocol (Batch V7) - drop-in adapters

Adapters are single files beside the woven apollo modules, named
`apollo_ext_<domain>.py`, exposing:

```python
DOMAIN = "<domain>"
def register(executors):
    executors[("video", "produce")] = handler   # (session, cmd, ctx)
```

Law on the extension path (proven, not aspirational):

1. Loader scans once at boot; a broken extension file is skipped,
   never fatal; its verbs stay organ-not-wired.
2. Extensions OVERRIDE builtin doubles - real organs replace doubles
   without touching apollo core (the dynamism contract).
3. The rights ladder runs BEFORE any handler; witness + digest +
   transcript apply to extension mutations identically; an L0 session
   invoking an L1 extension verb is refused exactly as for builtins.
4. Handler verdicts must be dicts with boolean `ok`; anything else is
   wrapped as `malformed extension verdict`.

### Registered adapters (authored + proven 2026-08-25)

| Blueprint | Woven module | Domain verbs | Distinct law |
|---|---|---|---|
| kinema-host | kinema_host | video produce | job-schema gates; B7 seed digests |
| riley-bridge | riley_bridge | image generate/models/gallery | relay-parity idempotency keys; gallery jail; poll lifecycle |
| media-lane | media_lane | media view/browse | jail with NAMED refusals; normalization table; deterministic manifests |
| ent-composer | entertainer_composer | entertain play/queue/reel | seeded playlists w/ shuffle-token-in-digest; guest clamp |
| game-domain | workshop_guard | game weave/selftest | recursion cap depth<=1; defensive verdict parsing |

Named-refusal rule: containment failures must raise violations whose
message names the reason (`traversal`, `absolute`, `drive`,
`hidden`, `empty`); gates assert the name so defense-in-depth cannot
mask a dead guard layer.

## 9. Mind tier adapters (Batch V8)

| Blueprint | Woven module | Domain verbs | Distinct law |
|---|---|---|---|
| know-gateway | know_gateway | know search/cards/advise | deterministic weighted rank (title x3, tags x2, body x1), id-ascending ties with semantic anchors; misses are None/honest errors |
| learn-gateway | learn_gateway | learn propose/status/report/promote | B9: proposals require evidence citations; promote = L2 session AND operator sign-off file, each precondition named on refusal; monotonic P-####/L### ids |
| muse-curriculum | muse_loader + muse_data | (knowledge organ drop-in) | convention validation (prefix M-, unique ids, tags lists); loader refuses unlawful corpora |
| voltage-tasks | register_voltage_learning_tasks.ps1 + linter | (installer) | task names ^voltage-[a-z0-9-]+$; root confinement via -VoltageRoot; forbidden references (OneDrive / frozen checkout / Olympos) are pre-install lint refusals |

Promotion valve wording is contract: *"promote requires L2 session
(human authority)"* and *"operator sign-off file missing: promotion
stays human-gated"* — both proven by the `auto_promote` breaker.

## 10. Hardening adapters (Batch V9) and the B-matrix, closed

| Blueprint | Woven module | Law |
|---|---|---|
| ops-domain | ops_domain | Single-use ConfirmToken per privileged action ("one acknowledgment, one action"); quarantine records containment, never deletion; every action hashed into an append-only ledger |
| session-seal | seal_chain | link_i = sha256(prev\|name\|payload_sha256); deletion/reordering fails AT THE GAP even with forged length+tip; first divergence named |
| sla-pulse | sla_pulse | Injected-clock beats only; healthy→late→quarantined at slo_max_late→revived exactly after cool-down; re-quarantine proven; GAIA-shaped vitals |
| voltage-packager | package_voltage | VERSION file == declared version or refusal naming both; deterministic canonical manifests with manifest_sha256; shipped task names must satisfy ^voltage-[a-z0-9-]+$ |

### B1–B10 coverage map (final)

| # | Criterion | Proven by | Status |
|---|---|---|---|
| B1 | L0 cannot mutate | apollo-os gate + no_ladder breaker | executable proof |
| B2 | mutations witnessed | apollo-os + extension path | executable proof |
| B3 | envelope error law | apollo-os + error_stripped breaker | executable proof |
| B4 | network-off studio matrix | commissioning suite run at root | commissioning-bound |
| B5 | 441xx boot sweep | doctor squatter sweep at root | commissioning-bound |
| B6 | boundary hygiene both sides | voltage-tasks lint (text) + export/scope probes (root) | text-proof done; root probe pending |
| B7 | seed ⇒ identical digests | kinema-host double-run + riley idempotency keys | executable proof |
| B8 | seals verify; tamper named | apollo-os transcript probe + session-seal linkage breakers | executable proof |
| B9 | evidence-gated, human-gated learning | learn-gateway + auto_promote breaker | executable proof |
| B10 | doctor --ci at full membership | release gate at root | commissioning-bound |

Authoring is complete; B4/B5/B6-root/B10 are commissioning-bound by
design and cannot be honestly claimed before ADR-0002 V2 opens.
