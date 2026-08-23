import glob
import json
import os
import time


def _heal_corrupt_mind_state(root, dry_run):
    path = os.path.join(root, ".mind_state.json")
    fixed = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, json.JSONDecodeError, ValueError) as e:
        if os.path.exists(path):
            backup = path + f".bad-{int(time.time())}"
            if not dry_run:
                os.replace(path, backup)
            fixed.append(f"reset corrupt .mind_state.json (backed up as "
                         f"{os.path.basename(backup)}): {e}")
    return fixed


def _heal_missing_dirs(root, dry_run):
    fixed = []
    for rel in ("runs", os.path.join("runs", "osrs_bus", "spool"),
                os.path.join("runs", "osrs_bus", "archive"),
                os.path.join("knowledge", "live"),
                os.path.join("knowledge", "raw"),
                os.path.join("mind", "proposals")):
        path = os.path.join(root, rel)
        if not os.path.isdir(path):
            if not dry_run:
                os.makedirs(path, exist_ok=True)
            fixed.append(f"recreated missing dir {rel}")
    return fixed


def _heal_stale_tmp(root, dry_run, max_age_s=3600):
    fixed = []
    now = time.time()
    pattern = os.path.join(root, "runs", "**", "*.tmp")
    for path in glob.glob(pattern, recursive=True):
        try:
            if now - os.path.getmtime(path) > max_age_s:
                size = os.path.getsize(path)
                if not dry_run:
                    os.remove(path)
                fixed.append(f"removed stale tmp {os.path.relpath(path, root)}"
                             f" ({size}B)")
        except OSError:
            continue
    return fixed


def _heal_quarantine_sessions(root, dry_run):
    from mind import moderator
    findings = moderator.sweep_sessions(root, quarantine=not dry_run)
    return [f.message for f in findings if f.action in ("auto-fixed",)]


PLAYBOOK = [
    ("corrupt .mind_state.json", _heal_corrupt_mind_state),
    ("missing directories", _heal_missing_dirs),
    ("stale tmp files", _heal_stale_tmp),
    ("corrupt sessions", _heal_quarantine_sessions),
]


def heal(root, dry_run=False, verify=False, log=None):
    actions = []
    for name, fn in PLAYBOOK:
        try:
            got = fn(root, dry_run)
        except Exception as e:
            got = [f"playbook '{name}' errored: {type(e).__name__}: {e}"]
        actions.extend(got)
    verified = None
    if verify and not dry_run and actions:
        from mind import engineer
        result = engineer.run_tests(root, timeout=300)
        verified = {"ok": result["ok"], "ran": result["ran"]}
        if log:
            log(f"post-heal verification: ok={result['ok']} "
                f"ran={result['ran']}")
    return {"actions": actions,
            "count": len(actions),
            "dry_run": dry_run,
            "verified": verified}
