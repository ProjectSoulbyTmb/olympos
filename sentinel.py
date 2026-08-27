"""Olympos Sentinel - continuous verification and automatic repair.

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


def ledger(kind, name, detail, severity=None):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    # v2: every line is a buskit envelope on the 'incidents' topic
    # (INTEGRATION.md 4.1 / acceptance A8). Legacy v1 quadruple lines
    # already on disk stay readable; verify_system lints both.
    payload = {"gate_kind": str(kind), "name": str(name),
               "detail": str(detail)[:400]}
    if severity:
        payload["severity"] = severity
    try:
        from buskit import envelope
        entry = envelope.make(
            "incident", "sentinel", payload,
            topic="incidents", rights="watcher")
        line = envelope.dump(entry)
    except Exception:                    # noqa: BLE001 - never lose an incident
        entry = {"ts": stamp(), "kind": kind, "name": name,
                 "detail": str(detail)[:400]}
        if severity:
            entry["severity"] = severity
        line = json.dumps(entry)
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------- doctor

def _registry_port_tiers():
    """{port: tier} for every realm declaring one; empty on parse
    failure so a broken manifest can never blind the probe."""
    try:
        import realms
        out = {}
        for realm in realms.all_realms():
            port = realm.get("port")
            if isinstance(port, int) and port > 0:
                out[port] = int(realm.get("tier") or 1)
        return out
    except Exception:                    # noqa: BLE001 - degrade to defaults
        return {}


def doctor():
    """Environment checks. Returns (ok, findings).

    Tier-aware (H0a): a busy T3 satellite/companion port is recorded
    informationally - a running companion is normal life, not an
    alarm. T1/T2 owned ports must still be free at rest.
    """
    findings = []

    def need(name, ok, detail="", fix=None):
        findings.append((name, bool(ok), detail, fix))
        return ok

    need("python >= 3.10", sys.version_info >= (3, 10),
         sys.version.split()[0])
    node = shutil.which("node")
    need("node (venus/thoth)", node is not None, node or "not on PATH")
    for port in sorted({43901, 43903} | set(_registry_port_tiers())):
        tier = _registry_port_tiers().get(port, 1)
        s = socketQuiet()
        busy = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        if not busy:
            need(f"port {port} free at rest", True)
        elif tier >= 3:
            need(f"port {port} (T{tier}) companion running",
                 True, "informational - satellite is alive")
        else:
            need(f"port {port} free at rest", False,
                 "in use - realm still running?")

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

def gate(name, cmd, cwd=None, env_extra=None, tier=1):
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
                "tier": tier,
                "secs": round(time.time() - t0, 1),
                "tail": f"OSError spawning {cmd[0]!r}: {exc}"}
    dt = round(time.time() - t0, 1)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-3:])
    ok = proc.returncode == 0
    return {"name": name, "ok": ok, "exit": proc.returncode,
            "tier": tier, "secs": dt, "tail": tail}


def gate_defs():
    """Every runnable gate with its exact command, cwd and env.

    Realm suites derive from realms/registry.json - the single source of
    membership (STRATEGY.md gap #3): adding a realm becomes one manifest
    entry plus its verifier, no edits here. Workspace-infrastructure gates
    stay declared below.
    """
    import realms  # repo-root package; script dir is on sys.path

    def _resolve(raw):
        parts = list(raw)
        if parts and parts[0] == "python":
            return [PY, "-u"] + parts[1:]
        if parts and parts[0] in ("npm", "npx"):
            found = shutil.which(parts[0])
            if found:
                return [found] + parts[1:]
        return parts

    defs = []
    for realm in realms.all_realms():
        raw = realm.get("verify")
        if not raw:
            continue
        cwd = os.path.join(HERE, realm["workdir"]) \
            if realm.get("workdir") else HERE
        if realm.get("lang") == "node" and \
                not os.path.exists(os.path.join(cwd, "node_modules")):
            continue  # same courtesy as the venus gate below
        tier = int(realm.get("tier") or 1)
        defs.append((f"{realm['name']} suite", _resolve(raw), cwd, None,
                     tier))

    # Workspace-infrastructure gates: blocking (tier 1). godot-template
    # is intentionally NOT duplicated here - its registry row (tier 3)
    # owns it as an informational gate since the H0a routing landed.
    defs += [
        ("buskit contract", [PY, "-u", "verify_buskit.py"], HERE, None, 1),
        ("scope guard", [PY, "-u", "verify_scope.py"], HERE, None, 1),
        ("boundary isolation", [PY, "-u", "verify_boundary.py"],
         HERE, None, 1),
        ("sindri forge", [PY, "-u", "verify_sindri.py"], HERE, None, 1),
        ("forseti arbitration", [PY, "-u", "verify_forseti.py"],
         HERE, None, 1),
        ("secrets hygiene", [PY, "-u", "verify_secrets.py"], HERE, None,
         1),
        ("coverage floor", [PY, "-u", "verify_coverage.py"], HERE, None,
         1),
        ("system seam", [PY, "-u", "verify_system.py"], HERE, None, 1),
    ]
    # Enhanced safety measures (tier 2 - important but not blocking)
    defs += [
        ("task health", [PY, "-u", "task_health.py", "--fleet", "voltage"],
         HERE, None, 2),
        ("disk watchdog", [PY, "-u", "disk_watchdog.py"], HERE, None, 2),
        ("fleet health", [PY, "-u", "fleet_health.py"], HERE, None, 2),
        ("state backup", [PY, "-u", "state_backup.py", "--verify"],
         HERE, None, 2),
    ]
    if shutil.which("node") and \
            os.path.exists(os.path.join(HERE, "assistant",
                                        "test-heart.js")):
        defs.append(("venus heart",
                     ["node", os.path.join("assistant", "test-heart.js")],
                     HERE, None, 1))
    eidovara_dir = os.path.join(HERE, "project-soul")
    if shutil.which("npm") and os.path.exists(
            os.path.join(eidovara_dir, "package.json")):
        defs.append(("eidovara suite",
                     ["npm", "test"], eidovara_dir, None, 3))
    if os.environ.get("SENTINEL_DRILL_T3"):
        # H0a dry-run drill: a guaranteed-red tier-3 gate proves
        # informational routing without touching any real suite.
        defs.append(("drill-t3 informational",
                     [PY, "-c", "import sys; sys.exit(7)"], HERE, None, 3))
    return defs


def run_gates():
    results = []
    for name, cmd, cwd, env_extra, tier in gate_defs():
        log(f"gate: {name} ...")
        res = gate(name, cmd, cwd, env_extra, tier=tier)
        results.append(res)
        if res["ok"]:
            log(f"gate: {name} -> PASS ({res['secs']}s)")
            ledger("gate", name, "pass")
        elif tier >= 3:
            log(f"gate: {name} -> FAIL (informational, T{tier}) "
                f"({res['secs']}s)")
            ledger("gate", name,
                   f"FAIL exit={res['exit']}: {res['tail'][-200:]}",
                   severity="informational")
        else:
            log(f"gate: {name} -> FAIL ({res['secs']}s)")
            ledger("gate", name,
                   f"FAIL exit={res['exit']}: {res['tail'][-200:]}")
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
    defs = {name: (cmd, cwd, env_extra, tier)
            for name, cmd, cwd, env_extra, tier in gate_defs()}
    retried = []
    for res in [r for r in results if not r["ok"]]:
        log(f"retry after remediation: {res['name']}")
        for name, fn in REMEDIATORS:
            fn()
        cmd, cwd, env_extra, tier = defs.get(
            res["name"],
            ([PY, "-u", os.path.join("zeus", "verify_zeus.py")],
             HERE, None, 1))
        retried.append(gate(res["name"], cmd, cwd, env_extra, tier=tier))
    return [r for r in results if r["ok"]] + retried


def main():
    ap = argparse.ArgumentParser(description="Olympos Sentinel")
    ap.add_argument("--watch", type=int, metavar="SECONDS")
    ap.add_argument("--doctor", action="store_true")
    ap.add_argument("--list", action="store_true")
    opts = ap.parse_args()

    if opts.list:
        for name, _cmd, _cwd, _env, tier in gate_defs():
            print(f"{name}  [T{tier} informational]"
                  if tier >= 3 else name)
        print("* gaia suite runs when node_modules is present;")
        print("* venus heart runs when node is present and "
              "assistant/ is checked out")
        return 0
    if opts.doctor:
        ok, _ = doctor()
        return 0 if ok else 2

    while True:
        remediate_all()
        results = pass_gates()
        blocking = [r for r in results if r.get("tier", 1) < 3]
        t3 = [r for r in results if r.get("tier", 1) >= 3]
        t3_red = [r["name"] for r in t3 if not r["ok"]]
        total = len(blocking)
        passed = sum(1 for r in blocking if r["ok"])
        failed = [r["name"] for r in blocking if not r["ok"]]
        log(f"summary: {passed}/{total} gates green"
            + (f" - failing: {', '.join(failed)}" if failed else ""))
        extra = ""
        if t3:
            extra += (f" | T3 informational: "
                      f"{len(t3) - len(t3_red)}/{len(t3)} green")
            if t3_red:
                extra += f" (red, non-blocking: {', '.join(t3_red)})"
        log("summary" + extra)
        ledger("summary", f"{passed}/{total}",
               ("all green" if not failed else "failing: "
                + ", ".join(failed)) + extra)
        if not opts.watch:
            return 0 if not failed else 1
        time.sleep(max(30, opts.watch))


if __name__ == "__main__":
    sys.exit(main())

