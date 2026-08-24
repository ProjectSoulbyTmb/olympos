"""Learning report: distill evidence streams into candidate findings.

Heuristics only - the heavy reading is the agents' job. This gives
metis/argus/logia (and any cycle) a cheap, deterministic starting
map: what recurred, what failed, what is queued.
"""

import collections

from . import evidence


def build():
    rep = {"streams": evidence.stream_summary(), "findings": []}

    # 1. Recurring incident kinds (top offenders first).
    kinds = collections.Counter(
        str(i.get("kind", i.get("gate", "unknown")))
        for i in evidence.incidents()
        if isinstance(i, dict))
    for kind, count in kinds.most_common(5):
        if count >= 2:
            rep["findings"].append({
                "type": "recurring-incident",
                "kind": kind,
                "count": count,
            })

    # 2. Currently failing doctor checks.
    for row in evidence.failing_checks():
        rep["findings"].append({
            "type": "failing-check",
            "check": row.get("check"),
            "detail": str(row.get("detail", ""))[:160],
        })

    # 3. Proposal queue pressure.
    props = evidence.proposals()
    if props:
        by = collections.Counter(p.get("proposed_by", "?")
                                 for p in props)
        rep["findings"].append({
            "type": "proposal-queue",
            "count": len(props),
            "by": dict(by),
        })

    return rep


def markdown(rep):
    lines = ["# Learning report", ""]
    s = rep["streams"]
    lines.append(f"streams: {s}")
    lines.append("")
    if not rep["findings"]:
        lines.append("_No candidate findings above threshold._")
    for f in rep["findings"]:
        lines.append(f"- **{f['type']}** "
                     + ", ".join(f"{k}={v}" for k, v in f.items()
                                 if k != "type"))
    return "\n".join(lines) + "\n"
