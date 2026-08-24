# HEART roadmap — fullest capability, phased

Companion to `docs/adr/0001-heart-layered-sovereignty.md` (decision) and
`docs/contracts/heart-interface-v1.md` (wire schemas). Baseline audited
2026-08-24: heart v0.2.0 at `heart/` (nested repo), port 4767, zero runtime
deps, tests via `node --test tests/*.test.js`.

Rules every phase honors (from DESIGN.md hard rules + INTEGRATION.md):
local-first; fail safe; verify before claiming health; additive wire changes
only; no organ invents fleet timers; nothing leaves the machine.

---

## H0 — Fleet visibility & gate safety (fleet-side, prerequisite-free)

**Goal:** HEART becomes a declared satellite without changing its behavior.

- Files: `realms/registry.json` (+1 row per ADR C1); DESIGN.md ecosystem
  table row + decision-log row; `sentinel.py` tier-awareness;
  **registry-derived port sweep** in `doctor.py` and `sentinel.py::doctor()`.
  Evidence: squatter checks are hardcoded today (`doctor.py`
  `OWNED_PORTS=[43901,43902,43903]`; sentinel pins `(43901,43903)`), so a
  registry row alone protects nothing — the sweep reads ports from the
  registry instead, which also discharges STRATEGY Phase 2's "squatter check
  covers every registered port".
- **Precondition (do first):** confirm sentinel treats `tier >= 3` rows as
  informational gates. Sentinel currently derives realm gates from the
  registry (codex §2, disk-verified). If tier routing is not implemented,
  land that first as `H0a` — otherwise a red heart test could turn fleet
  health red, which violates the T3 contract in STRATEGY §3.1. H0a also
  fixes severity encoding: today's incident envelope payload is free-form,
  so specify `payload.severity:"informational"` for T3 gate results.
- Verification:
  - `python doctor.py --ci` → green before and after (byte-identical realm results)
  - `(Get-Content realms\registry.json | ConvertFrom-Json).realms.Count` → 10, parses clean
  - `Push-Location heart; npm test; Pop-Location` → green
  - sentinel dry run with a forced heart-test failure → incident logged **informational**, fleet score untouched
- Acceptance: registry row present; doctor/sentinel derive checked ports
  from the registry (4767 protected while heart runs; future rows inherit
  protection automatically); DESIGN.md row cites version + port.
- Rollback: delete the registry row and doc rows; registry consumers keep fallback behavior (INTEGRATION §4.2).
- Risk: **Low-Med** (only phase touching shared gates).

## H1 — Wire alignment (heart-side, additive)

**Goal:** house response contract holds on every endpoint.

- Files: `heart/heart.js` (success paths return `"error": null`; `/api/state`
  adds `schema_version: 1`), `heart/tests/core.test.js` (envelope asserts).
- Verification: `npm test` in `heart/` green; manual `curl 127.0.0.1:4767/api/state` shows `error:null`.
- Acceptance: every JSON endpoint returns an `error` field; old clients unaffected (additive).
- Rollback: revert commit; no data migration involved.
- Risk: **Low**.

## H2 — Skills system-of-record (the Mistral lesson)

**Goal:** coach lines, nudge plans and digest phrasing become versioned,
content-addressed, user-editable skill packs with built-in fallbacks.

- Files: new `heart/lib/skills.js`; touch points `coach.js`, `nudges.js`,
  digest path in `heart.js`; `data/skills/ledger.jsonl` (append-only);
  `/api/skills` GET/POST endpoints per contract doc.
- Design rules: ids = sha256-16 of canonical JSON (provenance-ready for a
  later Hades seal); unknown manifest fields rejected like config.js rejects
  unknown settings; corrupt ledger line → quarantine file + built-in used;
  fail-open always.
- Verification: new `heart/tests/skills.test.js` (mint, activate, corrupt-line quarantine, fallback); full `npm test`.
- Acceptance: deleting `data/skills/` restores today's behavior exactly (built-ins resume).
- Rollback: remove skill-layer call sites (single indirection point).
- Risk: **Low-Med** (touches voice paths users feel).

## H3 — Typed memory & grounded digest

**Goal:** notes become a memory store; the digest proves its claims.

- Files: `notes.js` (entry `kind`, quarantine-on-read),
  `search.js` (hybrid overlap+embeddings scoring), `brain.js` reuse,
  `/api/digest` gains `sources[]` (note ids).
- Verification: extended core tests (corrupt line skipped + quarantined;
  digest cites only existing ids).
- Acceptance: with brain off, search quality ≥ v0.2 word-overlap baseline (same top-3 on fixture corpus).
- Rollback: kind field is additive; hybrid score degrades to overlap when embeddings unavailable.
- Risk: **Low**.

## H4 — Horizon plans (long-horizon work)

**Goal:** multi-step personal programs bound to focus blocks — the Vibe feature set, desk-sized.

- Files: new `lib/horizon.js` (pure timestamp math), `/api/plan*` endpoints,
  session-log `stepId` link, digest/badges report plan momentum, avatar mood
  mapping (deterministic function of streak/plan progress).
- Schemas: see contract doc §3. Journal: `data/horizon.jsonl`.
- Verification: new `horizon.test.js` (create → bind step → complete → digest reflects; restart mid-plan recomputes identically — restarts are free, same promise as timer).
- Acceptance: killing heart mid-plan loses nothing (state derives from timestamps+journal).
- Rollback: plans are an isolated module + file; ignore/delete to revert.
- Risk: **Medium** (new state machine — keep it pure, table-driven like timer.js).

## H5 — Judge-guarded brains + opt-in bus bridge

**Goal:** every generated line passes local guardrails; fleet observability arrives without coupling.

- Files: new `lib/judge.js` (facts-only, no-feelings-claims, length caps,
  banned patterns; config-extensible), brain router small-first, new
  `lib/buslink.js` (heartbeat stamps + one daily `vitals.heart` topic line;
  active only when `RATATOSK_ROOT` set).
- Precondition: three catalogue/enforcement edits before first publish —
  INTEGRATION.md §6 topic row (`vitals.heart`); kind constant in
  `ratatosk/bus.py`; AND a `buskit/envelope.py` TOPICS entry (verified:
  `envelope.py` does exact-match topic validation and rejects unknown
  topics; `bus.py` itself validates nothing). Sample letter ids must match
  `{seq}-{from}-{kind}-{12-hex}`.
- Verification: judge tests (bad line rejected → built-in voice returned);
  buslink test writes into a temp RATATOSK_ROOT; unconfigured boot produces zero bus files.
- Acceptance: `brain:on` + judge → no unguarded line can reach the UI; bridge off by default.
- Rollback: `brain:off`; unset env var.
- Risk: **Low-Med**.

---

## H6 — Voice & presence (Mistral: Voxtral lesson, zero-dep translation)

**Goal:** spoken coach lines, nudges and digest via the platform's built-in
SpeechSynthesis in the dashboard/overlay/Electron UI. Voice is presentation,
not backend — `lib/` stays pure Node.

- Files: new `public/voice.js` (client-side); `lib/voice-policy.js` (pure
  quiet-hours/gating logic, node-testable); `lib/config.js` (+ known keys:
  `voiceEnabled` dflt false, `voiceRate`, `voicePitch`, `voiceName`,
  `quietHours`); hooks in `index.html` / `overlay.html`.
- Prerequisite (reviewer-verified bug): `config.js saveSettings` coerces
  non-numbers via `String(v)`, so booleans silently revert to defaults on
  reload — reproducible today with any boolean setting. Make save/load
  type-aware against `DEFAULTS[k]` **before** adding `voiceEnabled`; add a
  bool round-trip test, or voice can never be switched on persistently.
- Transport: the quiet-hours/suppression decision is computed server-side by
  `voice-policy.js` and carried in `/api/state` as
  `voiceGate {speechAllowed, reason}` — the client never decides policy; it
  only speaks what state allows.
- Verification: `npm test` (quiet-hours table tests, config-key rejection);
  manual: start focus → exactly one spoken line; quiet hours suppress speech,
  chime unaffected.
- Acceptance: voice unavailable/off → silent, zero console errors, zero new
  dependencies; speech never fires more than once per event.
- Rollback: default-off setting; remove one script tag.
- Risk: **Low-Med** (OS voice inventories vary; degrade silently by design).

## H7 — Insight engine (Mistral: Studio observability, desk-sized)

**Goal:** descriptive local analytics over `log.jsonl`: best focus hour,
focus heatmap, per-lane nudge response rate, plan velocity; weekly review
digest composed from them. Pure functions, deterministic output.

- Files: new `lib/insights.js`; `/api/insights` endpoint; digest hook;
  fixture-log tests.
- Verification: `npm test` including a determinism assert (same log file →
  byte-equal insights JSON); empty-log case returns valid empty structure.
- Acceptance: no NaN/undefined paths; wording is strictly descriptive
  ("pattern"), never diagnostic or comparative.
- Rollback: endpoint removal is harmless (read-only view).
- Risk: **Low**.

## H8 — Widget presence system

**Goal:** overlay/dashboard composed of declarative widgets (mini-timer,
next-nudge countdown, streak, plan progress ring, mood avatar); layout
persisted; studio page arranges.

- Files: new `public/widgets.js`; `lib/config.js` (+ `layout` key);
  `/api/widgets` GET/PUT per contract §8; fixed widget-id allowlist;
  **retro hardening**: `public/studio.html` renders avatar names through
  `innerHTML` today — switch to DOM-API construction in this phase.
- Hard rule: **no user HTML ever** — ALL user-derived strings (plan
  goals/titles, avatar names, note text) reach the DOM exclusively via DOM
  APIs (`textContent`) or entity-escaped SVG `<text>`; unknown widget ids
  rejected server-side.
- Verification: `npm test` (layout schema validation, unknown-widget 400,
  corrupt-layout → defaults + `layout_reset:true`); injection-payload test
  (store avatar name / plan title containing HTML/script markers, render,
  assert zero element injection); manual arrange/persist.
- Acceptance: corrupt layout cannot break boot; no inline-HTML injection path.
- Rollback: reset `layout` key.
- Risk: **Medium** (only UI injection surface in the product — allowlist +
  text/SVG-only rendering are the mitigation; reviewer eyes requested).

## H9 — Deep-work coordination (fleet courtesy, advisory only)

**Goal:** an optional focus block publishes an advisory do-not-disturb flag
file that Venus/fleet agents may honor. File-only handshake (bridge.js
precedent), default off, advisory only — nobody is obligated to obey.

- Files: new `lib/dnd.js`; config key `dndDir` (unset = fully inert);
  temp-dir tests.
- Flag schema: `<dndDir>/heart-focus.flag` = `{v:1, untilTs, sessionId,
  reason:"focus-block"}`; written at block start, cleared at end, stale after
  `untilTs`. Writes are atomic (temp + rename); readers treat unparseable
  flags as expired; writers clamp `untilTs` to at most 24h ahead.
- Verification: `npm test` (write/expire/clear lifecycle); unconfigured boot
  produces zero writes anywhere.
- Acceptance: default installation touches nothing outside `HEART_DATA_DIR`.
- Rollback: unset `dndDir`.
- Risk: **Low**.

---

## Risk register (roadmap-scoped)

| Risk | Likelihood | Mitigation |
|---|---|---|
| Sentinel lacks tier-awareness → satellite test failure reddens fleet | Med | H0a precondition gate; informational-severity dry-run proof required before registry row lands |
| Skills layer changes coach voice users like | Med | built-in packs byte-equal to current coach lines; A/B only via explicit activation |
| Embedding path makes search worse offline | Low | overlap score always computed; embeddings strictly additive rerank |
| Horizon state machine drifts from timer's purity discipline | Med | table-driven transitions + identical-restart acceptance test mandated |
| Bus publish spam / catalogue violation | Low | one line/day cap; catalogue row precondition; review gate |
| OS voice availability/quality varies per machine | Med | silent degradation mandated in H6 acceptance; chime remains the floor |
| Insight output read as productivity judgment | Low | descriptive-language mandate; never comparative, never diagnostic |
| Widget layout becomes an injection vector | Med | fixed id allowlist, text/SVG-only rendering, schema-validated PUT (H8 hard rule) |
| DND flag ignored or over-obeyed by readers | Low | advisory-only contract with mandatory `untilTs` expiry (contract §9) |

## Promotion checklist (T3 → T2, only if ever justified)

Per STRATEGY §3.1, all boxes required:

1. Verify suite promoted from optional to blocking (`verify_heart.py` wrapper or npm gate in CI matrix)
2. Grant-class compliance: REST verbs mapped to L0/L1 (contract doc §5); destructive/admin surface = none today, keep it that way or add rights checks
3. Port registration already held (4767) + squatter coverage proven
4. DESIGN.md entry + INTEGRATION.md topology/port tables updated
5. Signed-off decision-log row in DESIGN.md referencing this checklist
6. Envelope/pulse decision recorded (buslink default flips only here)
