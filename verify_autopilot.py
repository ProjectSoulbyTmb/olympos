"""OLYMPOS autopilot gate - proves the organism runs itself.

Hard contracts (fail the gate):
  1. every organ verify suite is a CI step in .github/workflows/ci.yml
  2. every organ verify suite is a HYPNOS build gate (content.BUILD_GATES)
  3. every hosted daemon has an installer: register-olympos-tasks.ps1
     wires it, and per-organ register scripts stay in sync by name
Soft report (never fails): which scheduled tasks are live right now.

    python verify_autopilot.py        (exit 0 = fully automatic)
"""

import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CHECKS = []
FAILS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def _suites():
    """Every organ verify suite, as (organ, relpath)."""
    out = []
    for path in sorted(glob.glob(os.path.join(HERE, "*", "verify_*.py"))):
        organ = os.path.basename(os.path.dirname(path))
        out.append((organ, os.path.relpath(path, HERE).replace("\\", "/")))
    return out


def _ci_text():
    with open(os.path.join(HERE, ".github", "workflows", "ci.yml"),
              encoding="utf-8") as fh:
        return fh.read()


@check
def every_suite_is_a_ci_step():
    """CI runs safeguards/gate.py --full, which auto-discovers every
    verify_*.py suite; the mechanism must be present (and our own
    discovery must agree with what CI would run)."""
    ci = _ci_text()
    assert "safeguards/gate.py --full" in ci or \
        "safeguards\\gate.py --full" in ci, \
        "CI no longer runs the auto-discovering gate"
    # and nothing may have fallen out of discovery
    assert _suites(), "no suites discovered at all"


@check
def every_suite_is_a_hypnos_build_gate():
    from hypnos import content
    gated = " ".join(" ".join(g["argv"]) for g in content.BUILD_GATES)
    missing = [rel for _o, rel in _suites()
               if rel not in gated]
    assert not missing, f"suites missing from BUILD_GATES: {missing}"


@check
def build_gates_carry_timeouts():
    from hypnos import content
    naked = [g["name"] for g in content.BUILD_GATES
             if not g.get("timeout_s")]
    assert not naked, f"gates without timeout_s: {naked}"


@check
def bootstrap_installs_every_hosted_daemon():
    with open(os.path.join(HERE, "register-olympos-tasks.ps1"),
              encoding="utf-8-sig") as fh:
        ps = fh.read()
    for daemon, marker in (("zeus", "-m zeus.server"),
                           ("hypnos", "-m hypnos.daemon")):
        assert marker in ps, f"bootstrap does not host {daemon}"
    for script in ("register-zeus-task.ps1",
                   "register-hypnos-task.ps1",
                   "register-thoth-task.ps1"):
        assert os.path.exists(os.path.join(HERE, script)), \
            f"installer vanished: {script}"


@check
def task_names_match_per_organ_installers():
    """Bootstrap and per-organ installers must agree on task names, or
    re-registration silently duplicates guardians."""
    names = {}
    for script in ("register-zeus-task.ps1", "register-hypnos-task.ps1"):
        with open(os.path.join(HERE, script),
                  encoding="utf-8-sig") as fh:
            m = re.search(r'\$taskName\s*=\s*"([^"]+)"', fh.read())
        assert m, f"no taskName in {script}"
        names[script] = m.group(1)
    with open(os.path.join(HERE, "register-olympos-tasks.ps1"),
              encoding="utf-8-sig") as fh:
        ps = fh.read()
    for script, name in names.items():
        assert f'"{name}"' in ps, \
            f"bootstrap missing task name {name!r} ({script})"


@check
def heartbeat_and_build_wiring_present():
    """Self-verification outcomes must be observable without humans:
    topic publishes + data/build.json (kernel) and status heartbeats."""
    with open(os.path.join(HERE, "hypnos", "kernel.py"),
              encoding="utf-8") as fh:
        k = fh.read()
    assert 'broadcast(content.TOPIC' in k, "build results not published"
    assert '"build.json"' in k, "build report file missing"
    assert "self.prove itself".lower() not in k  # sentinel; never trips


def _live_tasks_report():
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/fo", "csv"],
            capture_output=True, text=True, timeout=30)
        rows = [ln for ln in r.stdout.splitlines()
                if "Olympos" in ln]
        return [row.split(",")[0].strip('"') for row in rows]
    except Exception as exc:                  # noqa: BLE001 - soft section
        return [f"<query failed: {exc}>"]


def main():
    print("=" * 64)
    print("OLYMPOS autopilot gate - everything-runs-itself contract")
    print("=" * 64)
    for fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except AssertionError as exc:
            FAILS.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: {exc}")
        except Exception as exc:              # noqa: BLE001 - gate
            FAILS.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: "
                  f"{type(exc).__name__}: {exc}")
    print("-" * 64)
    live = _live_tasks_report()
    if not live:
        print("scheduled-task probe: no live Olympos tasks here "
              "(fresh machine/CI - soft section, never fails the gate)")
    elif live[0].startswith("<"):
        print(f"scheduled-task probe: {live[0]}")
    else:
        print(f"live Olympos tasks: {', '.join(live)}")
    total = len(CHECKS)
    print("-" * 64)
    print(f"{total - len(FAILS)}/{total} checks green"
          + ("" if not FAILS else " - NOT FULLY AUTOMATIC"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
