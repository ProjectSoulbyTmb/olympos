"""Yggdrasil Sentinel - continuous verification and automatic repair.

The foundational watchdog for the whole workspace. One command runs
every product gate, applies safe automatic remediations first, and
appends an incident ledger entry so drift never goes unnoticed.

Usage:
  python sentinel.py                 # remediate -> all gates -> ledger
  python sentinel.py --watch 1800    # keep watching every N seconds
  python sentinel.py --doctor        # environment checks only, no gates
  python sentinel.py --list          # show registered gates

Exit codes: 0 all green, 1 some gate failed, 2 environment broken.

Remediators are deliberately conservative - they only touch artifacts
we own: runtime locks, tracked build junk, gitignore drift. Code
changes are reported, never auto-rewritten here; each realm has its
own repair brain (Vulcan warden, Venus heart).
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LEDGER = os.path.join(HERE, "data", "sentinel", "incidents.jsonl")


def stamp():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ledger(kind, name, detail):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    entry = {"ts": stamp(), "kind": kind, "name": name,
             "detail": str(detail)[:400]}
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------- doctor

def doctor():
    """Environment checks. Returns (ok, findings)."""
    findings = []

    def need(name, ok, detail="", fix=None):
        findings.append((name, bool(ok), detail, fix))
        return ok

    need("python >= 3.10", sys.version_info >= (3, 10),
         sys.version.split()[0])
    node = shutil.which("node")
    need("node (venus/thoth)", node is not None, node or "not on PATH")
    for port in (43901,):
        s = socketQuiet()
        busy = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        need(f"port {port} free at rest", not busy,
             "in use - realm still running?" if busy else "")

    ok = all(f[1] for f in findings)
    for name, good, detail, fix in findings:
        print(f"  {'OK  ' if good else 'NEED'} {name:<28} {detail}"
              + (f"  fix: {fix}" if fix and not good else ""))
    return ok, findings


def socketQuiet():
    import socket
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM)


# ------------------------------------------------------------ remediators

def remediate_tracked_artifacts():
    """git rm --cached anything matching our artifact patterns."""
    out = subprocess.run(["git", "ls-files"], cwd=HERE,
                         capture_output=True, text=True).stdout
    bad = [p for p in out.splitlines() if p.endswith(".pyc")]
    fixed = 0
    for p in bad:
        subprocess.run(["git", "rm", "-r", "--cached", "--quiet", p],
                       cwd=HERE)
        fixed += 1
    return fixed, f"untracked {fixed} artifact file(s)"


REMEDIATORS = [
    ("tracked-artifacts", remediate_tracked_artifacts),
]


# ----------------------------------------------------------------- gates

def gate(name, cmd, cwd=None, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=cwd or HERE, capture_output=True,
                              text=True, env=env)
    except OSError as exc:
        # A missing/unspawnable executable is gate data, not a
        # sentinel crash: record it and keep the sweep alive.
        return {"name": name, "ok": False, "exit": -1,
                "secs": round(time.time() - t0, 1),
                "tail": f"OSError spawning {cmd[0]!r}: {exc}"}
    dt = round(time.time() - t0, 1)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-3:])
    ok = proc.returncode == 0
    return {"name": name, "ok": ok, "exit": proc.returncode,
            "secs": dt, "tail": tail}


def gate_defs():
    """Every runnable gate with its exact command, cwd and env."""
    defs = [
        ("zeus suite", [PY, "-u",
                        os.path.join("zeus", "verify_zeus.py")], HERE, None),
        ("vulcan suite", [PY, "-u",
                          os.path.join("vulcan", "verify_vulcan.py")],
         HERE, None),
        ("hades suite", [PY, "-u",
                         os.path.join("hades", "verify_hades.py")],
         HERE, None),
    ]
    if shutil.which("node") and \
            os.path.exists(os.path.join(HERE, "assistant",
                                        "test-heart.js")):
        defs.append(("venus heart",
                     ["node", os.path.join("assistant", "test-heart.js")],
                     HERE, None))
    return defs


def run_gates():
    results = []
    for name, cmd, cwd, env_extra in gate_defs():
        log(f"gate: {name} ...")
        res = gate(name, cmd, cwd, env_extra)
        results.append(res)
        log(f"gate: {name} -> {'PASS' if res['ok'] else 'FAIL'} "
            f"({res['secs']}s)")
        ledger("gate", name,
               "pass" if res["ok"] else f"FAIL exit={res['exit']}: "
                                        f"{res['tail'][-200:]}")
    return results


# ------------------------------------------------------------------ main

def remediate_all():
    for name, fn in REMEDIATORS:
        count, detail = fn()
        log(f"remediate: {name} -> {detail}")
        if count:
            ledger("remediate", name, detail)


def pass_gates():
    results = run_gates()
    # one remediated retry for anything red - transient drift often
    # clears once artifacts are quarantined; retries reuse the exact
    # command, cwd and env of the original gate definition.
    defs = {name: (cmd, cwd, env_extra)
            for name, cmd, cwd, env_extra in gate_defs()}
    retried = []
    for res in [r for r in results if not r["ok"]]:
        log(f"retry after remediation: {res['name']}")
        for name, fn in REMEDIATORS:
            fn()
        cmd, cwd, env_extra = defs.get(res["name"],
                                       ([PY, "-u",
                                         os.path.join("zeus",
                                                      "verify_zeus.py")],
                                        HERE, None))
        retried.append(gate(res["name"], cmd, cwd, env_extra))
    return [r for r in results if r["ok"]] + retried


def main():
    ap = argparse.ArgumentParser(description="Yggdrasil Sentinel")
    ap.add_argument("--watch", type=int, metavar="SECONDS")
    ap.add_argument("--doctor", action="store_true")
    ap.add_argument("--list", action="store_true")
    opts = ap.parse_args()

    if opts.list:
        print("\n".join(["zeus suite", "vulcan suite", "hades suite",
                         "venus heart*"]))
        print("* runs when node is present and assistant/ is checked out")
        return 0
    if opts.doctor:
        ok, _ = doctor()
        return 0 if ok else 2

    while True:
        remediate_all()
        results = pass_gates()
        total = len(results)
        passed = sum(1 for r in results if r["ok"])
        failed = [r["name"] for r in results if not r["ok"]]
        log(f"summary: {passed}/{total} gates green"
            + (f" - failing: {', '.join(failed)}" if failed else ""))
        ledger("summary", f"{passed}/{total}",
               "all green" if not failed else "failing: "
               + ", ".join(failed))
        if not opts.watch:
            return 0 if not failed else 1
        time.sleep(max(30, opts.watch))


if __name__ == "__main__":
    sys.exit(main())

