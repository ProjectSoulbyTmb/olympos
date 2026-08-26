# Capability ledger - THOTH brain posture

Measured, sealed record of what the fleet's brains can do **right
now**, what stays armed but dormant, and exactly how to re-probe.
Decision authority: FLEET ORDER FO-2026-08-25-FULL-COMM v3
(operator: full execution and release; keep everything a local
suite application). Doctrine of record:
`knowledge/engineering-rules.md` rule 7 (breakers), rule 10
(verifier-checked changes), rule 11 (seal + anchor); deterministic-
first throughout: the small brain assists simple slots only, never
load-bearing; the scripted brain is the CI/offline default; NO
cloud fallback anywhere on this ladder.

## Measured posture (2026-08-26, repo head `fc2728c`)

| # | Capability | Posture | Evidence | Notes / hard rule |
|---|---|---|---|---|
| 1 | Slot-sized codegen offline | **proven** | `verify_codegen` 9/9 green, zero network | journaled -> retry+jitter -> breaker -> scripted terminal leg; slots capped at 4000 chars, oversize refused by name (`slot_too_large`) |
| 2 | Fault survival mid-generation | **proven** | endpoint killed mid-suite; converged 6.23s | named refusals only, no hangs; breaker state visible closed/open/half_open (rule 7) |
| 3 | Generation journal integrity | **proven** | scoped Hades seal green; tamper caught as MODIFIED | every leg journaled per `buskit.llmlog` contract; digests, never raw prompts |
| 4 | Determinism of fallback | **proven** | byte-stable artifacts + reproducible jitter across reruns | same seed in, same artifact out |
| 5 | PTAH LM Studio seam | **proven (offline-safe)** | `verify_ptah` 16/16 incl. seam check | env-only config (`PTAH_LMSTUDIO_URL`/`PTAH_LMSTUDIO_MODEL`); nothing dials at boot; scripted boot unchanged |
| 6 | Remote model slot assist | **armed, unexercised** | both LM Studio endpoints dead (HTTP 000) | rides the SAME chain as slot 1 via `RemoteBrain`; activates purely by env |
| 7 | App-scale codegen | **non-goal (today)** | milestone M-GPU1 gate below | deliberately out of `buskit.slotgen` scope; oversize is a refusal, not a truncation |

## Milestones armed as data

| Milestone | Entry condition | Unlocks | Tier |
|---|---|---|---|
| M-GPU1 | host reports >= 16 GB VRAM | app-scale codegen joins the ladder; slot cap lifted for designated lanes only | armed |
| M-GPU2 | host reports >= 24 GB VRAM, dual-model routing | small model assists simple slots + large model reviews; scripted brain stays CI default | armed |

Entry is measured, never assumed: run the probe command in the
evidence block plus `nvidia-smi --query-gpu=memory.total` and
record the output in a fresh ledger row before flipping any tier.

## Auto-reprobe hook (recorded, NOT daemonized)

```text
# 1. probe the seam (both ports):
curl.exe -s -o NUL -w "%{http_code}" --connect-timeout 2 http://127.0.0.1:1234/v1/models
curl.exe -s -o NUL -w "%{http_code}" --connect-timeout 2 http://127.0.0.1:12345/v1/models
# 2. if HTTP 200 anywhere: upgrade the suite against it live -
$env:CODEGEN_LIVE_URL = 'http://127.0.0.1:<port>/v1'; $env:CODEGEN_LIVE_MODEL = '<model-id>'
python verify_codegen.py   # live-seam check stops skipping
# 3. re-seal this ledger with the fresh evidence block (below).
```

## Evidence block (self-digesting)

The JSON block below is the machine-readable evidence of record.
`self_digest` = sha256 over the canonical serialization of this
object WITHOUT the `self_digest` key (sort_keys, compact
separators, UTF-8). Recompute it to authenticate the block.

```json
{
  "brain": {
    "lmstudio_1234": "dead (HTTP 000, curl exit 28, 2026-08-26)",
    "lmstudio_12345": "dead (HTTP 000, curl exit 28, 2026-08-26)",
    "posture": "OFFLINE",
    "probe_command": "curl.exe -s -o NUL -w \"%{http_code}\" --connect-timeout 2 http://127.0.0.1:<port>/v1/models"
  },
  "doctrine": "deterministic-first; scripted brain is the CI/offline default; no cloud fallback",
  "ledger_version": 1,
  "measured_at": "2026-08-26",
  "operator_order": "FLEET ORDER FO-2026-08-25-FULL-COMM v3 - full execution and release; local suite only",
  "repo_head": "fc2728c16d6636f892707fa4d6a1e5595789d4af",
  "seams": {
    "codegen_live_upgrade": {
      "behavior": "verify_codegen live-seam check upgrades in place when injected; skipped when absent",
      "keys": [
        "CODEGEN_LIVE_URL",
        "CODEGEN_LIVE_MODEL"
      ]
    },
    "ptah_lm_studio": {
      "boot_behavior": "no dial at config/boot; scripted mode unchanged when endpoints dead",
      "keys": [
        "PTAH_LMSTUDIO_URL",
        "PTAH_LMSTUDIO_MODEL"
      ],
      "precedence": "canonical PTAH_BASE_URL/PTAH_LLM_MODEL > alias > provider default"
    }
  },
  "self_digest": "b294fe42259abc3c63327a4b020f36b8849bb12bc7007f8d4cda67946ff79bd5",
  "suites": {
    "ptah_selfcheck": {
      "command": "python -m ptah selfcheck",
      "pruned": 0,
      "secs": 11.9,
      "verdict": "PASS"
    },
    "verify_codegen": {
      "command": "python verify_codegen.py --report data/forge/codegen-report.json",
      "fault_injection": "endpoint killed mid-suite: breaker closed->open->half_open->closed, converged 6.23s, refusals named",
      "journaled_legs_validated": 4,
      "passed": 9,
      "report_sha256": "d089d56ac494fc00fe6a83cb6b6cbb39ff8ea35ab8834c7abcc6d6e6eb582246",
      "total": 9,
      "wall_s": 18.88
    },
    "verify_ptah": {
      "command": "python ptah/verify_ptah.py",
      "note": "includes lm studio env seam offline-safe check",
      "passed": 16,
      "total": 16
    }
  }
}
```

## Seal

This file is pinned by a scoped Hades seal (product
`capability-ledger`, include `docs/plans/capability-ledger.md`).
Seal state lives machine-local under `data/hades-ledger-seal/`
(gitignored by house doctrine - keys never leave the machine).

```text
seal  : python -c "from hades.kernel import Hades; Hades(root='.', state_dir='data/hades-ledger-seal', config={'include_realms': False, 'products': [{'name': 'capability-ledger', 'include': ['docs/plans/capability-ledger.md'], 'exclude': []}]}).seal()"
verify: same construction, then .verify() -> violations == []
tamper: any byte change flips verify to MODIFIED (evidence is quarantined, never destroyed)
```
