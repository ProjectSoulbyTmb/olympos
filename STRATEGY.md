# Olympos - Architecture Strategy

Working strategy for growing the ecosystem without losing the guarantees
that make it trustworthy. Companion to `DESIGN.md` (what the architecture
*is*); this document defines where it goes next and how we get there.

## 1. Current state (audited 2026-08-24)

### Tracked core (the actual Olympos repo)

| Layer | Members | Notes |
|---|---|---|
| Protection | ZEUS (`zeus/`) | tick patrols, quarantine, circuit breakers, port 43902 |
| Health | GAIA (`gaia/`, Node) | vitals -> score 0-100 -> alerts |
| Operator | THOTH (`thoth-private/`) | grants L0/L1/L2, scribe, stabilizer |
| Products | Vulcan (`vulcan/`), Hades (`hades/`) | automation sandbox :43901, provenance |
| Shared | `image-toolkit/` (Node) | |
| Infra | `doctor.py`, `sentinel.py`, `register-*.ps1`, `.github/workflows/`, `site/` (generated hub) | |

### Satellites (present on disk, deliberately gitignored)

- `assistant/` - Venus desktop assistant (Node, plugins, tray)
- `eidovara/`, `live-soul/`, `project-soul/`, `project---soul/` - four
  local copies of the Eidovara Windows product line
  (`project---soul` is the publish source per its README)

### Limbo

- `ptah/` - exists, empty, untracked, undocumented
- `site/` - untracked regeneration of the auto-generated hub (last hub
  commit: `d70c73f`)

## 2. Gaps the strategy must close

1. **Doc drift** - DESIGN.md's ecosystem table stops at the six core
   members; satellites and limbo dirs are invisible to the docs even
   though they share the workspace, disk, and operator attention.
2. **Gate coverage asymmetry** - doctor/sentinel run verify suites for
   ZEUS/Vulcan/Hades (+ GAIA npm tests). Satellites ship their own test
   surfaces (npm tests, Playwright configs) that nothing aggregates.
3. **Hardcoded membership** - each gate script carries its own list of
   what to check; adding/removing a realm means N edits (see today's
   `4a17caf` retargeting churn).
4. **Port + artifact registries live in prose** - port assignments sit
   in one sentence of DESIGN.md; installer SHA-256s are hand-copied into
   Eidovara READMEs instead of machine-verifiable records.
5. **Runtime-output hygiene** - generated artifacts (`site/`) have no
   declared policy (tracked vs ignored), so they oscillate between
   commits and `??` noise.

## 3. Target architecture

### 3.1 Tier model

```
Tier 0  Infra        doctor, sentinel, CI, scheduled tasks, site
Tier 1  Kernels      ZEUS (protect), GAIA (measure), THOTH (operate)
Tier 2  Realms       Vulcan, Hades          (product-facing, server-bearing)
Tier 3  Satellites   Venus/assistant, Eidovara lineage (gitignored, self-gated)
```

Rules by tier:
- T0-T2 are tracked, stdlib-only (Python) or dep-pinned (Node), and MUST
  pass their verify gate before any health claim.
- T3 never blocks core CI. A satellite may register an optional gate;
  failures land in the sentinel ledger as informational, never as
  red fleet health.
- Promotion T3 -> T2 requires: verify suite, grant-class compliance,
  port registration, DESIGN.md entry, and a signed-off decision-log row.

### 3.2 Single source of truth: fleet manifest

Add `fleet.json` at repo root. Every gate, vital collector, and doc
generator derives from it - membership is declared once:

```json
{
  "realms": [
    {"name": "zeus",   "path": "zeus",           "lang": "python",
     "verify": ["python", "zeus/verify_zeus.py"],
     "ports": [43902], "tier": 1},
    {"name": "vulcan", "path": "vulcan",         "lang": "python",
     "verify": ["python", "vulcan/verify_vulcan.py"],
     "ports": [43901], "tier": 2},
    {"name": "gaia",   "path": "gaia",           "lang": "node",
     "verify": ["npm", "test"], "workdir": "gaia", "tier": 1}
  ],
  "satellites": [
    {"name": "venus",    "path": "assistant", "optional_gate": true},
    {"name": "eidovara", "path": "project---soul", "optional_gate": true}
  ]
}
```

Acceptance: adding a realm = one manifest edit + one suite file; doctor,
sentinel, GAIA, and README tables all pick it up without code changes.

### 3.3 Contracts (already de facto, now written down)

1. Servers speak JSON-lines on registered loopback ports; every response
   object carries `error`; clients send intents, receive full state.
2. Port registry: allocations recorded in fleet.json AND DESIGN.md;
   collisions are a doctor failure (squatter check generalizes to all
   registered ports, not just 43901/43902).
3. Repairs stay byte-exact and rollback-able; destructive action always
   requires L2 elevation regardless of tier.
4. Generated outputs declare their policy in `.gitignore` comments:
   `# GENERATED: build via CI, never hand-edit`.

### 3.4 Observability spine

```
realm verify suites -> sentinel gates -> incidents.jsonl -> GAIA vitals/scores -> alerts
      ZEUS audit.jsonl --------------------------------------^
```

One incident schema everywhere: `{ts, realm, gate, severity, action,
outcome}`. GAIA consumes the ledger directly instead of re-probing, so
scoring reflects watchdog reality, not a second opinion.

## 4. Phased roadmap

### Phase 0 - Hygiene (this week, zero-risk)
- [ ] Resolve `ptah/`: claim it (add realm entry + purpose) or delete it.
- [ ] Decide `site/`: preferred = gitignore + CI regenerates on deploy
      (matches "auto-generated hub" commit intent).
- [ ] Append a DESIGN.md decision-log row recording satellite policy
      (gitignored, self-owned, non-blocking).

### Phase 1 - Manifest (next)
- [ ] Land `fleet.json`; refactor sentinel/doctor gate loops to read it.
- [ ] Behavior must be byte-for-byte identical on current realms -
      verified by running all suites pre/post refactor.
- [ ] GAIA reads manifest for its member list.

### Phase 2 - Coverage
- [ ] Optional gates for Venus (`node test-heart.js` surface) and
      Eidovara (`npm test`) wired as informational sentinel checks.
- [ ] Doctor squatter check covers every registered port.

### Phase 3 - Provenance loop (Hades earns its keep)
- [ ] Hades fingerprints every release artifact (installers, snapshots);
      measured SHA-256 written to a machine-readable manifest shipped
      with the tag, replacing hand-maintained README hash blocks.
- [ ] SBOM directory pattern from `project---soul` promoted to release
      checklist for any T2+ product.

### Phase 4 - Release engineering
- [ ] Tag-driven releases gain: artifact fingerprint step (Phase 3),
      doctor `--ci` green requirement, and changelog lint against
      version consistency (source/site/service versions must agree -
      the invariant Eidovara v2.1.0 documents manually).

## 5. Explicit non-goals

- **No game-simulation revival.** Removed today by decision log; the
  Godot research stands as background only. If a visual layer is ever
  justified, the sanctioned shape is a thin read-only viewer over an
  existing JSON-lines realm server (e.g., Vulcan zones) - never a new
  simulation core.
- No cloud dependency for T0-T2 core function (local-first holds).
- No third-party imports into Python realms; root requirements.txt
  stays empty unless a realm formally adopts a dependency through
  doctor's coverage check.

## 6. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Manifest refactor changes gate semantics silently | Med | pre/post suite diff required in Phase 1 acceptance |
| Satellite test surfaces rot unused | High | optional gates keep them warm at informational severity |
| Port collisions as satellites grow | Med | registry + generalized squatter check |
| Doc drift recurrence | High | DESIGN.md table becomes generated from fleet.json (Phase 1 stretch) |
| Hash hand-copying ships stale provenance | Med | Hades-managed artifact manifest (Phase 3) |
