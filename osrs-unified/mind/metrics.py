import json
import os
import time


def _best_scores(root):
    scores = {}
    runs = os.path.join(root, "runs")
    if os.path.isdir(runs):
        for name in os.listdir(runs):
            if name.endswith("_best.json"):
                try:
                    with open(os.path.join(runs, name),
                              encoding="utf-8") as f:
                        data = json.load(f)
                    task = name[:-len("_best.json")]
                    scores[task] = (data or {}).get("score")
                except (OSError, json.JSONDecodeError):
                    continue
    return scores


def snapshot(root, extra=None):
    from mind import moderator
    findings = moderator.patrol(root, quarantine=False)
    entry = {
        "ts": round(time.time(), 3),
        "findings": len(findings),
        "critical": sum(1 for f in findings if f.severity == "critical"),
        "best_scores": _best_scores(root),
    }
    try:
        with open(os.path.join(root, "pyproject.toml"),
                  encoding="utf-8") as f:
            for line in f:
                if line.startswith("version"):
                    entry["version"] = line.split('"')[1]
                    break
    except OSError:
        pass
    if extra:
        entry.update(extra)
    path = os.path.join(root, "runs", "metrics.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def summary(root, last_n=30):
    path = os.path.join(root, "runs", "metrics.jsonl")
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    tail = entries[-last_n:]
    if not tail:
        return {"samples": 0}
    first, lastd = tail[0], tail[-1]
    trends = {}
    for task in {t for e in tail for t, s in e.get("best_scores", {}).items()
                 if s is not None}:
        values = [e["best_scores"].get(task) for e in tail
                  if e.get("best_scores", {}).get(task) is not None]
        if values:
            trends[task] = {"first": values[0], "last": values[-1],
                            "delta": values[-1] - values[0]}
    return {
        "samples": len(tail),
        "span_hours": round((lastd["ts"] - first["ts"]) / 3600, 2)
        if len(tail) > 1 else 0.0,
        "critical_total": sum(e.get("critical", 0) for e in tail),
        "findings_last": lastd.get("findings"),
        "version": lastd.get("version"),
        "task_trends": trends,
    }
