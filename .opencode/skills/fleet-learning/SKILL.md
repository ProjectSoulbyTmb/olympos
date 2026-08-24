---
name: fleet-learning
description: Shared doctrine for Athena's learning subfleet (metis, argus, logia) and anyone consuming the knowledge pipeline - evidence map, proposal schema, promotion workflow, budgets. Trigger when mining lessons, auditing drift, synthesizing patterns, staging or reviewing learning proposals.
---

# Fleet-learning doctrine: how the fleet learns

Learning is a PIPELINE with human checkpoints, not a memory dump.
Nothing reaches `knowledge/lessons.json` without operator sign-off;
everything upstream of that is proposals with provenance.

## 1. The subfleet

| Agent | Diet | Output | Budget |
|---|---|---|---|
| **metis** | incidents.jsonl, audit.jsonl, health_report FAILs, gate failures | lesson proposals | <= 5/cycle |
| **argus** | doc claims vs disk/registry/ports/ci reality | drift corrections + codex-update proposals | <= 5/cycle |
| **logia** | cycle logs, playbook, engineering rules, proposals queue | pattern/rule amendments (>= 3 corroborations) | <= 3/cycle |

## 2. Evidence map (all readers in `learning/evidence.py`)

| Stream | Path | Owner |
|---|---|---|
| Watchdog ledger | `data/sentinel/incidents.jsonl` | sentinel |
| Patrol trail | `zeus/data/audit.jsonl` | ZEUS |
| Doctor report | `data/health_report.json` | doctor |
| Cycle logs | `docs/plans/cycles/*.md`, `docs/plans/learning/*.md` | athena + subfleet |
| Proposal queue | `knowledge/proposals/*.proposal.json` | metis/argus/logia |

Quiet streams are normal; readers never crash on absence.

## 3. Proposal schema

```json
{"v":1, "proposed_by":"metis", "proposed_ts":"...",
 "evidence":["path:line", "..."], "rationale":"...",
 "lesson":{"id":"L###","title":"...","category":"...",
           "source":"...","lesson":"imperative rule","tags":[...]},
 "status":"proposed"}
```

Stage via `python -m learning propose ...`. The CLI validates against
the vault schema and refuses unknown categories / missing fields.

## 4. Promotion workflow

```
subfleet stages proposal
  -> ATHENA validates (dedupe vs vault, evidence spot-check)
    -> OPERATOR yes/no   (the human checkpoint)
      -> accepted: append to lessons.json with next L###
         rejected: delete proposal file, note reason in decision log
```

Athena consumes the queue at the top of every planning cycle:
`python -m learning report`.

## 5. Bounds (playbook pattern 9)

- Bounded cycles, persisted logs, budget caps per run.
- Learners never edit `lessons.json`, never weaken gates, never
  invent evidence; judgment calls escalate to humans.
- The vault is append-only: deprecate, never delete or renumber.
