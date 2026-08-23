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

## Update procedure

1. Edit here or in `../thoth-private`, then mirror.
2. `npm run lint && npm test` (kernel attaches itself; suite must stay green).
3. Smoke via any fake engine or through the running app's console:
   `window.soul.thothCommand("thoth doctor")`.
