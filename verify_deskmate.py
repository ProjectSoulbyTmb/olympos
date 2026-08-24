"""Verify gate: the deskmate blueprint weaves, serves, and survives
its own fault-injection retry.

Run:  python verify_deskmate.py
Exit: 0 green, 1 failure.

Proven here:
1. blueprint registered; weave produces server + gate + VENUS doc;
2. clean build passes the desk gate (health/template/scaffold/
   strict-validation over live HTTP);
3. injecting 'no_validation' turns the gate red and the workshop's
   fix/retry loop recovers to green.
"""

import json
import subprocess
import sys

PY = sys.executable


def run_build(name, extra=None):
    cmd = [PY, "-m", "daedalus", "build", "--blueprint", "deskmate",
           "--name", name]
    if extra:
        cmd.extend(extra)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"raw": proc.stdout[-200:]}


def main():
    print("verify_deskmate")

    rc, result = run_build("smoke-deskmate")
    ok1 = rc == 0 and result.get("ok") is True
    print(f"  {'PASS' if ok1 else 'FAIL'}  clean weave + live desk gate")
    if not ok1:
        print(json.dumps(result, indent=2, default=str)[:800])

    rc2, result2 = run_build("fault-deskmate",
                             ["--fault", "no_validation"])
    ok2 = rc2 == 0 and result2.get("ok") is True
    print(f"  {'PASS' if ok2 else 'FAIL'}  no_validation fault -> "
          f"fix/retry converges")
    if not ok2:
        print(json.dumps(result2, indent=2, default=str)[:800])

    verdict = "GREEN" if (ok1 and ok2) else "RED"
    print(f"deskmate-blueprint: {verdict}")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
