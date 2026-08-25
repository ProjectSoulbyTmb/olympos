# ADR-0002: PROJECT VOLTAGE grows as a private sovereign operating system at D:\VOLTAGE

| | |
|---|---|
| **Status** | Accepted (operator sign-off 2026-08-25: plan reviewed in session, "go" ordered) |
| **Date** | 2026-08-25 |
| **Author** | HERMES (execution lane), design authored by ATHENA cycle 2026-08-25 |
| **Scope** | `D:\VOLTAGE` (new root, outside this repo), `realms/registry.json` (read-only reference), Olympos scope guards |
| **Supersedes** | The shelved "Open-Source Core (Darwin)" initiative (never landed; name retired) |

## Context

- DESIGN.md states the ecosystem converges on *"a fully autonomous,
  open-source game and app development platform"*. An open-source-core
  extraction was planned 2026-08-25 (working name "Darwin"), then
  redirected by the operator: the core becomes a **private operating
  system**, not a public framework. Publishing is shelved; Apache-2.0
  text is still seeded at bootstrap so a future publish needs no rework.
- `D:\` already hosts fleet neighbors: `olympos` (runner checkout),
  `THOTH`, `aphrodite`, `riley*`, `actions-runner`. Interference control
  is therefore a first-class requirement, not an afterthought.
- Registered ports in service today occupy 43901–43910 plus heart's
  4767 (`realms/registry.json`, disk-audited). The block **44100–44199**
  is clear for VOLTAGE-exclusive use.
- Bootstrap seeds only from a stable main: Olympos W0 precondition
  (rebase complete + one full green CI push-run) gates phase V2.

## Decision

1. **Root.** All VOLTAGE state lives under `D:\VOLTAGE` — outside
   OneDrive sync by construction. Fresh git history seeded there; zero
   Olympos commit lineage is carried over.
2. **Seed set (v0).** Byte-exact export from Olympos main:
   `ratatosk/ norn/ hades/ zeus/ gaia/ ptah/ atlas/ daedalus/ buskit/`
   plus infra (`doctor.py`, `sentinel.py`, `realms/`). Configs are
   re-pointed at the new root (ports 441xx, protected roots,
   `RATATOSK_ROOT`). After V5, divergence is intentional policy.
3. **Isolation contract (two-sided, gate-enforced).**
   - VOLTAGE-side path jail: every VOLTAGE organ refuses any path outside
     `D:\VOLTAGE`; sole exception is the push lane to its private GitHub
     mirror using existing credential store (tokens never tracked).
   - Olympos-side scope guard: `D:\VOLTAGE` is foreign territory;
     sentinel/scope checks fail loud if any Olympos lane touches it.
4. **Connectivity.** Loopback-only servers per house contract; the single
   external touchpoint is the one-way mirror push. Local-first holds:
   network off except the mirror must leave every function intact.
5. **Coexistence.** Side-by-side with the running Olympos fleet: disjoint
   port block (44100–44199), task names all prefixed `voltage-*`, own
   `data/` tree. No shared runtime state, ever.
6. **License.** hebe-canonical Apache-2.0 text + NOTICE seeded at V2.
   No publishing steps are scheduled; the seed merely preserves optionality.

## Constraints honored

- Guarantee #3 (least privilege): the path jail is a capability boundary,
  checked server-side where organs dispatch.
- Guarantee #5 (health claims): VOLTAGE claims health only when its own
  verify matrix + `doctor --ci` pass at the new root.
- FLOW discipline: bootstrap exports read-only against the source tree;
  Olympos lanes never write into `D:\VOLTAGE`.

## Consequences

- Two fleets share one physical disk; logical isolation only. CPU/disk
  contention during parallel sim runs is an accepted operational cost.
- Post-V5, fixes to shared organ code land twice (once per fleet) unless
  the promotion valve is exercised deliberately — documented trade, not drift.
- Rollback: halt all `voltage-*` tasks, archive/remove `D:\VOLTAGE`,
  drop the mirror repo. Olympos remains untouched throughout.

## Open items (block V2, not V0)

1. Mirror repo identity: proposed `ProjectSoulbyTmb/voltage` (private).
2. Root spelling: proposed `D:\VOLTAGE`.
3. Port block ratification: proposed 44100–44199.
