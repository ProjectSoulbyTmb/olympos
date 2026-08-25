# Olympos - Working Model & Integration Design

Model of record for how every organ runs, talks, verifies, and ships.
Builds on `DESIGN.md` (what exists) and `STRATEGY.md` (where we're
going). Supersedes the proposed `fleet.json`; realm endpoints belong in
`realms/registry.json` (currently pending restoration on this lineage -
see section 9).

## 0. The goal this design serves

> You describe a game or an app; Olympos designs it, writes the
> code, verifies it, and iterates autonomously - entirely on your
> machine, fully open source. The Vulcan sandbox is the proving ground
> where build-and-verify loops harden before they target arbitrary
> projects.

Everything else is machinery: kernels are the immune system, ratatosk is
the nervous system, norn is memory and accountability, hades is the
notary.

## 1. Three planes, five guarantees

| Plane | Organs | Carries |
|---|---|---|
| **Control** | THOTH (grants/routing), norn.rights, Venus/Heimdall hub | intents, escalations, config |
| **Data** | ratatosk bus + realm JSON-lines servers (:43590/:43591/:43901) | letters, broadcasts, SDK calls |
| **Verification** | norn (clockwork/replay/witness/pulse), schema gates, verify suites, doctor, sentinel, GAIA, Hades | digests, attestations, incidents, scores |

Non-negotiable guarantees (each has an owner and a test):

1. **Deterministic replay** - same seed file => byte-identical session
   (`norn.replay`, tested by `verify_system.py`)
2. **Every mutation attested** - witness journal line + seed re-runs it
   (`norn.witness`, read back by Hades)
3. **Least privilege by default** - sessions hold capabilities, not
   tools (`norn.rights`; escalation requires `grant` right)
4. **No partial reads** - bus delivery is `os.replace`; corrupt letters
   quarantine, never block (`ratatosk.bus`)
5. **Health claims require gates** - nothing says "healthy" without its
   verify suite passing (doctor/sentinel/GAIA)

## 2. Runtime topology

```
                        ┌────────────────────────────┐
   operator/Venus ──────►  THOTH operator kernel     │
                        │  grants · knowledge · scribe│
                        └─────────┬──────────────────┘
                                  │ intents / escalations
   ═══════════════════ RATATOSK BUS (data/post/) ═══════════════════
     mailboxes        topics/*.jsonl         heartbeats
    │        │        │            │             │
 ┌──┴──┐ ┌──┴───┐ ┌──┴────┐  ┌────┴────┐  ┌─────┴─────┐
 │ZEUS │ │Vulcan│ │builder│  │  norn   │  │sentinel/  │
 │kernel│ │warden│ │(agent)│  │pulse/wit│  │doctor/GAIA│
 └──┬──┘ └──┬───┘ └──┬────┘  └────┬────┘  └─────┬─────┘
    │       │        │            │             │
    ▼       ▼        ▼            ▼             ▼
  patrols  :43901  SDK calls   journals      gates -> incidents.jsonl
           schema  into realms (JSONL)      -> GAIA vitals/scores
           gates
```

### Ports (single registry: `realms/registry.json`)

| Realm | Engine | Port | SDK | Path |
|---|---|---|---|---|
| vulcan | building-sandbox | 43901 | VulcanSDK | `vulcan/host.py` |

Retired registry entries (ports 43590/43591 and their engines) are
deleted during reconciliation (§9); the registry ships with vulcan
until new realms earn rows.

Extension fields added by this design: `"tier"`, `"verify"`,
"profile"`, `"topics"` (see §4).

### Filesystem layout (runtime state, gitignored)

```
data/
  post/                     RATATOSK_ROOT default
    registry.json           organ -> meta
    seq/<organ>.seq         per-sender FIFO counters
    locks/<res>.lock        O_EXCL spinlocks, stale takeover 10s
    <organ>/inbox/          unread letters <seq>-<from>-<kind>-<token>.json
    <organ>/seen/           read + corrupt-quarantine letters
    <organ>/heartbeat.json  liveness stamp
    topics/<topic>.jsonl    broadcast journals (line no = seq)
    cursors/<consumer>.<topic>
  sentinel/incidents.jsonl  incident ledger
  zeus/audit.jsonl          patrol audit trail
zeus/data/                  quarantine, baselines
norn/seeds/*.jsonl          named regression scenarios
hades/                      fingerprints, seals, watermark ledgers
```

## 3. Time model - one beat hierarchy

| Cadence | Owner | Tick | SLO |
|---|---|---|---|
| Realm sim tick | Olympos engine | 0.6 s logical | Clockwork-seeded, replayable |
| Patrol tick | ZEUS kernel | fast loop | audit-only, never destructive |
| Supervisor beat | norn.pulse | base beat N | organs run on `every_beats`; quarantine after `slo_max_late` consecutive misses; revive after cool-down |
| Watchdog cycle | sentinel | manual / `--watch N` / Scheduled Task | remediate -> all gates -> ledger |
| Vitals sweep | GAIA (Node) | poll | score 0-100 per member |
| Heartbeats | every organ | on activity | `<organ>/heartbeat.json` |

Rule: **no organ invents its own timer** - periodic work registers with
pulse; pulse owns late-detection, quarantine, revival. Venus's
heart.js contract is the same autonomic loop and stays canonical for
Node-side organs.

## 4. Message contracts

### 4.1 Letter envelope (ratatosk mailbox + topic line)

```json
{
  "v": 1,
  "id": "<seq>-<from>-<kind>-<token>",
  "ts": "2026-08-24T12:00:00",
  "from": "vulcan",
  "to": "sentinel",              // mailbox letter; topics omit
  "topic": null,                 // set for broadcast lines
  "kind": "incident",            // verb/noun, see catalogue §6
  "rights": "operator",          // asserted profile of actor
  "payload": { },
  "error": null                  // EVERY response carries error
}
```

Delivery rules already enforced by `bus.py`: atomic `os.replace`,
per-sender FIFO seq under exclusive lock, stale-lock takeover
(`LOCK_STALE_S=10`), corrupt letters moved to `seen/corrupt-*`,
strong-lock mode raises rather than corrupting topic seq density.

### 4.2 Registry schema v2 (extends `realms/registry.json`)

```json
{
  "name": "vulcan",
  "engine": "building-sandbox",
  "port": 43901,
  "sdk": "VulcanSDK",
  "path": "vulcan/host.py",
  "tier": 2,
  "lang": "python",
  "verify": ["python", "vulcan/verify_vulcan.py"],
  "profile": "operator",
  "publishes": ["incident", "vitals.vulcan"],
  "consumes": ["policy.update"]
}
```

`realms.all_realms()` keeps its fallback behavior (missing file/name =>
caller defaults) so v1 callers survive untouched.

### 4.3 Rights model - one map, two vocabularies

THOTH grant classes and norn profiles describe the same ladder. Canonical
binding (enforced server-side at dispatch, per `rights.py`):

| Capability | norn profile | THOTH grant class | May do |
|---|---|---|---|
| observe | watcher | L0 read-only | state/live/status |
| act | agent_rw | L1 standing | + action verbs inside realm |
| administer | admin | L2 elevated | + grant/escalation mgmt |
| build | agent -> agent_rw (escalation required) | L1->L2 | codegen loops (§7) |

Default is least privilege: agents start `agent` (introspection only);
every escalation writes a witness line AND a THOTH grant record.

### 4.4 Attestation chain (mutation provenance)

```
verb(args) -> rights check -> execute under Clockwork(seed)
  -> witness.append({tick, actor, args_digest, state_delta})
  -> replayable: seed + journal == state_digest
  -> hades seals journal (fingerprint + watermark)
```

Hades treats witness journals as first-class artifacts: sealed nightly
and pre-release; a broken seal fails the release gate.

## 5. Process lifecycle

### Boot (any host)

```
1. doctor.py --quick      entrypoints compile, ports free, baselines sane
2. realms.load()          registry v2; unknown names degrade to defaults
3. organs register        pulse.Organ(name, fn, every_beats, slo...)
4. heartbeats open        each organ stamps data/post/<name>/heartbeat.json
5. bus subscribe          cursors resume from last consumed seq
```

### Sentinel cycle

```
remediate safe things -> run every registered verify suite
  PASS -> GAIA vitals sample
  FAIL -> incident letter {kind:"gate.fail"} + safe auto-repair attempt
         repeat offender -> ZEUS circuit breaker / pulse quarantine
all results -> data/sentinel/incidents.jsonl (append-only)
```

### Shutdown

Organs flush cursors + heartbeats, close journals (witness rotates at
5 MB, keep 5); bus holds no sockets so shutdown is always clean.

## 6. Topic catalogue (initial)

| Topic | Publisher | Consumers | Kind |
|---|---|---|---|
| `incidents` | sentinel, pulse, ZEUS | GAIA, Venus hub | incident |
| `vitals.<organ>` | every organ | GAIA | vital sample |
| `grants` | THOTH | sentinel (audit), norn.rights cache | grant.grant/revoke/escalate |
| `build.request` | Venus/operator | builder agent | build.describe |
| `build.stage` | builder | hub, witness | build.design/code/verify/iterate |
| `artifacts.sealed` | Hades | hub, releaser | provenance.seal |
| `policy.update` | THOTH | all | policy.reload |
| `llm` | builder brain (ptah) | hub, witness | llm.call / llm.error |
| `updates` | relay | Venus hub, GAIA, operator | fleet.tick / fleet.build / fleet.repair / fleet.render |

Rule: new cross-organ communication goes through a catalogue entry in
this table + a kind constant in `bus.py`; ad-hoc inbox spam is rejected
in review.

## 7. The autonomous build loop (the product)

Each stage is an organ handoff over the bus, gated before the next:

```
[describe] Venus/CLI -> build.request {intent, constraints}
    |
[design]   builder drafts architecture -> build.stage{design}
    |        gate: human-readable, cites knowledge routing (THOTH)
[code]     generate code against realm SDK surfaces only
    |        gate: imports resolve, stdlib/pinned-deps rule honored
[verify]   schema gate (vulcan.schema pattern) -> verify suite authoring
    |        gate: new tests red->green; verify_system.py extended
[prove]    Clockwork(seeded) runs scenario; witness journals mutations;
    |        norn replay asserts digest; invariants become seeds/
    |        gate: replay green, zero unattested mutations
[seal]     Hades fingerprints source+tests+journal -> artifacts.sealed
    |
[ship]     tag-driven CI (existing) requires: doctor --ci green,
           all tier<=2 verify gates, Hades seal valid
    \--> failures at any stage emit build.stage{iterate} with the exact
         failing output; loop continues autonomously up to policy cap
         (THOTH-configured, L2-bounded)
```

The proving ground matters because every SDK verb the builder may call
already carries rights checks, schema gates, and verify coverage there -
hardening done once transfers to arbitrary game and app targets.

## 8. Failure modes & containment

| Failure | Detection | Containment | Recovery |
|---|---|---|---|
| Organ hangs/overruns | pulse SLO miss xN | auto-quarantine | revive_after cool-down beats |
| Corrupt letter | bus parse fail | seen/corrupt-* | queue keeps flowing |
| Lock contention storm | strong_lock exhaustion | raise loudly (caller decides) | stale takeover at 10 s |
| Gate flake | sentinel repeat-fail pattern | informational severity (T3) / breaker (T1-2) | ledger trend, not one-off |
| Rogue mutation (no witness line) | Hades audit vs journal diff | ZEUS quarantine of writer | replay from last good seed |
| Divergent histories (git) | ff-only pull refusal | STOP, report | explicit operator merge decision |

That last row is not hypothetical - see §9.

## 9. Reconciliation - COMPLETED (2026-08-24)

Resolved by lineage reset: `main` was rebuilt directly as the purged
Olympos tree (`8455df4` -> `e7e48ed`, now origin/main) with zero
retired-scope residue, verified by content scan. All game-derived
realms, scripts, seeds and registry rows are gone; ratatosk, norn,
vulcan, hades, gaia, zeus and thoth machinery carried over.

Still missing from the reset tree, to be restored incrementally:
`doctor.py`, `sentinel.py`, `realms/` registry, PTAH working tree
(currently orphaned-untracked), CI wiring for the new gates. This
document's contracts apply unchanged once those return; run
`verify_scope.py` before any restoration to keep the boundary clean.

## 10. Acceptance criteria (per integration point)

| # | Criterion | Verified by |
|---|---|---|
| A1 | Registry v2 parses; v1 callers unchanged | extend `realms` fallback test |
| A2 | Letter envelope round-trips incl. error field | `verify_ratatosk.py` addition |
| A3 | Rights ladder blocks escalation without grant right | norn rights unit + server dispatch test |
| A4 | Seeded session replays to identical digest | existing `norn.replay` + new builder scenario seed |
| A5 | Every mutating builder verb has a witness line | Hades audit diff == empty |
| A6 | Pulse quarantines a stalled stub within N beats | pulse unit test with fake clock |
| A7 | Release blocked when any tier<=2 gate red or seal broken | CI dry-run on scratch tag |
| A8 | Sentinel ledger schema matches §4.1 envelope | ledger linter in doctor |

## 11. Migration order (maps to STRATEGY.md phases)

| Step | Work | Unlocks |
|---|---|---|
| M0 | Execute §9 purge-and-integrate on one lineage | everything |
| M1 | Registry v2 fields + A1 test | Phase 1 manifest single-source |
| M2 | Envelope adoption in sentinel ledger + GAIA reader | observability spine |
| M3 | Rights binding table wired into THOTH grants | unified control plane |
| M4 | Builder skeleton: describe->design->code stages only | first end-to-end build.request |
| M5 | Prove+seal stages, seeds/ regression capture | autonomous iterate loop |
| M6 | Satellite optional gates (Venus, Eidovara) informational | full-fleet vitals without coupling |
