import json
import os
import sys
import time


class Finding:
    def __init__(self, severity, area, message, action="report"):
        self.severity = severity
        self.area = area
        self.message = message
        self.action = action

    def as_dict(self):
        return {"severity": self.severity, "area": self.area,
                "message": self.message, "action": self.action}

    def __repr__(self):
        return f"[{self.severity}] {self.area}: {self.message}"


def check_world_integrity(root):
    findings = []
    try:
        sys.path.insert(0, root)
        from game import world as W
        xp = W.XP_TABLE
        if isinstance(xp, dict):
            levels = sorted(xp)
            if not levels or levels[0] != 1:
                findings.append(Finding("high", "world",
                                        "XP_TABLE missing level 1"))
            pairs = [(xp[a], xp[b]) for a, b in zip(levels, levels[1:])]
        elif isinstance(xp, (list, tuple)):
            if len(xp) < 2:
                findings.append(Finding("high", "world",
                                        "XP_TABLE too short"))
            pairs = list(zip(xp, xp[1:]))
        else:
            findings.append(Finding("critical", "world",
                                    f"XP_TABLE unexpected type "
                                    f"{type(xp).__name__}",
                                    action="block-release"))
            pairs = []
        for a, b in pairs:
            if b <= a:
                findings.append(Finding(
                    "critical", "world",
                    f"XP table non-monotonic ({a}->{b})",
                    action="block-release"))
                break
        shop = getattr(W, "SHOP_PRICES", {})
        bad_prices = [i for i, p in shop.items()
                      if not isinstance(p, (int, float)) or p < 0]
        if bad_prices:
            findings.append(Finding("medium", "world",
                                    f"invalid shop prices: {bad_prices[:5]}",
                                    action="block-release"))
        locs = getattr(W, "LOCATIONS", {})
        if not locs:
            findings.append(Finding("high", "world", "LOCATIONS empty"))
        if not hasattr(getattr(W, "World", None), "score_task"):
            findings.append(Finding("low", "world",
                                    "World.score_task missing"))
    except Exception as e:
        findings.append(Finding("high", "world",
                                f"integrity check failed: "
                                f"{type(e).__name__}: {e}"))
    return findings


def sweep_sessions(root, quarantine=True):
    findings = []
    runs_dir = os.path.join(root, "runs")
    qdir = os.path.join(runs_dir, "_quarantine")
    if not os.path.isdir(runs_dir):
        return findings
    for dirpath, dirnames, filenames in os.walk(runs_dir):
        if "_quarantine" in dirpath:
            continue
        dirnames[:] = [d for d in dirnames if d != "_quarantine"]
        for fn in filenames:
            if fn.startswith("session") and fn.endswith(".json"):
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict) or "tick" not in data:
                        raise ValueError("missing tick field")
                except (json.JSONDecodeError, ValueError, OSError) as e:
                    stamp = int(time.time())
                    if quarantine:
                        os.makedirs(qdir, exist_ok=True)
                        dest = os.path.join(
                            qdir, f"{fn}.corrupt-{stamp}")
                        try:
                            os.replace(path, dest)
                            findings.append(Finding(
                                "medium", "sessions",
                                f"quarantined {os.path.relpath(path, root)} "
                                f"({e})", action="auto-fixed"))
                            continue
                        except OSError:
                            pass
                    findings.append(Finding("medium", "sessions",
                                            f"corrupt session unreadable: "
                                            f"{e}"))
    return findings


def check_data_freshness(root, max_age_hours=48):
    findings = []
    knowledge = os.path.join(root, "knowledge")
    for label, rel in (("digest", os.path.join("knowledge", "digest.md")),
                       ("ge prices", os.path.join("knowledge", "live",
                                                  "ge_prices.json"))):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            findings.append(Finding("medium", "data",
                                    f"{label} missing - run update-knowledge",
                                    action="needs-update"))
            continue
        age_h = (time.time() - os.path.getmtime(path)) / 3600
        if age_h > max_age_hours:
            findings.append(Finding("low", "data",
                                    f"{label} is {age_h:.0f}h old",
                                    action="needs-update"))
    return findings


def audit_best_scores(root):
    findings = []
    best_path = os.path.join(root, "runs", "wc_xp_best.json")
    if os.path.exists(best_path):
        try:
            with open(best_path, encoding="utf-8") as f:
                best = json.load(f)
            score = best.get("score", 0) if isinstance(best, dict) else 0
            if score <= 0:
                findings.append(Finding("low", "scores",
                                        "wc_xp_best.json has no positive "
                                        "score"))
        except (json.JSONDecodeError, OSError):
            pass
    return findings


def patrol(root, quarantine=True, max_data_age_hours=48):
    findings = []
    findings += check_world_integrity(root)
    findings += sweep_sessions(root, quarantine=quarantine)
    findings += check_data_freshness(root, max_data_age_hours)
    findings += audit_best_scores(root)
    return findings
