# Promotion decisions - learning queue of 2026-08-26

Operator order: "promote" (2026-08-26, post-Athena validation). Executed by
Hermes primary per fleet-learning pipeline. Validation record:
`docs/plans/learning/2026-08-26-0233-athena-validation.md`.

## Rulings

| Final ID | Proposal | By | Athena verdict | Disposition |
|---|---|---|---|---|
| L046 | Automated merges wait for required checks to finish green | metis | ACCEPT | promoted as-is |
| L047 | A clean ledger proves nothing unless the watcher provably ran | metis | ACCEPT | promoted as-is |
| L048 | Verify claimed ports by process identity, not port number or name match | metis | ACCEPT | promoted as-is |
| L049 | Amend historical records only by dated annotation or disclosed recreation - never silent rewrite | logia | ACCEPT | promoted as-is |
| L050 | Reconcile monotonic identifiers against merged history before allocating them | metis | AMEND | promoted; anchor re-pointed volt-comm.md:60 -> :64-67 |
| L051 | Pin interpreters by absolute path in gates, hooks and scheduled tasks | metis | ACCEPT | promoted as-is |
| L052 | Unlock construction waves only on provably green preconditions - paper precedes metal | logia | AMEND | promoted; anchor re-pointed volt-comm.md:38 -> :44-45 |
| L053 | Finders report and route - detection lanes never repair inline | logia | AMEND | promoted; anchor re-pointed volt-comm.md:45 -> :51-58 |
| L054 | INTEGRATION sec6 catalogue missing live fleet.plan kind on the daedalus lane | argus | AMEND | promoted; re-targeted from `updates` row to `daedalus` lane row per buskit/envelope.py:58 TOPICS truth (title + lesson text rewritten) |
| L055 | Codex facts carry exactly one date-stamped value each (SKILL.md 21-vs-32 self-contradiction) | argus | ACCEPT | promoted as-is |
| L056 | Decision-log entries naming other roots must carry lineage attribution (DESIGN.md ghost rows) | argus | ACCEPT | promoted as-is |
| - | INTEGRATION.md sec2 registry count 28 -> 32; persephone tier grouping wrong | argus | REJECT | proposal deleted. Reason: correction-not-lesson, near-dupe of L041 (re-derive stale truth-lists at every revision); the two concrete doc fixes are routed to the @argus doc-fix backlog instead of the vault |

## Anchor-shift note

All four failed citations traced to one cause: commit 3b71ed5 (01:51Z,
"volt-comm historical-label note") added six lines to
2026-08-25-volt-comm.md AFTER proposals staged at 01:55:44Z. Mutable cycle
logs are weak anchors; Athena recommends a stable-secondary-anchor rule
(section header + quoted fragment) as a future logia proposal.

## Post-promotion proof

- Vault: 56 lessons, next_id L057, ids monotonic+unique (script assertion +
  `verify_learning.py` 4/4 PASS)
- Queue: drained to 0 `.proposal.json`; 11 records renamed
  `*.promoted.json` with `promoted_id`/`promoted_ts`/validation-ref stamps
- Knowledge engine: `knowledge/verify_knowledge.py` 7/7 PASS
- No git operations (OneDrive checkout uncommitted except by operator
  order); promotion is local-disk state pending operator ship instructions

## Open follow-ups (not part of this promotion)

1. @argus doc-fix backlog: INTEGRATION.md sec2 count/tier fix;
   SKILL.md:69-70 parenthetical; DESIGN.md:311-312 lineage qualification.
2. L054's companion drift: `fleet.render-done` emitted on updates but
   absent from buskit TOPICS["updates"] (inventory sec5, cited).
3. @logia candidate: stable-secondary-anchor rule (>=2 corroborations
   already: today's four shifted anchors).
