# ADR-0001: HEART grows as a sovereign companion on the layered-stack model

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-08-24 (rev 2 — reviewer findings folded, same day) |
| **Author** | ATHENA (design cycle, ad-hoc trigger) |
| **Scope** | `heart/` (nested repo, v0.2.0), `realms/registry.json`, `DESIGN.md`, future `heart/lib/*` |
| **Review** | @reviewer verdict 2026-08-24: **REQUEST-CHANGES** (10 findings) — all folded into this revision; see `docs/plans/cycles/2026-08-24-1042.md`. H0 remains blocked on the restored tree + operator yes. |

## Context (evidence, audited 2026-08-24; re-audited post-review)

> **Evidence-status note (rev 2):** the `heart/` source tree was present at
> the morning audit but is **absent from the workspace now** (empty
> directory, no `.git`; it lived only in an untracked nested repo — parent
> commit `2fec27e` added only `.gitignore` rows). Implementation-grounded
> citations below are preserved as recorded morning-audit evidence and must
> be re-verified when the tree is restored. H0 is gated on
> `Test-Path heart\package.json`.

- `heart/` joined as a **self-managed nested git repo** — parent commit
  `2fec27e` "chore: deskmate joins as a self-managed nested repo"; tree
  currently absent from disk (see note above).
- HEART v0.2.0 (`heart/CHANGELOG.md`) is an **offline desk-side companion**:
  focus/break timer as a pure timestamp state machine (`lib/timer.js`),
  healthy-habit nudge lanes (`lib/nudges.js`), crash-safe JSONL notes +
  word-overlap search (`lib/notes.js`, `lib/search.js`), stats/milestones
  (`lib/stats.js`), built-in coach voice (`lib/coach.js`), runtime settings
  (`lib/config.js`), procedural SVG avatar forge (`lib/avatar.js`,
  `lib/avatars.js`), optional local Ollama brain that **fails open everywhere**
  (`lib/brain.js`), file-only Venus bridge (`lib/bridge.js`), Electron shell as
  devDependency (`desktop/main.js`). Loopback-only HTTP on port **4767**
  (`heart/heart.js:33`); zero runtime dependencies beyond Node
  (`heart/package.json`).
- HEART is **invisible to the fleet's declaration surfaces**: absent from the
  DESIGN.md ecosystem table, from STRATEGY.md tier tables, and from
  `realms/registry.json` (re-audited post-review: **20 rows**, none heart;
  the morning audit's "9 realms" predates lanes #34/#37/#42 landing).
  Scope note: GAIA's `discoverSystems()` auto-includes any root-level
  directory containing `.git`, so a restored nested repo joins GAIA's
  composite regardless — "invisible" here means docs/registry/gates only.
  Consequences today: port 4767 has no sentinel-side at-rest check, and
  HEART's `npm test` surface is aggregated by nothing.
- Operator directive this cycle: *design HEART to its fullest capabilities,
  learning from mistral.ai*.

### Mistral patterns adopted (source: mistral.ai, retrieved 2026-08-24)

| Mistral pattern | Evidence on page | HEART translation |
|---|---|---|
| Layered product stack | Studio / Forge / Vibe / Compute product nav | HEART Core → Studio UI → Skills forge → Horizon planner |
| Long-horizon agent | Vibe: multi-step task scheduling, persistent memory, reusable skills, knowledge search | Plans bound to focus blocks; typed memory; skill packs |
| System of record | "Your Prompts and Skills need a system of record" (news) | Versioned, content-addressed skills ledger |
| Model tiering, graceful smalls | Mistral Small 4 / Medium 3.5 lineup | Brain ladder: built-in coach → local Ollama → nothing else |
| Evals, judges, guardrails | Studio feature bullets; Shieldstral news | Local judge gating every generated line |
| Sovereignty | "Self-hosted … Your data stays within your walls" | Already core doctrine in HEART; kept as hard rule |

## Options considered

| | A. Standalone forever | B. Promote to Tier-2 realm now | C. Layered sovereignty (chosen) |
|---|---|---|---|
| Effort | Low | High (envelope, rights, grants, pulse migration) | Medium, phased |
| Risk to five guarantees | None added; none gained | High if rushed (new wire member) | Low (additive, opt-in bridge) |
| Blast radius | None | Fleet-wide (registry consumers, sentinel gates, GAIA scoring) | Contained per phase |
| Reversibility | n/a | Poor (entangled) | Every phase independently rollback-able |
| Tier alignment | T3 undeclared (drift persists) | T2 forced fit — heart's cadence is product UX, not fleet supervision | T3 with declared identity; promotion path preserved |

Option B is rejected on tier-model grounds: INTEGRATION.md §3 rule "no organ
invents its own timer" binds *fleet* periodic work to norn.pulse; HEART's
focus/nudge cadences are user-facing product logic of the same class Venus's
canonical Node autonomic loop already serves (INTEGRATION.md §3). Forcing
pulse/envelope ceremony onto a desk companion couples user-facing uptime to
fleet internals for zero guarantee gain.

## Decision

Adopt **Option C — layered sovereignty**, eight commitments:

- **C1 Declared satellite identity.** One registry row: `{"name": "heart",
  "kind": "companion", "engine": "desk-companion", "port": 4767, "sdk": null,
  "path": "heart/", "tier": 3, "lang": "node", "verify": ["npm", "test"],
  "workdir": "heart", "profile": "watcher"}` — declaring identity and an
  informational optional gate per STRATEGY Phase 2 / M6 precedent.
  Port-protection evidence corrected in rev 2: `doctor.py` already derives
  `OWNED_PORTS` from the registry (`sorted({43901,43902,43903} |
  _registry_ports())`), so the row alone buys doctor-side squatter coverage;
  the remaining gaps are (a) `sentinel.py::doctor()`, which still pins a
  hardcoded `(43901, 43903)` probe list, and (b) listener *semantics* — both
  tools treat any busy owned port as squatter/warn (sentinel exits 2 on
  busy-at-rest), which for a long-running companion means permanent alarm
  noise. C1 therefore lands with H0's work items: sentinel probe-list
  derivation plus tier-aware classification (T1/T2 ports free at rest; T3
  companion ports busy ⇒ informational log, not warn/fail).
  Precondition: sentinel must treat `tier >= 3` verify failures as
  informational — excluded from summary and exit code, not merely tagged —
  before the row lands (verify first; see roadmap H0a).
- **C2 Additive wire alignment.** Every JSON response gains `"error": null`
  on success paths (house contract: every response carries `error`);
  `/api/state` reports `schema_version`. No breaking field removals.
  One deliberate behavior change is called out (rev 2): rejecting unknown
  setting/skill/plan fields with `400` replaces config's silent-ignore —
  ship-ordered so the bundled UI stops sending legacy keys *before* the
  server starts rejecting, keeping the change effectively additive
  (contract §1).
- **C3 Skills system-of-record.** `lib/skills.js`: append-only
  `data/skills/ledger.jsonl`, content-addressed ids (sha256-16 of canonical
  JSON), versioned manifests; coach/nudges/digest read through the skill layer;
  missing/corrupt entries fall back to built-ins (fail-open, matching the
  brain.js philosophy and bus quarantine patterns).
- **C4 Typed memory with hygiene.** Notes gain `kind`
  (`note|goal|fact`), hybrid search (word-overlap always; embeddings only when
  the local brain is up), corrupt-line quarantine on read (guarantee #4
  pattern: no partial reads), digest cites source note ids.
- **C5 Horizon plans.** Multi-step personal programs
  (`{goal, steps[], dueAt?}`) whose steps bind to focus sessions via
  `stepId` links in the session log; pure timestamp math like `timer.js`;
  JSONL journal so history replays deterministically.
- **C6 Judge-guarded brain ladder.** `lib/judge.js` applies facts-only /
  no-feelings-claims / length-cap / banned-pattern checks to every
  brain-generated line; failure falls back to the built-in coach voice. Brain
  routing is small-first and localhost-only — never cloud, mirroring Mistral's
  sovereignty posture inverted for a single machine.
- **C7 Opt-in observability.** When (and only when) `RATATOSK_ROOT` is
  configured, heart stamps `data/post/heart/heartbeat.json` and publishes one
  `vitals.heart` topic line per day-digest (catalogue row + kind constant
  required per INTEGRATION.md §6 before landing). Unconfigured = silently off
  (bridge.js precedent).
- **C8 Sovereignty is non-negotiable.** Zero runtime dependencies, loopback
  bind only, all state plain files under `HEART_DATA_DIR`, nothing leaves the
  machine. Any change violating C8 is a constraint change requiring a new ADR.

## Consequences

**Positive:** operator-facing wellbeing becomes a first-class, visible fleet
citizen without coupling it to fleet uptime; port 4767 gains squatter
protection; test surface stays warm (STRATEGY risk "satellite tests rot");
Mistral-grade capability ladder (skills → memory → horizon → judged brains)
lands in reversible phases; provenance-ready content-addressed skills leave a
door open for Hades sealing later.

**Negative:** two vocabularies coexist (REST responses vs letter envelope)
until/unless promotion — mitigated by the mapping table in
`docs/contracts/heart-interface-v1.md`; registry/sentinel consumers must be
tier-aware (one-time H0 work); nested-repo autonomy means parent-side docs can
drift again — mitigated by the DESIGN.md row plus changelog discipline.

## Rollback path

Every phase is additive and independently revertible: remove the registry row
(C1), ignore unknown response fields (C2), delete the ledger file — built-ins
resume (C3/C4), delete plan journal (C5), set `brain: off` (C6), unset
`RATATOSK_ROOT` (C7). No phase migrates or transforms existing data formats
destructively; v0.2 data files remain readable throughout.
