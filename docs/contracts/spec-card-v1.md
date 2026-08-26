# Spec-card contract v1 (families, slots, zero-LLM green)

Normative schema for **spec-cards**: the paper layer that lets the DAEDALUS
workshop weave ANY registered family green with **zero LLM calls**
(deterministic-first, operator-locked defaults 2026-08-26: strictly local,
no cloud fallback). Base truth is this document plus each family's card
file. The implementation module (`daedalus/blueprint_parametric.py`) is a
later phase **gated on this contract merging** — paper precedes metal
(L052). Local loopback only; no secrets; no network beyond 127.0.0.1.

Extends ADR-0002 §3.2 (E2 blueprint-authoring sessions) and ADR-0005's
law-is-one-table discipline to every family, and generalizes the
godot-game verification ladder (`templates/godot-game/README.md`,
`templates/verify_template.py`) from one target to all. Machine-readable
kin: `templates/design-card.json` (design-card-v0) describes WHAT to build;
a spec-card describes HOW the workshop proves it built it.

## 1. What a family is

A **family** is a weave-target class: a fixed file set, a self-test gate,
and named faults — exactly what a `BLUEPRINTS` row exposes in canon
(`daedalus/blueprints.py`). A **spec-card** is the machine-readable
declaration of one family: which slots exist, which are critical, what
fills them by default, and how a weave is proven. The workshop consumes
cards; a card is never trusted beyond what its own gate can prove.

Field mapping (card ↔ workshop canon):

| Spec-card | `BLUEPRINTS` row | Notes |
|---|---|---|
| `family` | dict key | registry identity, §8 |
| `slots[].default_body` | text inside `files` values | slot bodies render into files |
| `params` | `params` | deterministic fill values, sorted-key rendering |
| `gate.l0_gate_cmd` | `gate` | self-test; exit 0 = pass |
| `faults[]` | `faults` | name → (file, find, replace), §6 |

## 2. Card schema v1

One JSON object, UTF-8, stored per family (proposed home:
`daedalus/cards/<family>.card.json`; relocation is @daedalus's call — see
§11.4). Example — the existing `godot-game` family expressed as a card:

```json
{"$schema": "Olympos/spec-card-v1", "v": 1,
 "family": "godot-game",
 "description": "deterministic Godot orb-collector (python-twin proven)",
 "seed": "20260824",
 "slots": [
   {"name": "world_spec", "kind": "config_gen", "criticality": "critical",
    "default_body": "{\"gems\": [[1,2],[6,3],[3,6],[7,7],[2,5]], \"target\": 5}",
    "refine": null},
   {"name": "flavor_banner", "kind": "template_fill",
    "criticality": "non_critical",
    "default_body": "# Orb Collector — seed {seed}\n",
    "refine": {"prompt_hint": "one-line banner", "max_attempts": 3}}],
 "ladder": {
   "l0_gate_cmd": ["python", "verify_game_twin.py"],
   "l1_tool_env": "GODOT_BIN", "l1_cmd": ["{GODOT_BIN}", "--headless", "--import"],
   "l2_cmd": ["{GODOT_BIN}", "--headless", "--quit-after", "300"],
   "l3_golden": "journal.jsonl.sha256"},
 "faults": [{"name": "unwinnable", "file": "game_spec.json",
             "find": "\"target\": 5", "replace": "\"target\": 99"}],
 "constraints": {"stdlib_only": true, "network": "deny-by-default",
                 "secrets": "none-at-build-time"}}
```

Field law (reject wrong shapes with key+type precision; unknown keys warn;
missing keys with defaults take them — L010):

| Field | Type | Required | Notes |
|---|---|---|---|
| `$schema` | string | yes | exactly `Olympos/spec-card-v1` |
| `v` | number | yes | `1` |
| `family` | string | yes | `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`; unique in registry |
| `description` | string | yes | one line |
| `seed` | string | yes | determinism knob fed to slot identity (slotgen `SlotSpec.seed`) |
| `slots[]` | array | yes | ≥1 element; names unique |
| `slots[].name` | string | yes | `^[a-z][a-z0-9_]*$`; stable slot id |
| `slots[].kind` | enum | yes | `function_body \| template_fill \| config_gen` — exactly `buskit.slotgen.SLOT_KINDS` |
| `slots[].criticality` | enum | yes | `critical \| non_critical` |
| `slots[].default_body` | string | yes | **mandatory for EVERY slot**, §3 |
| `slots[].refine` | object\|null | see §3 | optional-brain hook; forbidden on critical slots |
| `slots[].cap_chars` | number | no | default `4000` = `slotgen.DEFAULT_SLOT_CAP` |
| `ladder` | object | yes | four rungs per §5 |
| `faults[]` | array | yes | ≥1 named fault per §6 |
| `constraints` | object | yes | stdlib_only / network / secrets, as shown |

## 3. Criticality law

**Critical** slots are correctness-bearing: rights or containment checks,
persistence boundaries, tick/simulation discipline, digest/seal math,
anything another module depends on structurally. **Non-critical** slots are
flavor, copy, tuning constants, presentation.

| Rule | critical | non_critical |
|---|---|---|
| deterministic `default_body` mandatory | yes | yes |
| brain refinement | **forbidden, no exceptions** | allowed under §4 chain only |
| `refine` present | refusal `critical_refinement` | optional (`null` = never refine) |
| may be load-bearing for the gate | yes | must not be (gate stays green with default body alone) |

**Zero-LLM-green law:** a weave of any registered family MUST reach a
green gate offline with zero model calls, using default bodies alone. A
card whose any slot lacks a deterministic default body is unlawful — the
weaver refuses it (`missing_default_body`), it does not improvise. The
scripted brain is the terminal brain of every chain (`buskit.slotgen`
doctrine: the chain must END in the scripted brain); LM Studio being
offline is the *supported default state*, never an error condition.

## 4. Determinism law

Same seed file ⇒ **byte-identical weave**: rendering a card twice with the
same seed and params produces identical bytes for every declared output
file (the NORN clockwork guarantee applied to weaving — seeded RNG and
logical time behind one duck-typed seam, `norn/clockwork.py`, L015).

1. **Scope of the guarantee:** byte-identity covers the declared weave
   outputs (the rendered file map). Derived products — engine import
   caches, media payload encodes, OS artifacts — are out of scope; L3
   digests cover declared outputs only (see §11.1–11.2).
2. **Chance seam:** every random/time read inside a slot body goes through
   the Clockwork seam or the seeded slot identity (`spec.key()`); wall-clock
   reads or unseeded randomness in a body are refused
   (`nondeterministic_slot`). Checksummed artifacts write binary or with
   `newline=''` via temp-file + `os.replace` (L006) — CRLF drift has
   permanently broken stored hashes before.
3. **Brain refinement chain** (non-critical slots only) matches the Phase 1
   `buskit.slotgen` seam leg-for-leg:
   journaled call (`buskit.llmlog`, digests never raw prompts) → retry
   with exponential backoff + seeded jitter → visible breaker with
   half-open revival (engineering rule 7) → deterministic fallback ending
   in the scripted brain → Hades seal of the journal via the scoped
   `SlotCaller.seal_journal` instance.
4. **Jail + bounds:** refinement executes only inside the ATLAS jail,
   through the bounded verify-fix-retry loop with culprit isolation
   (kernel pattern, proven 23/23); a refined body replaces the default
   only if the family gate goes green afterwards. Oversize replies are
   refused by name, never truncated (`slot_too_large`).
5. **Seal obligation:** a refinement whose journal leg was not Hades-sealed
   is void — the weaver refuses it (`unsealed_refinement`) and keeps the
   default body.

## 5. Verification ladder (every family declares L0–L3)

Reusing the template-ladder shape; every card carries all four rungs:

| Level | Check | Tooling needed | When tooling is absent |
|---|---|---|---|
| L0 structural | required files present, parse clean, slot bodies resolve, no unresolved `{placeholder}` | pure Python, none | **never skippable** |
| L1 unit/import | family unit gate (godot-game analog: `--headless --import` exits 0) | family tool env var | **named skip** |
| L2 integration/smoke | run N seconds / N operations without error | family tool env var | **named skip** |
| L3 packaged artifact/replay | packaged-artifact or seeded-run digest == golden digest (norn replay pattern) | packager / binary | **named skip** |

**Named-skip rule:** absent tooling — `GODOT_BIN` unset is the canonical
case — produces `skipped: <level>: <TOOL_ENV> unset` in the verdict and
the verdict counts skips explicitly. A skip is never a silent pass; a
verdict claiming green while a *runnable* rung was skipped is itself
invalid output (L030: failure output is part of the gate). L0 can never be
skipped: if pure Python cannot prove the weave's shape, the family is not
registered (L037 posture).

Example pair — tooling absent, honestly reported:

```json
{"error": null, "weave": "smoke-godot", "gate_l0": "pass",
 "ladder": {"L0": "pass", "L1": "skipped: GODOT_BIN unset",
            "L2": "skipped: GODOT_BIN unset",
            "L3": "skipped: golden manifest absent"},
 "skips": 3}
```

```json
{"error": "unnamed_skip: L1 reported green without GODOT_BIN",
 "weave": "smoke-godot", "gate_l0": "pass",
 "ladder": {"L0": "pass", "L1": "pass", "L2": "skipped: GODOT_BIN unset",
            "L3": "skipped: golden manifest absent"},
 "skips": 2}
```

(The refusal case above shows the shape only; a conforming weaver emits
`unnamed_skip` instead of reporting L1 green without tooling.)

## 6. Fault-injection muster obligations

Every family declares ≥1 named fault (workshop canon shape: `faults` =
name → file/find/replace). Obligations, per family:

1. **Independent breaker:** injecting the fault turns THAT family's gate
   red on a named assertion — not via collateral breakage. Innocent-looking
   faults that cannot fail are labeled cosmetic, never counted as breakers.
2. **Repair convergence:** the bounded verify-fix-retry loop recovers the
   gate to green after injection (proven property of the workshop loop).
3. **Named refusals in guards:** containment failures raise violations
   whose message names the reason (`traversal`, `absolute`, `drive`,
   `hidden`, `empty`); gates assert the NAME so defense-in-depth cannot
   mask a dead guard layer (voltage-command-spec §8 rule).
4. **Muster evidence** recorded ADR-0005-style: clean run `GATE GREEN`;
   per-fault run `BREAKER CONFIRMED`.

## 7. Refusal semantics

Every response carries `error` (string | null; house contract). Refusals
are lawful outputs, not crashes. A conforming weaver MUST emit these exact
classes:

| Error class | Trigger |
|---|---|
| `missing_default_body` | slot without a deterministic default body |
| `nondeterministic_slot` | body reads wall clock, unseeded RNG, network, or host-dependent state |
| `critical_refinement` | refinement attempted on a critical slot |
| `unsealed_refinement` | refined body whose journal leg is not Hades-sealed |
| `unknown_slot_kind` | kind outside `buskit.slotgen.SLOT_KINDS` |
| `slot_too_large` | reply exceeds `cap_chars` (refuse by name, never truncate) |
| `duplicate_family` | registration colliding with an existing family name (L036) |
| `null_verifier` | registration attempt whose verify suite is absent (L037) |
| `unnamed_skip` | verdict claimed green while a runnable ladder rung was skipped |

## 8. Extension protocol — registry rows, never membership lists

This workspace has been burned by hardcoded membership (STRATEGY.md gap #3;
the `4a17caf` retargeting churn). Law for adding family N+1:

1. **No hardcoded membership lists.** Loaders derive membership from the
   registry at runtime (L003 declarative registry). Canon
   `blueprints.py`'s try-import rows are grandfathered and remain
   @daedalus's; new families NEVER add loader lines — they add cards.
2. **Three-part registration, one PR** (L042 — document or retire within
   the same change):
   a. **registry row** — `daedalus/cards/<family>.card.json` lands (plus
      the `BLUEPRINTS` row @daedalus weaves from it);
   b. **verify suite** — the family's L0 gate wired into the doctor/gate
      set; admission with a null verifier is refused (`null_verifier`);
   c. **doc-table entry** — DESIGN.md ecosystem row, plus INTEGRATION §6
      catalogue row iff the family speaks bus topics.
3. **Broken cards quarantine:** an unparseable/unlawful card is skipped,
   never fatal, and published back with non-empty `error` (ADR-0002 §3.2
   reject path). Absence from disk means not-a-member — no ghost rows
   (L040).
4. **Retire completely:** removal takes all three parts in the same change
   (L021); grep the family name before declaring it gone.

## 9. Versioning & compatibility

- Card format version lives in `$schema` + `v`. v1 consumers reject wrong
  shapes with key+type precision, WARN on unknown keys, apply defaults
  where this table gives them (L010).
- **Within v1: additive-only.** New optional fields do not bump the
  version; old cards stay valid forever. Breaking changes require
  spec-card-v2 with its own contract doc; no silent edits — corrections
  land as dated revision notes (heart-interface-v1 rev discipline, L049).
- Rendered artifacts stamp `"schema_version": 1` in generated manifests so
  downstream consumers can branch on it explicitly.
- This contract binds implementations, not prose: where wording and a
  conforming verifier disagree, the verifier's named refusal wins and the
  doc gets a dated correction.

## 10. Acceptance matrix S1–S8

| # | Criterion | Proven by | Status |
|---|---|---|---|
| S1 | every registered family weaves green offline, scripted-brain only, zero LLM calls | family verify suite, endpoints dead | pending (implementation phase) |
| S2 | same seed ⇒ byte-identical weave | double-run digest equality per family | pending |
| S3 | refinement journaled + Hades-sealed; tamper breaks the seal | slotgen seam probes | pending |
| S4 | refinement on a critical slot refused BY CLASS | `critical_refinement` probe | pending |
| S5 | tooling-absent rungs produce named skips, never silent passes | GODOT_BIN-unset ladder probe | pending |
| S6 | every registered family passes muster: clean green + faults CONFIRMED as breakers | muster evidence log | pending |
| S7 | doctor --ci green at full membership post-registration | release gate | pending |
| S8 | registering family N+1 touches exactly the three §8 places, zero loader edits | next admission diff review | pending |

All rows are honestly **pending** until the `blueprint_parametric` phase
lands against THIS contract; nothing above is claimable from the paper PR
(L052).

## 11. Open issues (stated, not weakened)

1. **Byte-identity vs derived caches.** Resolved by scoping §4 to declared
   outputs. A family that cannot bound its outputs to a declared file set
   CANNOT conform and must say so in its card — that is a conformance
   fact, not a relaxation of the law.
2. **Hardware-flavored families** (riley-tune image/nvenc lineage): encoded
   payload bytes vary by hardware; conformance there means digests over
   configs + manifests only. Owner decision needed (@daedalus): register
   with narrowed L3 scope, or carry an explicit exemption row.
3. **CI treatment of named skips** for tooling-gated rungs (godot-game
   L1/L2 with `GODOT_BIN` unset): skip semantics are normative here;
   whether CI blocks on them per-family is the gate owner's dial
   (@daedalus).
4. **Card home path** `daedalus/cards/` is proposed, not canon — @daedalus
   relocates at implementation time if the workshop layout prefers
   otherwise.
5. **Determinism + zero-LLM-green tension check:** for every PLANNED family
   both laws hold simultaneously because both collapse to "the scripted
   terminal brain renders from seed." No known family violates this. If a
   future family genuinely cannot meet a quality bar with scripted
   default bodies, that family is an E2 candidate for HUMAN-authored
   defaults — never a loosening of §3.
