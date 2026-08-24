# THOTH private kernel

Local-only operator kernel for Eidovara. Canonical source: `../thoth-private`.
This installed copy is **never tracked by git** (enforced by `scripts/guard-invariants.mjs`).

## Contract

- Entry: `src/features/thoth/index.js` exports `thothFeature` (+ `THOTH_VERSION`).
  `core/feature-registry.js` self-registers it when this folder exists.
- Descriptor: id `thoth`, intents `['thoth']`, dashboard module `thoth-console`,
  schemaDefaults `thoth: { masterEnabled, grants }`.
- API consumed elsewhere:
  - `attachToEngine(engine)` -> kernel with `state`, `listTools()`,
    `matchInvocation(text)`, `handleCommand(parsed, { adminAuthorized })`,
    `grant(tool, 'L0'|'L1'|null)`
  - `knowledge` -> `{ entries, rules }` merged via `core/knowledge.js`
- Electron IPC (already wired in `src/electron/main.js` + `preload.cjs`):
  `soul:thothStatus | soul:thothCommand | soul:thothGrant | soul:thothRevoke`

## Tool classes

| Class | Meaning                                                        |
| ----- | -------------------------------------------------------------- |
| L0    | read-only, runs while master is on                             |
| L1    | workspace-mutating; needs a standing grant                     |
| L2    | elevated/destructive; never grantable - admin session per call |

Grants persist inside the local profile only (`engine.state.thoth.grants`);
nothing leaves this PC.

## Learning loop (v2.8.0+)

- `learn.js` distills sweep signals into durable facts in
  `.operator/thoth_learnings.json`: fragile systems and MTTR from the incident
  ledger, chronic finding categories from the design watch, most-used tools.
- Observed facts carry evidence counts and expire after ~14 quiet days.
  Operator facts ("thoth teach <fact>") persist until "thoth unteach".
- Tools: `learn` (L0 review + reconcile), `teach`/`unteach` (L1).
- Usage counters live in `.operator/thoth_tooluse.json` (top 20).

## Operational wisdom (v2.9.0+)

- `wisdom.js` holds verified topology, environment facts, incident playbooks
  (signature-matched), and the escalation policy.
- `thoth topology` (L0) prints the workspace map + environment facts.
- `thoth advise` (L0) matches live incidents to playbooks; steps are marked
  `[auto-ok]` / `[L0]` / `[L1]` / `[human]`.
- `thoth advise --apply` runs exactly ONE step that the caller's existing
  standing grants already allow (L0, or granted L1). It never chains multiple
  mutations, never touches L2/elevated steps, and never executes `[human]`
  guidance. Automation depth equals standing grants - by design.

## Autonomic loop (v3.0.0+)

- `autonomic.js` is the single heartbeat: per tick it sweeps the fleet,
  reconciles incident memory, refreshes learning facts, matches playbooks,
  and applies at most ONE permitted action (existing grants only).
- `thoth auto on [minutes]|off|status|tick` (L1). Default cadence 15 min,
  bounded 5-240. Master pause blocks ticks exactly like manual commands.
- Every tick emits a relay `autonomic` event; state persists in
  `engine.state.thoth.auto`.

## Code repair (v3.1.0+)

- `repair.js` scans first-party code for unfinished markers and missing SPDX
  headers (`thoth repair`, L0) and prints a wiring checklist separating
  automation-fixable items from human decisions (`thoth wire`, L0).
- `thoth repair-fix` (L2, like comply-fix) applies ONLY deterministic repairs:
  Prettier with the repo `.prettierrc` + SPDX header insertion. Every rewrite
  is syntax-verified; failures are restored byte-for-byte and reported.
  Stubbed logic and startup-frozen wiring stay human-only by contract.

## Feature scaffolding (v3.2.0+)

- `thoth scaffold <id> [title]` (L0 dry-run) plans a full feature package:
  descriptor + knowledge + fail-closed contract test + guarded registry seam.
- `thoth scaffold ... --write` (L2) generates, wires feature-registry.js,
  syntax-checks every file, and executes the generated contract test before
  reporting success. Global knowledge merge stays a human one-liner.

## Auto Scribe (v3.3.0+)

- `scribe.js` is the automated documentation service covering every system
  the fleet sweep can see - apps, repositories, and the website docs folder.
- `thoth scribe` (L0) inventories all first-party Markdown and audits it
  against machine-checked facts: unknown `thoth <command>` references and
  broken relative doc links (with unique-target relink proposals).
- `thoth scribe-write` (L1) is the full document rewrite: regenerates
  `.operator/auto-scribe/<system>.md` digests plus a `_fleet.md` index from
  verified facts ONLY (identity, scripts, documents, network posture,
  topology roles, live command registry) and applies exactly one mechanical
  fix class - relinking a broken link when exactly one same-basename target
  exists. Prose is never improvised; historical version mentions stay put.
- Autonomic integration: idle ticks (no playbook action) spend their one
  permitted action on `scribe-write` while its standing grant is live.

## Stabilizer foundations (v3.4.0+)

- `stabilize.js` declares every recurring repair as a foundational point
  with a scan -> apply -> verify contract and byte-exact rollback:

  | point          | class | fixes                                | gate                        |
  | -------------- | ----- | ------------------------------------ | --------------------------- |
  | `doc-links`    | L1    | unique-target Markdown relinks       | re-audit finds zero fixable |
  | `digests`      | L1    | regenerate Auto Scribe fleet digests | written files parse + fresh |
  | `code-hygiene` | L2    | Prettier + SPDX headers              | per-file syntax verify      |

- `thoth stabilize` (L0) prints per-point status; `thoth stabilize-run`
  (L1) applies grantable points atomically - any failed verification rolls
  that point back byte-for-byte; `stabilize-full` (L2) adds code hygiene.
- Sessions append honest history to `.operator/stabilize/history.jsonl`
  and are idempotent: a second session over a stable tree does nothing.
- Autonomic idle ticks now spend their one permitted action on
  `stabilize-run` (supersedes the raw scribe-write rail), so continuous
  development self-heals declared drift without chaining unverified work.

## Update procedure

1. Edit here or in `../thoth-private`, then mirror.
2. `npm run lint && npm test` (kernel attaches itself; suite must stay green).
3. Smoke via any fake engine or through the running app's console:
   `window.soul.thothCommand("thoth doctor")`.
