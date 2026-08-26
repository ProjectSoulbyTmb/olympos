---
description: Muster the full learning subfleet - run metis, argus, and logia cycles in parallel, then compile one consolidated muster report.
---

# Fleet muster

You are marshaling ATHENA's learning subfleet for a coordinated sweep.
Scope for this muster: $ARGUMENTS (if empty, run the standard full sweep).

## Doctrine (binding)

- Follow the `fleet-learning` skill: bounded cycles, budget caps,
  proposals only - learners NEVER edit `knowledge/lessons.json`,
  weaken gates, or invent evidence.
- Every proposal must cite concrete evidence (`path:line`) from the
  evidence map; no evidence, no proposal.
- Nothing reaches the vault without operator sign-off. You stage
  proposals; the human decides.

## Muster order

Launch all three subagents IN PARALLEL (single message, multiple task
calls). Each gets: today's date, this scope note, and its budget cap.

1. **@metis** (lesson miner): sweep `data/sentinel/incidents.jsonl`,
   `zeus/data/audit.jsonl`, `data/health_report.json` FAILs, and gate
   failures. Output <= 5 deduplicated lesson proposals staged via
   `python -m learning propose ...` into `knowledge/proposals/`.
2. **@argus** (drift auditor): compare documented claims against disk -
   doc-vs-disk membership, registry-vs-reality (`realms/registry.json`),
   port claims vs listeners, codex staleness
   (`docs/plans/cycles/`, knowledge docs). Output <= 5 drift corrections
   / codex-update proposals.
3. **@logia** (pattern synthesizer): read recent cycle logs
   (`docs/plans/cycles/*.md`, `docs/plans/learning/*.md`), the playbook,
   engineering rules, and the proposal queue. Promote only patterns with
   >= 3 corroborations into pattern/rule amendment proposals, <= 3/cycle.

## After muster

Compile ONE muster report for the operator containing:

- Per-agent verdict: what each swept, what it found, what it staged.
- Proposal queue state: run `python -m learning report`, list new
  proposals by id with one-line rationale each.
- Drift findings that need immediate fixes vs cosmetic ones.
- Recommended operator decisions (accept/reject) - clearly marked as
  recommendations, awaiting human yes/no.

Do not apply any accepted lessons yourself. End the report with the
exact next commands the operator should run to review the queue.
