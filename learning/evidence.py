"""Evidence readers: safe tails over every organ's learning streams.

Each reader degrades to an empty list/dict when its stream is absent
- learners must never crash on a quiet organ. Paths follow the
runtime layout documented in INTEGRATION.md section 2.
"""

import glob
import json
import os

from .vault import repo_root


def _root():
    return repo_root()


def tail_jsonl(path, limit=100):
    out = []
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # corrupt lines are quarantined upstream
    except OSError:
        return []
    return out[-limit:]


def incidents(limit=200):
    """Sentinel watchdog ledger (gates, remediations, summaries)."""
    return tail_jsonl(os.path.join(_root(), "data", "sentinel",
                                   "incidents.jsonl"), limit)


def zeus_audit(limit=200):
    """Protection kernel patrol trail."""
    return tail_jsonl(os.path.join(_root(), "zeus", "data",
                                   "audit.jsonl"), limit)


def health_report():
    """Last doctor report, or {} when absent."""
    p = os.path.join(_root(), "data", "health_report.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def failing_checks():
    rep = health_report()
    rows = rep.get("rows", [])
    return [r for r in rows if str(r.get("status", "")).upper()
            in ("FAIL", "UNRESOLVED")]


def cycle_logs(limit=10):
    """Newest Athena/learning cycle logs, newest first."""
    pat = os.path.join(_root(), "docs", "plans", "cycles", "*.md")
    files = sorted(glob.glob(pat), reverse=True)
    return files[:limit]


def proposals():
    """Pending lesson proposals from the subfleet."""
    d = os.path.join(_root(), "knowledge", "proposals")
    out = []
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if f.endswith(".proposal.json"):
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    out.append(json.load(fh))
            except (OSError, ValueError):
                continue
    return out


def stream_summary():
    """One dict describing every stream's liveness - the diet card."""
    def n(x):
        return len(x) if isinstance(x, list) else (1 if x else 0)

    return {
        "incidents": n(incidents()),
        "zeus_audit": n(zeus_audit()),
        "health_report": n(health_report()),
        "failing_checks": len(failing_checks()),
        "cycle_logs": len(cycle_logs()),
        "proposals": len(proposals()),
    }
