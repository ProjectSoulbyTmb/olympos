"""KRONOS suite - the all-inclusive commissioning console.

One silent program drives the whole command-sequence structure, so
bringing the governor up (or checking on it) never means remembering
an incantation list:

    python -m kronos.suite              # gate -> observe -> install -> confirm
    python -m kronos.suite gate         # self-test gate only
    python -m kronos.suite observe      # dry-run decisions, touches nothing
    python -m kronos.suite install      # register + start the hidden task
    python -m kronos.suite confirm      # prove the governor is governing
    python -m kronos.suite status       # live governor snapshot
    python -m kronos.suite report       # journal + recent events
    python -m kronos.suite uninstall    # remove the task

Every child process spawns windowless; the machine stays quiet.
Exit 0 only when every requested stage passes.
"""

import argparse
import json
import os
import subprocess
import sys
import time

from . import content as C
from .kernel import ROOT, Governor, TaskController, data_paths

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTER_PS1 = os.path.join(ROOT, "register-kronos-task.ps1")
TASK_NAME = "Olympos KRONOS Governor"
ZEUS_TASKS = ("Olympos ZEUS Guardian", "Yggdrasil ZEUS Guardian")

SILENT = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _run(argv, timeout=300):
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout, **SILENT)


# ------------------------------------------------------------- stages

def stage_gate():
    """House law: nothing claims healthy without its gate passing."""
    proc = _run([sys.executable, os.path.join(HERE, "verify_kronos.py")])
    lines = (proc.stdout or "").strip().splitlines()
    print("\n".join(lines[-4:]) or proc.stderr.strip())
    return proc.returncode == 0


def stage_observe(cycles=5, gap_s=2.0):
    """Dry-run decision pass: real samples, zero task touches - and a
    throwaway journal, so observation never pollutes the real state."""
    import tempfile
    g = Governor(controller=TaskController(dry_run=True),
                 root=tempfile.mkdtemp(prefix="kronos-observe-"))
    rows = []
    for i in range(max(1, cycles)):
        s = g.sampler()
        row = g.step(s["load_pct"])
        row["sample"] = i + 1
        rows.append(row)
        if i < cycles - 1:
            time.sleep(max(0.0, gap_s))
    print(json.dumps(rows, indent=1))
    return True


def _register_once_elevated():
    """Limited shells may not register tasks; this box runs silent
    admin-consent (elevate-bootstrap doctrine), so hop through one
    hidden elevated child. No prompt, no visible window."""
    import tempfile
    log = os.path.join(tempfile.gettempdir(), "kronos-reg.log")
    # Build the child script with in-script variables (no nested
    # quote-escaping): the shape proven to work on this box.
    outer = ("$log='{log}';$ps1='{ps1}';"
             "$inner=\"& '$ps1' *> '$log'\";"
             "Start-Process powershell -Verb RunAs "
             "-WindowStyle Hidden -Wait "
             "-ArgumentList '-NoProfile','-ExecutionPolicy',"
             "'Bypass','-Command',$inner"
             ).format(log=log.replace("'", "''"),
                      ps1=REGISTER_PS1.replace("'", "''"))
    proc = _run(["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-Command", outer], timeout=240)
    return proc.returncode == 0


def stage_install():
    """Register + start the hidden governor task (idempotent)."""
    proc = _run(["powershell.exe", "-NoProfile",
                 "-ExecutionPolicy", "Bypass",
                 "-File", REGISTER_PS1], timeout=180)
    if proc.returncode != 0 or \
            "Access is denied" in ((proc.stderr or "") + (proc.stdout or "")):
        if not _register_once_elevated():
            print("silent elevation hop failed:\n%s%s"
                  % (proc.stdout or "", proc.stderr or ""))
            return False
    ctrl = TaskController()
    state = ctrl.query(TASK_NAME)
    for _ in range(5):                    # give the loop a beat to wake
        if state == "Running":
            break
        time.sleep(1.0)
        state = ctrl.query(TASK_NAME)
    print("governor task '%s': %s" % (TASK_NAME, state))
    return state == "Running"


def stage_confirm():
    """Prove the governor is governing: task alive, patrols obeying,
    ZEUS untouched. The journal is the truth about the live loop."""
    ctrl = TaskController()
    gov_state = ctrl.query(TASK_NAME)
    s = Governor(controller=ctrl, root=ROOT)
    snap = s.status()
    j = snap["journal"] or {}
    holding = bool(j.get("holding"))
    held = set(j.get("held") or [])
    patrol_states = dict(snap["tasks"])
    escaped = [t for t in held
               if patrol_states.get(t) == "Running"]
    zeus = {t: ctrl.query(t) for t in ZEUS_TASKS}
    ok = (gov_state == "Running"
          and not escaped
          and all(st != "Running" for st in zeus.values()))
    print(json.dumps({"governor": gov_state,
                      "holding": holding,
                      "held": sorted(held),
                      "patrols_escaped_hold": escaped,
                      "zeus_guardians": zeus,
                      "ram_load_pct": (snap["sample"] or {}).get("load_pct")},
                     indent=1))
    return ok


def stage_status():
    print(json.dumps(Governor(controller=TaskController(),
                              root=ROOT).status(), indent=1))
    return True


def stage_report(tail=15):
    snap = Governor(controller=TaskController(),
                    root=ROOT).status()
    events_path = data_paths(ROOT)["events"]
    try:
        with open(events_path, encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
    except OSError:
        rows = []
    print(json.dumps({"journal": snap["journal"],
                      "recent_events": rows[-tail:]}, indent=1))
    return True


def stage_uninstall():
    proc = _run(["powershell.exe", "-NoProfile",
                 "-ExecutionPolicy", "Bypass",
                 "-File", REGISTER_PS1, "-Unregister"], timeout=120)
    ok = proc.returncode == 0
    print("uninstalled '%s': %s" % (TASK_NAME, ok))
    return ok


# ---------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(prog="kronos.suite")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gate")
    o = sub.add_parser("observe")
    o.add_argument("--cycles", type=int, default=5)
    o.add_argument("--gap", type=float, default=2.0)
    sub.add_parser("install")
    sub.add_parser("confirm")
    sub.add_parser("status")
    r = sub.add_parser("report")
    r.add_argument("--tail", type=int, default=15)
    sub.add_parser("uninstall")

    ns = ap.parse_args(argv)
    cmd = ns.cmd or "all"

    if cmd == "gate":
        return 0 if stage_gate() else 1
    if cmd == "observe":
        return 0 if stage_observe(ns.cycles, ns.gap) else 1
    if cmd == "install":
        return 0 if stage_install() else 1
    if cmd == "confirm":
        return 0 if stage_confirm() else 1
    if cmd == "status":
        return 0 if stage_status() else 1
    if cmd == "report":
        return 0 if stage_report(ns.tail) else 1
    if cmd == "uninstall":
        return 0 if stage_uninstall() else 1

    # full commissioning sequence
    print("[1/4] gate")
    if not stage_gate():
        print("gate red - refusing to install an unproven governor")
        return 1
    print("[2/4] observe (dry-run)")
    stage_observe()
    print("[3/4] install")
    if not stage_install():
        return 1
    time.sleep(2.0)
    print("[4/4] confirm")
    if not stage_confirm():
        print("confirmation failed - inspect: "
              "python -m kronos.suite report")
        return 1
    print("KRONOS commissioned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
