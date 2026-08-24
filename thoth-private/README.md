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

## Update procedure

1. Edit here or in `../thoth-private`, then mirror.
2. `npm run lint && npm test` (kernel attaches itself; suite must stay green).
3. Smoke via any fake engine or through the running app's console:
   `window.soul.thothCommand("thoth doctor")`.
