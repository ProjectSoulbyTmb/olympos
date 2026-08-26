import time

from . import config
from .logging_setup import get_logger, log_mtime

READY_LINE = "FLEET READY FOR FULL INTEGRATION"
NOT_READY_LINE = "FLEET NOT READY"


def collect(supervisors, scheduler):
    rows = []
    for name, sup in supervisors.items():
        s = sup.snapshot()
        fresh = None
        if s["state"] == "RUNNING":
            mt = log_mtime(name)
            limit = supervisors[name].spec.get("freshness", 900)
            fresh = (mt is not None and time.time() - mt <= limit)
        ok = (
            s["state"] == "RUNNING"
            and s["pid"] is not None
            and fresh is True
            and s["consecutive_crashes"] < 3
        )
        rows.append({
            "name": name,
            "kind": "singleton",
            "state": s["state"],
            "pid": s["pid"],
            "restarts": s["restarts"],
            "crashes": s["consecutive_crashes"],
            "job_assigned": s.get("job_assigned"),
            "log_fresh": fresh,
            "ok": ok,
        })
    for name, j in scheduler.oneshots.items():
        s = j.snapshot()
        spec = j.spec
        horizon = (
            26 * 3600 if "daily" in spec else spec["interval"] * 2 + 60
        )
        ran_recent = s["last_run"] is not None and time.time() - s["last_run"] <= horizon
        clean = s["last_exit"] in (0, None)
        scheduled_future = s["last_run"] is None and s["next_run"] > time.time()
        rows.append({
            "name": name,
            "kind": "oneshot",
            "state": "BUSY" if s["busy"] else ("IDLE" if s["last_run"] else "PENDING"),
            "pid": None,
            "runs": s["runs"],
            "last_exit": s["last_exit"],
            "ran_recent": ran_recent or scheduled_future,
            "ok": (ran_recent and clean) or scheduled_future,
            "next_run": s["next_run"],
        })
    return rows


def report(rows):
    lines = []
    lines.append(f"OLYMPUS MUSTER v{config.VERSION} — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("-" * 78)
    for r in rows:
        mark = "[OK]" if r["ok"] else "[!!]"
        detail = f"pid={r['pid']}" if r["kind"] == "singleton" else \
            f"exit={r.get('last_exit')} runs={r.get('runs', 0)}"
        extra = ""
        if r["kind"] == "singleton":
            extra = f" crashes={r['crashes']} job={r['job_assigned']} logfresh={r['log_fresh']}"
        lines.append(f"{mark} {r['name']:<22} {r['state']:<9} {detail}{extra}")
    greens = sum(1 for r in rows if r["ok"])
    total = len(rows)
    verdict = f"MUSTER: {greens}/{total} GREEN — {READY_LINE if greens == total else NOT_READY_LINE}"
    lines.append("-" * 78)
    lines.append(verdict)
    text = "\n".join(lines)
    archive = get_logger("muster")
    for line in lines:
        archive.info(line)
    return text, greens == total


def run_muster(supervisors, scheduler):
    text, ready = report(collect(supervisors, scheduler))
    try:
        with open(
            __import__("os").path.join(
                config.LOG_DIR,
                f"muster-{time.strftime('%Y%m%d-%H%M%S')}.txt",
            ),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(text + "\n")
    except OSError:
        pass
    return text, ready
