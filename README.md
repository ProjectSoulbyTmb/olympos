# Yggdrasil

The protective and operational ecosystem around the Soul fleet: a
protection kernel, a provenance realm, an automation sandbox, an
ecosystem health kernel, the THOTH operator kernel, and shared tooling.

## Quick start

```powershell
python doctor.py            # full local check + safe auto-repairs
python doctor.py --ci       # environment-independent subset (CI)
python sentinel.py          # remediate -> all gates -> incident ledger
```

## Components

| Path | What it is |
|---|---|
| `zeus/` | **ZEUS**: workspace protection kernel - patrols processes, integrity and churn on a tick loop; audit trail in `zeus/data/audit.jsonl`. Verify: `python zeus/verify_zeus.py` |
| `vulcan/` | **Vulcan**: offline smart-building automation sandbox - 7-zone thermal sim (37 devices), rules engine (sequences, priorities, mode-scoping, max-fires, motion events) + **warden** self-healing (waste/runaway/stuck-sensor repair, rule circuit-breaker w/ auto-revival, escalated load shedding, corrupt-save recovery), authoritative JSON-lines server on 127.0.0.1:43901. Verify: `python vulcan/verify_vulcan.py` |
| `hades/` | **Hades**: provenance realm - file fingerprinting, watermarking, and audit of artifact lineage. Verify: `python hades/verify_hades.py` |
| `gaia/` | **GAIA**: ecosystem health kernel (Node) - collects vitals from every member system (git sync state, commit age, CI verdicts, daemon freshness), scores each 0-100, raises severity-ranked alerts. Test: `cd gaia && npm test` |
| `thoth-private/` | **THOTH** operator-kernel modules: grants/safety, knowledge routing, scribe documentation service, stabilizer, scaffold, autonomic loop |
| `ptah/` | **PTAH**: software-engineering agent kernel - event-sourced reasoning-action loop over audited tools (terminal, file editor, grep, task tracker, verify-gate runner, memory), risk-classified actions with confirmation gating, keyword-triggered skills, REST control plane on 127.0.0.1:43903. Offline-scriptable (`--demo`), provider-agnostic LLM brain (OpenAI-compatible/Anthropic). Verify: `python ptah/verify_ptah.py`; nightly self-check: `python -m ptah selfcheck` |
| `image-toolkit/` | Shared image-processing toolkit (Node) |

## Infrastructure

- `doctor.py` - one-command stabilization: entrypoint compilation,
  component gates (ZEUS, Vulcan, Hades), protected directories,
  integrity-baseline age, port squatters, stale bytecode purge.
- `sentinel.py` - continuous watchdog: runs every product gate,
  applies safe automatic remediations first, appends incidents to
  `data/sentinel/incidents.jsonl`. Use `--watch N` to keep watching.
- `register-zeus-task.ps1`, `register-sentinel-task.ps1`,
  `register-thoth-task.ps1` - Windows Scheduled Task helpers that keep
  the kernels running around the clock.
