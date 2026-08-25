"""ARTEMIS hunt kernel - signatures, bounded repairs, escalation.

Design (INTEGRATION.md sections 3, 6, 8; playbook pattern 9):

  sweep() -> for each signature: hunt(ctx) -> findings
             -> policy check -> optional bounded repair
             -> ledger line (buskit envelope, 'incidents' topic)
             -> 'fleet.repair' letters on 'updates' when a repair lands

Every hunt function receives a ctx dict so the verify suite can point
the kernel at sandbox directories:

    here         repo/workspace root
    post_root    ratatosk data/post directory
    ledger_path  hunt.jsonl append-only incident ledger
    state_path   bounded-autonomy state (data/artemis/hunt-state.json)
    config       operator overrides (watched_organs, thresholds)

Severity ladder mirrors INTEGRATION.md section 8:
T1 breaker-grade, T2 degraded, T3 informational.
Repairs only touch runtime artifacts we own. Code changes are
reported with exact file:line - never auto-rewritten here.
"""

import datetime
import glob
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from artemis import ORGAN, VERSION          # noqa: E402

DATA_DIR = os.path.join(HERE, "data", "artemis")
LEDGER_PATH = os.path.join(DATA_DIR, "hunt.jsonl")
STATE_PATH = os.path.join(DATA_DIR, "hunt-state.json")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

# ---- policy bounds (playbook pattern 9 - no unbounded loops) --------
MAX_ATTEMPTS = 3        # repair attempts per target before escalation
ESCALATE_AFTER = 3      # sightings of an unrepairable finding before T1
COOLDOWN_SWEEPS = 12    # sweeps to stand down after an escalation

# ---- signature thresholds -------------------------------------------
STALE_HEARTBEAT_S = 900     # organ silent ~15 min -> zombie suspicion
LOCK_DEAD_S = 600           # bus stale-takeover is 10 s; 10 min is dead
CORRUPT_ALERT = 10          # quarantined letters before it rates T2
RETIRED_PORTS = (43590, 43591)   # registry = single source of ports
TRACKED_REPAIR_CAP = 50     # max git rm --cached calls per sweep
BASELINE_REL = os.path.join("zeus", "data", "baseline.json")
WATCHED_ORGANS = ("zeus", "hypnos", "gaia", "relay", "poseidon", "hebe")
REQUIRED_IGNORES = ("data/", "__pycache__/", "*.pyc", ".worktrees/")


def stamp():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------- context

def make_ctx(**overrides):
    ctx = {
        "here": HERE,
        "post_root": os.path.join(HERE, "data", "post"),
        "ledger_path": LEDGER_PATH,
        "state_path": STATE_PATH,
        "config_path": CONFIG_PATH,
        "netstat_text": None,       # injection seam for tests
        "realms": None,             # injection seam for tests
    }
    cfg = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:                # noqa: BLE001 - defaults are fine
        pass
    ctx["config"] = cfg
    ctx.update(overrides)
    return ctx


def load_realms(ctx):
    if ctx.get("realms") is not None:
        return ctx["realms"]
    try:
        import realms                # repo-root package
        return list(realms.all_realms())
    except Exception:                # noqa: BLE001 - hunt without roster
        return []


def _post(ctx):
    from ratatosk.bus import Post
    return Post(root=ctx["post_root"])


# ------------------------------------------------------- state + policy

def load_state(ctx):
    try:
        with open(ctx["state_path"], encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict) and isinstance(
                state.get("targets"), dict):
            return state
    except Exception:                # noqa: BLE001 - fresh start
        pass
    return {"sweeps": 0, "targets": {}}


def save_state(ctx, state):
    os.makedirs(os.path.dirname(ctx["state_path"]), exist_ok=True)
    tmp = ctx["state_path"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, ctx["state_path"])


def _rec(state, key):
    return state["targets"].setdefault(
        key, {"seen": 0, "attempts": 0, "cooldown": 0, "escalated": False})


def _cool_down(rec):
    if rec["cooldown"] > 0:
        rec["cooldown"] -= 1
        return True
    return False


# ------------------------------------------------------ ledger and bus

def record(ctx, finding, action):
    """Append one buskit envelope to the hunt ledger (A8 contract)."""
    payload = {
        "nymph": str(finding.get("nymph", "-")),
        "signature": str(finding.get("signature")),
        "target": str(finding.get("target"))[:200],
        "detail": str(finding.get("detail"))[:400],
        "severity": str(finding.get("severity", "T3")),
        "action": str(action),
    }
    os.makedirs(os.path.dirname(ctx["ledger_path"]), exist_ok=True)
    try:
        from buskit import envelope
        env = envelope.make("incident", ORGAN, payload,
                            topic="incidents", rights="watcher")
        line = envelope.dump(env)
    except Exception:                # noqa: BLE001 - never lose a finding
        line = json.dumps({"ts": stamp(), "kind": "incident",
                           "from": ORGAN, **payload})
    with open(ctx["ledger_path"], "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def announce_repair(ctx, finding):
    """Broadcast fleet.repair on the 'updates' topic (catalogue row)."""
    try:
        from ratatosk.bus import publish
        publish("updates", {
            "signature": finding.get("signature"),
            "target": str(finding.get("target"))[:200],
            "organ": ORGAN,
            "note": "bounded repair applied",
        }, frm=ORGAN, kind="fleet.repair", root=ctx["post_root"])
    except Exception:                # noqa: BLE001 - bus may be dark
        pass


def escalate(ctx, finding, why):
    """Repeat offender: T1 letter in the ledger + live incidents topic."""
    bumped = dict(finding, severity="T1")
    record(ctx, bumped, f"escalated: {why}")
    try:
        from ratatosk.bus import publish
        publish("incidents", {
            "kind": "artemis-escalation",
            "signature": finding.get("signature"),
            "target": str(finding.get("target"))[:200],
            "severity": "T1",
            "why": why,
            "organ": ORGAN,
        }, frm=ORGAN, kind="incident", root=ctx["post_root"])
    except Exception:                # noqa: BLE001 - ledger already has it
        pass


# ------------------------------------------------------------- hunters
# Each returns a list of findings:
# {signature, target, detail, severity, repairable}

def hunt_stale_organs(ctx):
    """Watched organs reporting Running-but-dead heartbeats."""
    watched = ctx["config"].get("watched_organs", list(WATCHED_ORGANS))
    stale_s = int(ctx["config"].get("stale_heartbeat_s",
                                    STALE_HEARTBEAT_S))
    findings = []
    try:
        post = _post(ctx)
    except Exception as exc:         # noqa: BLE001
        return [{"signature": "stale-organ", "target": "ratatosk",
                 "detail": f"bus unreachable: {exc}", "severity": "T2",
                 "repairable": False}]
    for name in watched:
        try:
            age = post.heartbeat_age(name)
        except Exception:            # noqa: BLE001
            age = None
        if age is None:
            findings.append({
                "signature": "stale-organ", "target": name,
                "detail": "no heartbeat on record",
                "severity": "T2", "repairable": False})
        elif age > stale_s:
            findings.append({
                "signature": "stale-organ", "target": name,
                "detail": f"heartbeat stale {int(age)}s "
                          f"(> {stale_s}s) - zombie suspicion; "
                          "revive belongs to watchdog/pulse",
                "severity": "T2", "repairable": False})
    return findings


def hunt_retired_ports(ctx):
    """Listeners squatting on retired registry ports."""
    text = ctx.get("netstat_text")
    if text is None:
        try:
            proc = subprocess.run(["netstat", "-ano"],
                                  capture_output=True, text=True)
            text = proc.stdout
        except Exception as exc:     # noqa: BLE001
            return [{"signature": "retired-port-squatter",
                     "target": "netstat",
                     "detail": f"probe failed: {exc}",
                     "severity": "T3", "repairable": False}]
    findings = []
    seen = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or "LISTENING" not in line.upper():
            continue
        local = parts[1] if len(parts) > 1 else ""
        pid = parts[-1]
        m = re.search(r":(\d+)$", local.strip())
        if not m:
            continue
        port = int(m.group(1))
        if port in RETIRED_PORTS and port not in seen:
            seen.add(port)
            findings.append({
                "signature": "retired-port-squatter",
                "target": str(port),
                "detail": f"listener pid={pid} on retired port "
                          f"{port}; kill is L2 - escalated, "
                          "not attempted",
                "severity": "T2", "repairable": False})
    return findings


def hunt_corrupt_letters(ctx):
    """Quarantined letters accumulating in organ seen/ dirs."""
    post_root = ctx["post_root"]
    threshold = int(ctx["config"].get("corrupt_alert", CORRUPT_ALERT))
    findings = []
    try:
        organs = os.listdir(post_root)
    except OSError:
        return findings
    for organ in sorted(organs):
        seen_dir = os.path.join(post_root, organ, "seen")
        if not os.path.isdir(seen_dir):
            continue
        bad = [p for p in glob.glob(os.path.join(seen_dir, "corrupt-*"))
               if os.path.isfile(p)]
        if len(bad) >= threshold:
            findings.append({
                "signature": "corrupt-letters", "target": organ,
                "detail": f"{len(bad)} quarantined letters in seen/ "
                          "(evidence preserved - inspect, do not purge)",
                "severity": "T2" if len(bad) >= CORRUPT_ALERT else "T3",
                "repairable": False})
    return findings


def hunt_ledger_corruption(ctx):
    """Envelope-contract lint over append-only ledgers (A8)."""
    targets = [
        ("sentinel-incidents",
         os.path.join(ctx["here"], "data", "sentinel",
                      "incidents.jsonl")),
        ("zeus-audit", os.path.join(ctx["here"], "zeus", "data",
                                    "audit.jsonl")),
        ("artemis-hunt", ctx["ledger_path"]),
    ]
    findings = []
    try:
        from buskit import envelope as env_mod
    except Exception:                # noqa: BLE001
        return findings
    for name, path in targets:
        if not os.path.isfile(path):
            continue
        try:
            bad = list(env_mod.iter_lint(path))
        except Exception as exc:     # noqa: BLE001
            bad = [(0, [f"unreadable: {exc}"])]
        if bad:
            head = "; ".join(f"line {no}: {'/'.join(v)}"
                             for no, v in bad[:3])
            findings.append({
                "signature": "ledger-corruption", "target": name,
                "detail": f"{len(bad)} bad line(s) - append-only, "
                          f"never rewritten: {head}",
                "severity": "T2", "repairable": False})
    return findings


def hunt_compile_breaks(ctx):
    """Byte-compile every registered python entrypoint."""
    findings = []
    scratch = os.path.join(tempfile.gettempdir(), "artemis-pyc")
    os.makedirs(scratch, exist_ok=True)
    for realm in load_realms(ctx):
        rel = realm.get("path") or ""
        if realm.get("lang", "python") != "python":
            continue
        if not rel.endswith(".py"):
            continue
        full = os.path.join(ctx["here"], rel)
        if not os.path.isfile(full):
            continue
        tag = re.sub(r"[^A-Za-z0-9_.-]", "_", rel)
        cfile = os.path.join(scratch, tag + ".pyc")
        try:
            py_compile.compile(full, cfile=cfile, doraise=True)
        except py_compile.PyCompileError as exc:
            findings.append({
                "signature": "compile-break",
                "target": rel,
                "detail": str(exc).strip()[:400],
                "severity": "T1", "repairable": False})
    return findings


def hunt_missing_baseline(ctx):
    """ZEUS aegis integrity baseline present and fresh-ish?"""
    baseline = os.path.join(ctx["here"], BASELINE_REL)
    if os.path.isfile(baseline):
        age = time.time() - os.path.getmtime(baseline)
        if age > 30 * 86400:
            return [{"signature": "missing-baseline",
                     "target": BASELINE_REL,
                     "detail": f"baseline {int(age // 86400)} days old "
                               "- rebuild belongs to zeus aegis",
                     "severity": "T3", "repairable": False}]
        return []
    return [{"signature": "missing-baseline", "target": BASELINE_REL,
             "detail": "no integrity baseline - run zeus aegis build",
             "severity": "T2", "repairable": False}]


def hunt_tracked_artifacts(ctx):
    """Build junk (*.pyc) tracked by git - repairable."""
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "ls-files"],
            cwd=ctx["here"], capture_output=True, text=True).stdout
    except Exception as exc:         # noqa: BLE001
        return [{"signature": "tracked-artifacts", "target": "git",
                 "detail": f"ls-files failed: {exc}",
                 "severity": "T3", "repairable": False}]
    bad = [p for p in out.splitlines()
           if p.endswith(".pyc") or "__pycache__/" in p.replace("\\", "/")]
    if not bad:
        return []
    return [{"signature": "tracked-artifacts", "target": "*.pyc x"
             + str(len(bad)),
             "detail": "tracked build junk: "
                       + ", ".join(bad[:5])
                       + (" ..." if len(bad) > 5 else ""),
             "severity": "T3", "repairable": True}]


def hunt_gitignore_drift(ctx):
    """Required ignore lines missing from .gitignore - repairable."""
    gi = os.path.join(ctx["here"], ".gitignore")
    try:
        text = open(gi, encoding="utf-8").read()
    except OSError:
        text = ""
    lines = set(l.strip() for l in text.splitlines())
    missing = [l for l in REQUIRED_IGNORES if l not in lines]
    if not missing:
        return []
    return [{"signature": "gitignore-drift", "target": ".gitignore",
             "detail": "missing ignore lines: " + ", ".join(missing),
             "severity": "T3", "repairable": True}]


def hunt_stale_locks(ctx):
    """Dead O_EXCL spinlocks in the bus lock dir - repairable."""
    lockdir = os.path.join(ctx["post_root"], "locks")
    findings = []
    try:
        entries = os.listdir(lockdir)
    except OSError:
        return findings
    now = time.time()
    for name in sorted(entries):
        if not name.endswith(".lock"):
            continue
        path = os.path.join(lockdir, name)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age > LOCK_DEAD_S:
            findings.append({
                "signature": "stale-lock", "target": path,
                "detail": f"lock abandoned {int(age)}s "
                          f"(> {LOCK_DEAD_S}s)",
                "severity": "T3", "repairable": True})
    return findings


# ------------------------------------------------------------- repairs

def repair_tracked_artifacts(ctx, finding):
    count = 0
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "ls-files"],
        cwd=ctx["here"], capture_output=True, text=True).stdout
    for p in out.splitlines():
        if count >= TRACKED_REPAIR_CAP:
            break
        if p.endswith(".pyc") or "__pycache__/" in p.replace("\\", "/"):
            subprocess.run(["git", "rm", "-r", "--cached", "--quiet", p],
                           cwd=ctx["here"])
            count += 1
    return count > 0


def repair_gitignore_drift(ctx, finding):
    gi = os.path.join(ctx["here"], ".gitignore")
    missing = [l for l in REQUIRED_IGNORES
               if l not in set(x.strip() for x in
                               _read(gi).splitlines())]
    if not missing:
        return True
    with open(gi, "a", encoding="utf-8") as fh:
        fh.write("\n# --- required ignores (artemis) ---\n")
        for line in missing:
            fh.write(line + "\n")
    return True


def repair_stale_lock(ctx, finding):
    try:
        os.unlink(finding["target"])
        return True
    except OSError:
        return False


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


# --------------------------------------------------- signature registry

SIGNATURES = [
    ("stale-organ", hunt_stale_organs, None),
    ("retired-port-squatter", hunt_retired_ports, None),
    ("corrupt-letters", hunt_corrupt_letters, None),
    ("ledger-corruption", hunt_ledger_corruption, None),
    ("compile-break", hunt_compile_breaks, None),
    ("missing-baseline", hunt_missing_baseline, None),
    ("tracked-artifacts", hunt_tracked_artifacts,
     repair_tracked_artifacts),
    ("gitignore-drift", hunt_gitignore_drift, repair_gitignore_drift),
    ("stale-lock", hunt_stale_locks, repair_stale_lock),
]


# --------------------------------------------------------------- sweep

def _board(signatures=None):
    """Normalize the hunting order into 4-tuples with nymph owners.

    Default: the nymph roster claims every signature (artemis.nymphs).
    An explicit list (verify suites) keeps working, attributed '-'.
    Roster/kernel drift degrades to a flat sweep rather than blinding
    ARTEMIS - drift itself is pinned red by the verify suite.
    """
    if signatures is not None:
        return [tuple(sig) if len(sig) == 4 else ("-",
                                                  *tuple(sig))
                for sig in signatures]
    try:
        from artemis import nymphs
        return list(nymphs.dispatch(sys.modules[__name__]))
    except Exception as exc:         # noqa: BLE001 - never go blind
        log(f"roster dispatch failed ({exc}) - flat fallback")
        return [("-", name, fn, rep) for name, fn, rep in SIGNATURES]


def sweep(ctx=None, signatures=None):
    """One full hunt. Returns a summary dict; never raises."""
    ctx = make_ctx(**(ctx or {}))
    state = load_state(ctx)
    state["sweeps"] = state.get("sweeps", 0) + 1

    total = repaired = escalations = 0
    for nymph_name, sig_name, hunt_fn, repair_fn in _board(signatures):
        try:
            findings = hunt_fn(ctx)
        except Exception as exc:     # noqa: BLE001 - breaker, keep hunting
            findings = [{"signature": sig_name, "target": sig_name,
                         "detail": f"hunter crashed: {exc}",
                         "severity": "T2", "repairable": False}]
        for finding in findings:
            total += 1
            finding.setdefault("nymph", nymph_name)
            key = f"{finding['signature']}::{finding['target']}"
            rec = _rec(state, key)
            action = "observed"
            if finding.get("repairable") and repair_fn is not None:
                if _cool_down(rec):
                    action = "cooldown"
                else:
                    ok = False
                    try:
                        ok = bool(repair_fn(ctx, finding))
                    except Exception as exc:   # noqa: BLE001
                        finding["detail"] += f" (repair error: {exc})"
                    rec["attempts"] += 1
                    if ok:
                        action = "repaired"
                        repaired += 1
                        announce_repair(ctx, finding)
                    elif rec["attempts"] >= MAX_ATTEMPTS:
                        escalate(ctx, finding,
                                 f"{MAX_ATTEMPTS} failed repairs")
                        escalations += 1
                        rec["cooldown"] = COOLDOWN_SWEEPS
                        rec["attempts"] = 0
                        action = "repair-failed+escalated"
                    else:
                        action = "repair-failed"
            else:
                rec["seen"] += 1
                if rec["seen"] == ESCALATE_AFTER and \
                        not rec["escalated"]:
                    escalate(ctx, finding,
                             f"unresolved across {ESCALATE_AFTER} "
                             "sweeps")
                    escalations += 1
                    rec["escalated"] = True
                    rec["cooldown"] = COOLDOWN_SWEEPS
                    continue            # escalate() recorded it
                elif rec["escalated"]:
                    action = "watching"
                    if _cool_down(rec) and rec["cooldown"] == 0:
                        rec["escalated"] = False   # re-arm after standdown
                        rec["seen"] = 0
            record(ctx, finding, action)

    save_state(ctx, state)
    summary = {"ts": stamp(), "sweep": state["sweeps"],
               "findings": total, "repairs": repaired,
               "escalations": escalations}
    record_summary(ctx, summary)
    beat(ctx, summary)
    log("summary: {findings} finding(s), {repairs} repair(s), "
        "{escalations} escalation(s)".format(**summary))

    # bounded drill cadence: proof through DAEDELUS on demand only -
    # jail builds are minutes-scale, so patrols stay off them by default
    every = int(ctx["config"].get("drill_every_sweeps", 0) or 0)
    if every > 0 and state["sweeps"] % max(1, every) == 0:
        try:
            from artemis import nymphs as _retinue
            summary["drill"] = _retinue.drill(ctx)
        except Exception as exc:     # noqa: BLE001 - drills never bite
            log(f"drill error: {exc}")
    return summary


def record_summary(ctx, summary):
    try:
        from buskit import envelope
        env = envelope.make("incident", ORGAN, {
            "signature": "sweep-summary", "target":
            f"sweep-{summary['sweep']}",
            "detail": json.dumps(summary)[:400], "severity": "T3",
            "action": "summary"}, topic="incidents", rights="watcher")
        line = envelope.dump(env)
    except Exception:                # noqa: BLE001
        line = json.dumps({"ts": summary["ts"], "kind": "incident",
                           "from": ORGAN, "signature": "sweep-summary",
                           **summary})
    os.makedirs(os.path.dirname(ctx["ledger_path"]), exist_ok=True)
    with open(ctx["ledger_path"], "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def beat(ctx, summary=None):
    try:
        note = None
        if summary is not None:
            note = (f"sweep {summary['sweep']}: {summary['findings']} "
                    f"finding(s)")
        _post(ctx).beat(ORGAN, note=note)
    except Exception:                # noqa: BLE001 - bus may be dark
        pass


def list_signatures():
    """(owner_nymph, signature, mode) - '-' when the roster is dark."""
    try:
        from artemis import nymphs
        owners = nymphs.coverage()
    except Exception:                # noqa: BLE001 - listing must live
        owners = {}
    return [(owners.get(name, "-"), name,
             "repair" if rep else "report")
            for name, fn, rep in SIGNATURES]
