# PROJECT VOLTAGE — Private Sovereign OS Roadmap (V0–V5)

Companion to `docs/adr/0002-project-voltage.md` (decision of record).
Execution doctrine: paper-first per FLOW protocol; each phase gates the
next; bootstrap (V2) additionally requires the Olympos W0 precondition
(rebase complete + one full green CI push-run on main).

## Phases

### V0 — Paper first (this PR)
- [x] ADR-0002 accepted by operator (session 2026-08-25).
- [x] This roadmap.
- Entry to V1 requires nothing further; V2 stays CI-gated.

### V1 — Two-sided guards
- [ ] Olympos-side: scope rule extended so sentinel/verify lanes treat
      `D:\VOLTAGE` as foreign territory; any touch fails loud.
- [ ] VOLTAGE-side: path-jail check wired into organ dispatch — refuse
      any path outside `D:\VOLTAGE` except the mirror push lane.
- Acceptance: attempted cross-boundary write fails on BOTH sides.

### V2 — Bootstrap (gated: W0 green)
- [x] Byte-exact copy from Olympos main: `ratatosk/ norn/ hades/ zeus/
      gaia/ ptah/ atlas/ daedalus/ buskit/` + `doctor.py sentinel.py realms/`.
      [DONE by parallel lane — D:\VOLTAGE seeded from main @ be5e170,
      commits a4990c9/46f0a04, 2026-08-25 morning]
- [x] Fresh `git init` at `D:\VOLTAGE`; seed commit only.
- [x] Repoint configs: ports → 44100–44199 block, protected roots,
      `RATATOSK_ROOT` → `D:\VOLTAGE\data\post`.
- [x] hebe-text Apache-2.0 + NOTICE seeded (publishing shelved).
- [x] HADES seals the seed baseline (`state/seal.json`). [A2 order GREEN]
- Acceptance: source tree digest unchanged post-export. [A3 GREEN]

### V3 — Standalone green
- [x] Every seeded organ's verify suite passes inside `D:\VOLTAGE`
      with zero C:-path or Olympos dependencies. [B2 matrix GREEN
      2026-08-25 evening: zeus 20/20, ptah 15/15, hades 13/13,
      ratatosk 28/28 (post git-trust fix), norn 4/6+2 sanctioned
      skips (vulcan unseeded), atlas 12/12, daedalus 15/15,
      buskit 12/12]
- [x] `doctor --ci` green at new root, incl. squatter sweep over
      441xx. [B3 GREEN]
- [x] GAIA scores all members; sentinel completes a full cycle.
      [B4/B5/B6 GREEN]
- Acceptance: full verify matrix green with network disabled.

### V4 — Autonomy
- [x] Arm `voltage-*` scheduled tasks: patrol (ZEUS), watch (sentinel),
      pulse (GAIA), push-lane (private mirror). [C1 GREEN 2026-08-25
      evening via coordinator --allow-c: voltage-sentinel/20m,
      voltage-gaia/15m, voltage-zeus/30min all Ready; push lane
      deliberately left manual pending explicit operator sign-off on
      auto-pushing sovereign commits]
- [x] norn.pulse SLOs + quarantine live for every periodic job.
      [pulse core proven in B2 matrix; sla-pulse blueprint adds the
      injected-clock acceptance law]
- Acceptance: kill-all + reboot re-arms everything (verify-autopilot
  equivalent passes at the new root).

### V5 — Sovereign operation
- [ ] All further work happens in D:\VOLTAGE's own lanes.
- [ ] Promotion valve from Olympos becomes deliberate and rare;
      divergence is documented policy.
- Acceptance: one full week of unattended side-by-side operation with
  zero cross-fleet incidents in either ledger.

### V6 — APOLLO command plane (ADR-0003; test-launch SHIPPED 2026-08-25)
- [x] Blueprint `apollo-os` (daedalus/blueprint_apollo.py): grammar,
      rights law, sessions, dispatch, witness, seals, gate.
- [x] Muster matrix green: clean pass + all four breakers confirmed
      (silent_start, error_stripped, no_ladder, unwitnessed).
- [x] Contract `docs/contracts/voltage-command-spec-v1.md`.
- [x] COMMISSIONED at D:\VOLTAGE 2026-08-25 evening: payload staged
      via organ/incoming, P1 install order digest-proofed, P2 weave +
      gate green AT ROOT + live :44120 bind probe; registry rows
      apollo/44120 + kinema-host/44130 + riley-engine/44128; bus
      command-plane constants landed; muse DB conforming to organ
      law (7/7 knowledge verify) and discoverable; sentinel 13/13.
- Remaining at root: studio engine backends behind their seams
  (kinema/riley/harmonia binaries+weights), doctor SUITES apollo
  entry if desired beyond sentinel derivation.
- Acceptance: B1/B2/B3/B8 green at the sovereign root.

### V7 — Studio tier (adapters replace builtin doubles)
- [x] BP `kinema-host` - video domain: job-schema gates, B7 digest
      determinism (synthetic backend; FFmpeg binds at commissioning).
- [x] BP `riley-bridge` - image domain: relay-parity idempotency
      keys, gallery jail, poll lifecycle, HTTP-refusal translation.
- [x] BP `media-lane` - containment jail with NAMED refusals,
      normalization semantics, deterministic manifests.
- [x] BP `ent-composer` - seeded deterministic playlists, guest clamp,
      shuffle-token-in-digest determinism witness.
- [x] BP `game-domain` - recursion cap (depth 1), defensive verdict
      parsing.
- [x] APOLLO drop-in protocol shipped: `apollo_ext_<domain>.py`
      adapters override builtin doubles; ladder/witness/seal apply
      unchanged on the extension path (proven in apollo-os gate).
- [ ] Commission at root: ports 44130/44128 registry rows, engine
      bases injected, real FFmpeg/RILEY/HARMONIA backends behind the
      proven seams.
- Acceptance at root: B4, B5, B7 green with network disabled.
- Muster evidence 2026-08-25: 6/6 clean greens; breakers confirmed -
  digest_skip, seed_drift, jail_hole, shuffle_drift, depth_uncapped.

### V8 — Mind tier
- [x] BP `know-gateway` - deterministic weighted search with anchored
      tie-breaks; honest misses; advise routing.
- [x] BP `learn-gateway` - evidence-required proposals (B9), promote
      valve = L2 session AND operator sign-off file, monotonic ids.
- [x] BP `muse-curriculum` - convention-validated knowledge product
      DB (organ auto-discovery shape); loader refuses corrupt corpus.
- [x] BP `voltage-tasks` - subfleet installer text with B6 hygiene
      lint: voltage-* names, root confinement, boundary-leak refusal,
      staggered weekly sweep.
- [ ] Arm under `voltage-*` scheduled tasks at commissioning;
      bind real knowledge organ / haven-v / vault behind proven seams.
- Acceptance: B9 green at root; subfleet sweeps only VOLTAGE ledgers.
- Muster evidence 2026-08-25: 4/4 clean greens; breakers confirmed -
  rank_drift, auto_promote, prefix_drift, olympus_leak.

### V9 — Enterprise hardening
- [x] BP `ops-domain` - privileged verbs under SINGLE-USE confirm
      tokens (re-arm law), quarantine-not-destroy, hashed ledger.
- [x] BP `session-seal` - linked seal chains over transcripts +
      artifacts; deletion/reordering breaks verification AT THE GAP;
      first divergence named.
- [x] BP `sla-pulse` - injected-clock SLOs: healthy -> late ->
      quarantined -> revived exactly at cool-down; GAIA-shaped
      vitals; re-quarantine after revival proven.
- [x] BP `voltage-packager` - version consistency by name,
      deterministic manifests, task-name law reaching the release.
- Muster evidence 2026-08-25: 4/4 clean greens; breakers confirmed -
  sticky_confirm, weaken_link, slo_blind, version_blind.

## Authoring complete (2026-08-25)

Fourteen blueprints stand registered and gate-proven across command,
studio, mind, and hardening tiers - the full B1-B10 acceptance matrix
is executable in blueprint form (`muster_launch.py` per blueprint).
What remains is COMMISSIONING ONLY, gated by ADR-0002 W0/V2: export
(`tools/voltage_export.py` dry-run ready), registry rows on 441xx,
engine bases behind proven seams, real backends swapped for doubles,
and the week-long soak of V5. No further Olympos-side authoring is
required to reach a commissioned VOLTAGE OS.

## Isolation contract summary

| Rule | Enforced by |
|---|---|
| Disjoint ports 44100–44199 | registry + boot-time squatter sweep |
| Task names `voltage-*` | installer scripts + task audit |
| Path jail (outbound) | VOLTAGE organ dispatch checks |
| Foreign territory (inbound) | Olympos sentinel/scope guards |
| Secrets never tracked | secrets gate pre-mirror-push |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Neighbor squats 441xx first | Med | fail-loud binding + boot sweep claims the block |
| Dual maintenance after divergence | High | deliberate promotion valve; document every divergence |
| Mirror credential exposure | Low | existing store only; secrets scan hard-gates push |
| CPU/disk contention, shared hardware | Med | accepted ops cost; schedule heavy sims apart |

## Open questions (operator)

1. Confirm mirror repo name (`ProjectSoulbyTmb/voltage`, private?).
2. Confirm root spelling `D:\VOLTAGE`.
3. Ratify port block 44100–44199.
