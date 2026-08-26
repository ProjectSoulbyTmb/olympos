# VOLTAGE Authoring Bundle — install & promotion plan

Generated 2026-08-25 evening. Payload: the Creative Control OS
authoring stack (14 gate-proven blueprints + registration, muster
harness, sovereign exporter, ADR/contract/roadmap/DESIGN closure).

## Contents

- `daedalus/blueprint_*.py` ×14 — apollo-os, kinema-host,
  riley-bridge, media-lane, ent-composer, game-domain, know-gateway,
  learn-gateway, muse-curriculum, voltage-tasks, ops-domain,
  session-seal, sla-pulse, voltage-packager.
- `daedalus/blueprints.py` — includes the try-import registrations
  for all fourteen (`apollo-os` … `voltage-packager`). NOTE: the
  D:\VOLTAGE copy has its own `voltage-ops` registration — MERGE,
  do not overwrite: keep their block, append ours.
- `tools/muster_launch.py`, `tools/voltage_export.py`.
- Docs: ADR-0003, command-spec v1 (incl. §8 extension protocol,
  §10 hardening + B-matrix), roadmap with V6–V9 + tonight's V2/V3
  evidence ticks, DESIGN decision-log rows.

## Install into D:\VOLTAGE (deliberate valve — operator ordered)

1. Copy payload files over the root (blueprints merge as above;
   docs land under the existing docs/ tree; tools/ is new).
2. Drop the muse curriculum where the knowledge organ discovers it:
   `knowledge/muse/muse.json` = entries from
   `blueprint_muse.CURRICULUM` (convention auto-registers; loader
   law lives in the blueprint).
3. Registry rows to append (offset law already ratified by use):
   apollo :44120 tier1 · riley-engine :44128 tier2 · kinema-host
   :44130 tier2. Bus constants from contract §4; doctor SUITES
   gains one apollo entry pointing at its woven gate.
4. Commission apollo: `Workshop.weave("apollo-os",
   "organ/apollo-os")` then run its gate AT THE ROOT; wire
   `VOLTAGE_ROOT` env only (jail posture stays armed).

## Promotion orders (paper-first — draft, needs operator sign-off)

Phase P executes through the same manifest pump:

- P1 `promote-payload`: step ("P","authoring") copies staged payload
  from `organ/incoming/` (operator drops bundle contents there) into
  live positions per Install steps 1–3; digest-proof before/after;
  reseal via st_seal.
- P2 `commission-apollo`: weave + gate at root, then boot check on
  :44120 (fail-loud bind, port.txt discovery).
- P3 `studio-bind`: swap apollo builtin doubles for organ backends —
  kinema-host :44130, riley engine :44128, harmonia lane read-only;
  each swap gated by B7 double-run digests at root.

Acceptance: B1–B10 map in contract §10 flips fully executable at the
sovereign root; network-off run proves B4.

## Verify before you trust any of it

    python tools/muster_launch.py <blueprint>          # clean green
    python tools/muster_launch.py <bp> --fault <name>  # breaker bites
