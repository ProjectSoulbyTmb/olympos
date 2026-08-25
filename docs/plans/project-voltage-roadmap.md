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
- [x] Olympos-side: scope rule extended so sentinel/verify lanes treat
      `D:\VOLTAGE` as foreign territory; any touch fails loud.
      (`boundary.py` side A + `verify_boundary.py` gate, registered in
      sentinel + CI; executables may not even name the root.)
- [x] VOLTAGE-side: path-jail check wired into organ dispatch — refuse
      any path outside `D:\VOLTAGE` except the mirror push lane.
      (`boundary.py` side B, armed by `VOLTAGE_ROOT`; ratatosk bus
      seams wired; push lane declares exemptions via
      `VOLTAGE_JAIL_EXEMPT`.)
- Acceptance: attempted cross-boundary write fails on BOTH sides.
      PROVEN by `verify_boundary.py` (both-direction refusal tests +
      live ratatosk seam tests).

### V2 — Bootstrap (gated: W0 green)
- [ ] Byte-exact copy from Olympos main: `ratatosk/ norn/ hades/ zeus/
      gaia/ ptah/ atlas/ daedalus/ buskit/` + `doctor.py sentinel.py realms/`.
- [ ] Fresh `git init` at `D:\VOLTAGE`; seed commit only.
- [ ] Repoint configs: ports → 44100–44199 block, protected roots,
      `RATATOSK_ROOT` → `D:\VOLTAGE\data\post`.
- [ ] hebe-text Apache-2.0 + NOTICE seeded (publishing shelved).
- [ ] HADES seals the seed baseline (`state/seal.json`).
- Acceptance: source tree digest unchanged post-export (read-only proof).

### V3 — Standalone green
- [ ] Every seeded organ's verify suite passes inside `D:\VOLTAGE` with
      zero C:-path or Olympos dependencies.
- [ ] `doctor --ci` green at new root, incl. squatter sweep over 441xx.
- [ ] GAIA scores all members; sentinel completes a full cycle.
- Acceptance: full verify matrix green with network disabled.

### V4 — Autonomy
- [ ] Arm `voltage-*` scheduled tasks: patrol (ZEUS), watch (sentinel),
      pulse (GAIA), push-lane (private mirror).
- [ ] norn.pulse SLOs + quarantine live for every periodic job.
- Acceptance: kill-all + reboot re-arms everything (verify-autopilot
  equivalent passes at the new root).

### V5 — Sovereign operation
- [ ] All further work happens in D:\VOLTAGE's own lanes.
- [ ] Promotion valve from Olympos becomes deliberate and rare;
      divergence is documented policy.
- Acceptance: one full week of unattended side-by-side operation with
  zero cross-fleet incidents in either ledger.

## Isolation contract summary

| Rule | Enforced by |
|---|---|
| Disjoint ports 44100–44199 | registry + boot-time squatter sweep |
| Task names `voltage-*` | installer scripts + task audit |
| Path jail (outbound) | `boundary.py` side B via organ dispatch seams (`VOLTAGE_ROOT` arms; `VOLTAGE_JAIL_EXEMPT` for the push lane only) |
| Foreign territory (inbound) | `boundary.py` side A + `verify_boundary.py` gate in sentinel/CI |
| Secrets never tracked | secrets gate pre-mirror-push |

One canonical module serves both sides (`boundary.py`, seeded at V2):
posture derives from whether the jail is armed, so neither fleet edits
the shared file to flip polarity.

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
