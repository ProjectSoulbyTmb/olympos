---
description: Run one bounded ARGUS drift-audit cycle - verify one claim-source against disk reality, classify drift, stage corrections.
agent: argus
---

Execute exactly one ARGUS drift-audit cycle now: INVENTORY ->
VERIFY -> CLASSIFY -> PROPOSE -> RECORD -> STOP.

Claim-source to audit this cycle (empty = rotate your rotation):
$ARGUMENTS

- Read the newest `docs/plans/learning/*-argus.md` first; continue
  its rotation and open questions instead of starting cold.
- Two independent commands before declaring a doc wrong.
- Finish with the DRIFT status block.
