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
we own: runtime locks, tracked build junk, corrupt saves, gitignore
drift. Code changes are reported, never auto-rewritten here; each
realm has its own repair brain (Vulcan warden, Minerva, Venus heart).
"""
import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LEDGER = os.path.join(HERE, "data", "sentinel", "incidents.jsonl")
JDK17 = next((os.path.join(HERE, "tools", d)
              for d in sorted(os.listdir(os.path.join(HERE, "tools")))
              if d.startswith("jdk-17")), None) \
    if os.path.isdir(os.path.join(HERE, "tools")) else None

REQUIRED_IGNORES = ["tools/", "hyperion-181/.gradle/", "hyperion-181/build/"]


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
    for mod in ("pygame", "numpy"):
        try:
            __import__(mod)
            need(f"module {mod}", True)
        except ImportError:
            need(f"module {mod}", False, "pip install -r requirements.txt",
                 fix=f"{PY} -m pip install {mod}")
    node = shutil.which("node")
    need("node (venus/thoth)", node is not None, node or "not on PATH")
    need("jdk-17 (hyperion)", JDK17 is not None,
         JDK17 or "tools/jdk-17* missing - see IMPLEMENTATION.md M0")
    gw = os.path.join(HERE, "hyperion-181", "gradlew.bat")
    need("gradle wrapper", os.path.exists(gw))
    for port in (43590, 43901):
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
    bad = [p for p in out.splitlines() if
           p.startswith(("hyperion-181/.gradle/", "hyperion-181/build/",
                         "tools/", "jdktmp/"))
           or p.endswith((".pyc", ".class"))]
    fixed = 0
    for p in bad:
        subprocess.run(["git", "rm", "-r", "--cached", "--quiet", p],
                       cwd=HERE)
        fixed += 1
    return fixed, f"untracked {fixed} artifact file(s)"


def remediate_gitignore():
    gi_path = os.path.join(HERE, ".gitignore")
    gi = open(gi_path, encoding="utf-8").read() if os.path.exists(gi_path) \
        else ""
    missing = [r for r in REQUIRED_IGNORES if r not in gi]
    if missing:
        with open(gi_path, "a", encoding="utf-8") as fh:
            fh.write("\n# sentinel: required ignores\n"
                     + "\n".join(missing) + "\n")
    return len(missing), f"restored {len(missing)} ignore pattern(s)" \
        if missing else "gitignore complete"


def remediate_corrupt_rsps_saves():
    """Quarantine unparseable player snapshots so resume stays healthy."""
    saves = os.path.join(HERE, "osrs-llm-agent", "server", "saves")
    if not os.path.isdir(saves):
        return 0, "no saves dir yet"
    quarantined = 0
    for p in glob.glob(os.path.join(saves, "*.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                json.load(fh)
        except Exception:
            os.replace(p, p + f".corrupt-{int(time.time())}")
            quarantined += 1
    return quarantined, f"quarantined {quarantined} corrupt snapshot(s)"


REMEDIATORS = [
    ("tracked-artifacts", remediate_tracked_artifacts),
    ("gitignore-drift", remediate_gitignore),
    ("corrupt-rsps-saves", remediate_corrupt_rsps_saves),
]


# ----------------------------------------------------------------- gates

def gate(name, cmd, cwd=None, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=cwd or HERE, capture_output=True,
                          text=True, env=env)
    dt = round(time.time() - t0, 1)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-3:])
    ok = proc.returncode == 0
    return {"name": name, "ok": ok, "exit": proc.returncode,
            "secs": dt, "tail": tail}


def run_gates():
    gates = [
        ("yggdrasil verify_system", [PY, "-u", "verify_system.py"],
         HERE, None),
        ("vulcan suite", [PY, "-u",
                          os.path.join("vulcan", "verify_vulcan.py")],
         HERE, None),
        ("live functional probe", [PY, "-u", "probe_live.py"], HERE, None),
    ]
    if JDK17:
        gates.append(("muspelheim gradle build",
                      ["gradlew.bat", "build", "--no-daemon"],
                      os.path.join(HERE, "hyperion-181"),
                      {"JAVA_HOME": JDK17}))
    else:
        log("muspelheim gate skipped (no jdk-17 in tools/)")
    if shutil.which("node"):
        gates.append(("venus heart",
                      ["node", os.path.join("assistant", "test-heart.js")],
                      HERE, None))
    results = []
    for name, cmd, cwd, env_extra in gates:
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
    # clears once artifacts are quarantined
    retried = []
    for res in [r for r in results if not r["ok"]]:
        log(f"retry after remediation: {res['name']}")
        for name, fn in REMEDIATORS:
            fn()
        env_extra = {"JAVA_HOME": JDK17} \
            if "muspelheim" in res["name"] and JDK17 else None
        cwd = os.path.join(HERE, "hyperion-181") \
            if "muspelheim" in res["name"] else HERE
        cmd = {"yggdrasil verify_system": [PY, "-u", "verify_system.py"],
               "vulcan suite": [PY, "-u",
                                os.path.join("vulcan",
                                             "verify_vulcan.py")],
                "live functional probe": [PY, "-u", "probe_live.py"],
                }.get(res["name"]) or \
            ["gradlew.bat", "build", "--no-daemon"]
        retried.append(gate(res["name"], cmd, cwd, env_extra))
    return [r for r in results if r["ok"]] + retried


def main():
    ap = argparse.ArgumentParser(description="Yggdrasil Sentinel")
    ap.add_argument("--watch", type=int, metavar="SECONDS")
    ap.add_argument("--doctor", action="store_true")
    ap.add_argument("--list", action="store_true")
    opts = ap.parse_args()

    if opts.list:
        print("\n".join(["yggdrasil verify_system", "vulcan suite",
                         "live functional probe",
                         "muspelheim gradle build*", "venus heart*"]))
        print("* runs when jdk-17 / node present")
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

