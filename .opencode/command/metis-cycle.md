---
description: Run one bounded METIS mining cycle - sweep incident/audit streams, deduplicate against the vault, stage up to 5 lesson proposals.
agent: metis
---

Execute exactly one METIS mining cycle now: MINE -> CLUSTER -> DRAFT
-> RECORD -> STOP.

Operator focus (may be empty): $ARGUMENTS

- Read the newest `docs/plans/learning/*-metis.md` first and resume
  from its NEXT line instead of re-deriving history.
- Budget: at most 5 proposals, one log in
  `docs/plans/learning/`. Proposals only - never touch
  `knowledge/lessons.json`.
- Finish with the MINED status block.
