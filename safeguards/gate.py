"""SAFEGUARDS gate - parallel verify-suite orchestration.

One command runs every discoverable verify suite in the workspace,
bounded in time, and publishes the outcome:

    python safeguards/gate.py [--quick] [--full] [--suite NAME ...]
                              [--timeout S] [--json]

- auto-discovers verify_*.py at repo root and one level deep;
- runs suites in parallel (thread pool) with a hard per-suite timeout
  so one hung probe can no longer stall the whole gate;
- writes data/gates/report.json and prints a human summary;
- best-effort broadcasts each result onto the ratatosk 'gates' topic
  so organs and dashboards can subscribe;
- exit 0 only when every executed suite is green.
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

DEFAULT_TIMEOUT_S = 900.0
MAX_WORKERS = 4
RETRY_SETTLE_S = 3.0     # settle before re-running red suites
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def discover():
    """Auto-register every suite: root-level verify_*.py plus any
    verify_*.py one directory deep (templates/, sub-engines, ...).
    New suites join the gate by existing - zero registry upkeep."""
    suites = {}
    if os.path.isfile(os.path.join(HERE, "check.py")):
        suites["static"] = {
            "cmd": [PY, "-u", os.path.join(HERE, "check.py"),
                    "--all", "--strict"],
            "cwd": ROOT,
        }

    def add(key, path, cwd=None):
        key = key[7:-3] if key.startswith("verify_") else key
        suites.setdefault(key, {"cmd": [PY, "-u", path],
                                "cwd": cwd or ROOT})

    try:
        for name in sorted(os.listdir(ROOT)):
            p = os.path.join(ROOT, name)
            if name.startswith("verify_") and name.endswith(".py"):
                add(name, p)
            elif os.path.isdir(p) and not name.startswith(".") \
                    and name not in ("data", "safeguards", "__pycache__",
                                     "node_modules"):
                inner = os.path.join(p, f"verify_{name}.py")
                if os.path.isfile(inner):
                    add(name, inner)
                elif name == "gaia":
                    # node kernel: no python verifier, but its own
                    # tests must still ride the same gate
                    suites.setdefault("gaia", {
                        "cmd": ("npm install --no-save && npm test"),
                        "cwd": p, "shell": True})
                else:
                    for v in sorted(os.listdir(p)):
                        if v.startswith("verify_") and v.endswith(".py") \
                                and os.path.isfile(os.path.join(p, v)):
                            add(v, os.path.join(p, v))
    except OSError:
        pass
    return suites


def run_suite(name, spec, timeout_s):
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            spec["cmd"], cwd=spec.get("cwd", ROOT), capture_output=True,
            text=True, timeout=timeout_s,
            creationflags=CREATE_NO_WINDOW,
            shell=spec.get("shell", False))
        ok = proc.returncode == 0
        tail_src = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        ok = False
        tail_src = f"TIMEOUT after {timeout_s}s"
        if exc.stdout:
            tail_src += "\n" + str(exc.stdout)[-2000:]
    secs = round(time.monotonic() - t0, 1)
    # L030: a gate that detects failure but discards the failing output
    # turns every diagnosis into archaeology. Failed suites keep their
    # output (bounded) so the culprit check ships with the verdict.
    # Inline tails carry 10 lines (was 3) so a red verdict names the
    # failing check without opening the full artifact.
    lines = tail_src.splitlines()
    tail = "\n".join(lines[-10:])
    return {"suite": name, "ok": ok, "secs": secs, "tail": tail,
            "output": "" if ok else tail_src[-8000:]}


def _fail_detail(res):
    """The most diagnostic line a failed suite produced: prefer its own
    [FAIL] verdict, then errors/tracebacks, then the plain tail."""
    out = res.get("output") or res.get("tail") or ""
    for line in out.splitlines():
        low = line.lower()
        if "[fail]" in low or "traceback" in low:
            return line[:280]
    for line in out.splitlines():
        if "error" in line.lower() or "assert" in line.lower():
            return line[:280]
    return (res.get("tail") or "")[:160]


def publish_result(res):
    """Best-effort broadcast onto the bus - never raises."""
    try:
        sys.path.insert(0, ROOT)
        from ratatosk import publish          # noqa: deferred on purpose
        publish("gates", {"ok": res["ok"], "secs": res["secs"]},
                frm="safeguards", kind=res["suite"])
    except Exception:                         # noqa: BLE001 - observability
        pass                                  # must not affect the gates


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    quick = "--quick" in argv
    full = "--full" in argv
    timeout_s = DEFAULT_TIMEOUT_S
    if "--timeout" in argv:
        i = argv.index("--timeout")
        timeout_s = float(argv[i + 1])
        del argv[i:i + 2]
    only = []
    if "--suite" in argv:
        i = argv.index("--suite")
        only = argv[i + 1].split(",")
        del argv[i:i + 2]
    as_json = "--json" in argv

    registry = discover()
    if quick:
        keep = ("static", "ratatosk")
        registry = {k: v for k, v in registry.items() if k in keep}
    if only:
        registry = {k: v for k, v in registry.items() if k in only}

    if not as_json:
        print(f"GATES: {len(registry)} suite(s), "
              f"timeout {timeout_s:.0f}s each")
    results = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_WORKERS, max(1, len(registry)))) as pool:
        futures = {pool.submit(run_suite, n, s, timeout_s): n
                   for n, s in sorted(registry.items())}
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            results.append(res)
            publish_result(res)
            if not as_json:
                mark = "PASS" if res["ok"] else "FAIL"
                print(f"[{mark}] {res['suite']:<16} {res['secs']:>6}s "
                      + ("" if res["ok"]
                         else "| " + _fail_detail(res)))

    results.sort(key=lambda r: r["suite"])

    # One remediated retry before red (the doctor/sentinel convention):
    # back-to-back batteries on a busy box trip timing-sensitive checks
    # (worktree races, socket drills, SLO pulses) that pass in
    # isolation. Red suites settle briefly, then run once more - a fix
    # is never claimed without proof, and a real red stays red.
    red = [r for r in results if not r["ok"]]
    retried = []
    if red:
        time.sleep(RETRY_SETTLE_S)
        for r in red:
            spec = registry[r["suite"]]
            again = run_suite(r["suite"], spec, timeout_s)
            again["retried"] = True
            retried.append(again)
            publish_result(again)
            results[results.index(r)] = again

    retried_ok = sum(1 for r in retried if r["ok"])
    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "timeout_s": timeout_s,
              "passed": sum(1 for r in results if r["ok"]),
              "total": len(results),
              "retries": {"count": len(retried), "healed": retried_ok},
              "results": results}
    try:
        out_dir = os.path.join(ROOT, "data", "gates")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
    except OSError:
        pass                                  # reporting never blocks
    if as_json:
        print(json.dumps(report, indent=1))
    else:
        for r in sorted(retried, key=lambda x: x["suite"]):
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"[{mark}] {r['suite']:<16} {r['secs']:>6}s (retry) "
                  + ("" if r["ok"] else "| " + _fail_detail(r)))
        note = f", {len(retried)} retried ({retried_ok} healed)" \
            if retried else ""
        print(f"- gates: {report['passed']}/{report['total']} green{note}")
    return 0 if report["total"] and report["passed"] == report["total"] \
        else 1


if __name__ == "__main__":
    sys.exit(main())
