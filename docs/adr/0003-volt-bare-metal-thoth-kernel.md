# ADR-0003: VOLT runs on bare metal — THOTH is the kernel of record

| | |
|---|---|
| **Status** | Accepted (operator directive 2026-08-25: "I want THOTH to be my base metal kernel") |
| **Date** | 2026-08-25 |
| **Author** | HERMES (execution lane) |
| **Scope** | Future kernel code home `D:\VOLTAGE\kernel\thoth\` (lands post-V2), this repo's docs, roadmap Track B (V6–V12) |
| **Extends** | ADR-0002 (PROJECT VOLTAGE private sovereign OS) |

## Context

- The operator extended the PROJECT VOLTAGE goal: Volt must become a
  **fully usable operating system**, not only a sovereign agent fleet
  on a Windows host. In the same session the operator chose:
  - **Substrate:** true bare-metal kernel (own kernel; no Linux
    distro, no Windows-underneath product).
  - **Product surface seed:** the Eidovara lineage (`live-soul/`) —
    its UX, app model, themes, installer discipline seed the desktop
    work; see Consequences for the Electron honesty clause.
- "THOTH" currently names two real things in this ecosystem: the
  operator-kernel modules (`thoth-private/` — grants/safety, knowledge
  routing, scribe, stabilizer) and the integration mirror checkout
  (`D:\THOTH`). The operator now binds the name to the metal: THOTH is
  the kernel VOLTAGE runs on.

## Decision

1. **Identity.** VOLTAGE is the operating system; **THOTH is its
   kernel**. All kernel-level work, specs and code carry the THOTH
   name (`kernel/thoth`, `voltage-thoth-*` tasks when automation
   exists).
2. **Doctrine carry-over.** The four thoth-private modules graduate
   into kernel subsystems — concepts port, code does not:

   | thoth-private module | THOTH kernel subsystem | Fleet lineage feeding it |
   |---|---|---|
   | grants/safety | capability & permission enforcement | norn rights, zeus grant classes |
   | knowledge routing | IPC / message routing | ratatosk envelopes, buskit contracts |
   | scribe | journalling & provenance | hades sealing, norn witness |
   | stabilizer | fault recovery / supervised restart | doctor repairs, sentinel ledger |

3. **Language.** Rust recommended, C acceptable. **Final choice is an
   open item and the first gate of V6** — nothing metal is written
   before it closes.
4. **Two-track truth.** Track A (roadmap V1–V5) is unchanged: the
   Windows-hosted organ fleet remains the factory, control plane and
   CI harness that builds, tests and operates THOTH/VOLTAGE. No Python
   ships inside the metal kernel; stdlib-only doctrine applies to
   Track A realms, not to kernel code.
5. **Home.** Paper lives in Olympos `docs/` until the V2 bootstrap;
   kernel code lands exclusively at `D:\VOLTAGE\kernel\thoth\` after
   bootstrap. Olympos lanes never write there (boundary.py side A
   already enforces this); THOTH-kernel work happens in VOLTAGE's own
   lanes once they exist.
6. **Product surface.** The desktop (Track B V10+) rebuilds the
   Eidovara product surface natively on THOTH. **Electron does not run
   on early THOTH**; what carries over is design: app model, themes,
   media surfaces, installer/updater discipline, assistant-layer
   conventions. A Chromium/Electron port is a late, deliberate,
   separately-gated ambition — not assumed.

## Constraints honored

- Five guarantees (INTEGRATION.md §1) bind kernel work equally;
  least-privilege is literally the kernel's grants subsystem.
- FLOW discipline and the ADR-0002 isolation contract are unaffected;
  Track B consumes Track A artifacts through the same promotion valve.
- Local-first: a THOTH/VOLTAGE machine must be fully functional with
  networking disabled except its mirror push.

## Consequences

- Honest scale statement: a bare-metal kernel is a multi-year effort.
  Track A keeps delivering sovereign-fleet value every month while
  Track B advances phase-gated; neither blocks the other.
- Naming collision risk: "THOTH" the checkout vs "THOTH" the kernel.
  Docs disambiguate as "THOTH mirror" vs "THOTH kernel"; if ambiguity
  bites operationally, the mirror path may be renamed later (mechanical
  move, out of scope here).
- Divergence policy from ADR-0002 extends naturally: kernel code never
  promotes back into Olympos; organ→kernel concept promotions are
  documented decisions, not drift.

## Open items (gates, in order)

1. **Kernel language** — Rust vs C; closes at V6 start (ADR-0004 or
   amendment here).
2. **Reference hardware target** — the exact machine/board THOTH must
   boot first; closes before V7 leaves QEMU.
3. **Filesystem format** — closes before V9 userland genesis.
4. **Eidovara port strategy detail** — which surfaces rebuild first;
   closes before V10.
