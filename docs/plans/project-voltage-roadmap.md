# PROJECT VOLTAGE — Private Sovereign OS Roadmap (V0–V12, two tracks)

Companion to `docs/adr/0002-project-voltage.md` (decision of record)
and `docs/adr/0003-volt-bare-metal-thoth-kernel.md` (THOTH kernel of
record). Two tracks, independently gated:

- **Track A (V0–V5)** — sovereign foundation: the organ fleet on the
  Windows host; becomes the factory + control plane for everything
  Track B builds.
- **Track B (V6–V12)** — the metal ladder: THOTH kernel and the
  userland that makes VOLT a fully usable operating system.

Execution doctrine: paper-first per FLOW protocol; each phase gates
the next; bootstrap (V2) additionally requires the Olympos W0
precondition (rebase complete + one full green CI push-run on main).

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

---

# Track B — The metal ladder (V6–V12, THOTH kernel)

Per `docs/adr/0003-volt-bare-metal-thoth-kernel.md`: THOTH is the
kernel of record; VOLTAGE is the OS. Track A above remains the factory
and control plane that builds, tests and operates everything below.
Kernel code lives at `D:\VOLTAGE\kernel\thoth\` post-V2; before that,
paper only. ADR-0003 open items gate their phases: language → V6,
reference hardware → V7 exit, filesystem → V9, Eidovara port strategy
→ V10.

### V6 — THOTH paper architecture (first metal phase)
- [ ] Close the kernel-language decision (Rust recommended, C
      acceptable) — ADR-0004 or amendment to ADR-0003.
- [ ] Subsystem spec derived from the ADR-0003 doctrine map: grants,
      routing, scribe, stabilizer + scheduler, memory, drivers, init.
- [ ] Toolchain + repo skeleton decision for `kernel/thoth` (CI builds
      artifacts from day one, even before anything boots).
- Gate: language closed; subsystem paper reviewed by operator.

### V7 — Hello metal
- [ ] UEFI boot under QEMU/OVMF: a THOTH image reaches framebuffer
      output (boot logo / text).
- [ ] CI builds a bootable ISO and runs a QEMU smoke gate per commit.
- [ ] Reference hardware target named and provisioned (ADR-0003 open
      item #2 closes).
- Gate: `voltage-thoth-smoke` green in CI; ISO boots verified headless.

### V8 — Kernel core
- [ ] Physical/virtual memory manager; region allocators.
- [ ] Scheduler with THOTH-grant-aware priorities (capability classes
      from day one; norn lineage).
- [ ] IPC: ratatosk envelope semantics reborn as kernel message
      passing (buskit contracts as the wire format).
- [ ] virtio driver set under QEMU (block, net, console).
- Gate: two processes exchange kernel IPC under memory pressure
  without corruption; stabilizer-lineage watchdog recovers a killed
  process automatically.

### V9 — Userland genesis
- [ ] Filesystem format chosen (ADR-0003 open item #3) + implemented;
      crash-consistent journal or CoW.
- [ ] Init (PID 1) with supervised-restart doctrine (doctor lineage).
- [ ] Text shell + process model; per-process capability rights
      enforced by the grants subsystem — least privilege native, not
      bolted on.
- Gate: power-on to shell; files survive hard reset; a rogue process
  cannot read outside its grant.

### V10 — Desktop seed (Eidovara surface, rebuilt natively)
- [ ] Framebuffer compositor + window server; keyboard/mouse input
      stack (touch later).
- [ ] Native Eidovara-lineage app model: manifests, launch,
      install/uninstall (daedalus/sindri templates lineage).
- [ ] Themes + assistant-layer conventions ported as design, not code;
      ADR-0003 open item #4 (port strategy detail) closes here.
- Gate: launcher opens/switches/closes apps; live theme switch; zero
      Electron assumptions anywhere in the tree.

### V11 — Drivers + installer
- [ ] Driver breadth on the reference machine: NVMe/AHCI, xHCI/USB,
      NIC, GPU modesetting.
- [ ] Self-installer writes THOTH/VOLTAGE to disk; release discipline
      inherited from Eidovara (checksums, provenance, recovery path).
- Gate: reference machine boots from its own installed disk; reinstall
      from media works; bad-update rollback proven once.

### V12 — Daily driver on metal
- [ ] Operator uses VOLT-on-THOTH as a primary working environment.
- [ ] Update lane live (tide-kernel discipline applied to OS images);
      incident ledger clean.
- Acceptance: target four weeks of real use on metal with zero
  data-loss incidents and every failure recovered by the stabilizer
  path, not by hand.

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

RESOLVED 2026-08-25 (operator "go" ordering V2 bootstrap):

1. Mirror repo: `ProjectSoulbyTmb/voltage`, private. Created.
2. Root spelling: `D:\VOLTAGE`.
3. Port block 44100–44199 ratified; seeded organs shift suffix-preserving
   (4390N → 4410N).
