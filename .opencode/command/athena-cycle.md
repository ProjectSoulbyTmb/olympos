---
description: Run one full autonomous ATHENA planning cycle (audit, distill, prioritize, specify, delegate, record).
agent: athena
---

Execute exactly one complete autonomous planning cycle now, following your
Autonomy kernel protocol: AUDIT -> DISTILL -> PRIORITIZE -> SPECIFY ->
DELEGATE -> RECORD -> STOP.

Operator focus for this cycle (may be empty): $ARGUMENTS

Rules for this run:

- If a focus was given, let it steer PRIORITIZE but do not skip AUDIT —
  findings from ground truth still get recorded.
- If no focus was given, self-select the top priority from your audit.
- Honor the budget: at most 3 artifacts plus the one cycle log in
  `docs/plans/cycles/`.
- If a previous cycle log exists, read the newest one first and resume from
  its NEXT ACTIONS instead of re-deriving history.
- Finish with the CYCLE status block.
