import json
import os
import time


class Sentinel:
    """Anomaly watch: score regressions, error spikes, staleness."""

    def __init__(self, root, state, max_log_errors=5):
        self.root = root
        self.state = state
        self.max_log_errors = max_log_errors

    def _best_regressions(self):
        regressions = []
        runs = os.path.join(self.root, "runs")
        best_path = os.path.join(runs, "wc_xp_best.json")
        marker_path = os.path.join(runs, "sentinel_marks.json")
        marks = {}
        try:
            with open(marker_path, encoding="utf-8") as f:
                marks = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        if os.path.exists(best_path):
            try:
                with open(best_path, encoding="utf-8") as f:
                    score = (json.load(f) or {}).get("score", 0)
                prev = marks.get("wc_xp_best")
                if prev is not None and score < prev * 0.5:
                    regressions.append(f"wc_xp best collapsed "
                                       f"{prev}->{score}")
                marks["wc_xp_best"] = max(prev or 0, score)
            except (OSError, json.JSONDecodeError):
                pass
        tmp = marker_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(marks, f)
        os.replace(tmp, marker_path)
        return regressions

    def _error_spike_in_mind_log(self):
        recent = self.state.recent(30)
        errors = [e for e in recent
                  if "error" in str(e.get("event", "")).lower()
                  or e.get("status") == "failed"]
        if len(errors) >= self.max_log_errors:
            return [f"{len(errors)} error events in last {len(recent)} "
                    f"mind log entries"]
        return []

    def _artifact_staleness(self):
        alerts = []
        exe = os.path.join(self.root, "OSRS-Suite.exe")
        py = os.path.join(self.root, "osrs_app.py")
        if os.path.exists(exe) and os.path.exists(py):
            if os.path.getmtime(exe) < os.path.getmtime(py):
                alerts.append("OSRS-Suite.exe older than osrs_app.py - "
                              "rebuild pending")
        return alerts

    def sweep(self):
        alerts = []
        alerts += self._best_regressions()
        alerts += self._error_spike_in_mind_log()
        alerts += self._artifact_staleness()
        for msg in alerts:
            self.state.log("sentinel", "alert", msg)
        return alerts
