"""SUITE - the all-inclusive silent command sequence console.

One windowless program drives the whole estate, so operating Olympos
never means remembering an incantation list:

    python suite.py status              # full estate snapshot (JSON)
    python suite.py gates [--all]       # verify gates (default: kronos)
    python suite.py doctor              # find what is broken/stale
    python suite.py heal                # fix what doctor found
    python suite.py quiet on|off|status # park patrols / restore them
    python suite.py commission          # doctor -> heal -> gate -> confirm
    python suite.py selftest            # prove the suite itself sound

Every child spawns windowless (CREATE_NO_WINDOW); registration and
task surgery take one hidden elevation hop under this box's silent
admin-consent doctrine. Exit 0 only when every requested stage passes.
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from kronos.kernel import (        # noqa: E402
    Governor, TaskController, ram_sample, data_paths)

GOVERNOR = "Olympos KRONOS Governor"
EXPECTED_ON = ("Olympos ZEUS Guardian",
               "Olympos HYPNOS Dreamworker",
               "Olympos GAIA Pulse")
OLD_ROOT = r"C:\Users\Earth949\OneDrive\Documents\Default Project"
REGISTER_PS1 = os.path.join(ROOT, "register-kronos-task.ps1")

PS = "powershell.exe"
SILENT = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _run(argv, timeout=300):
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout, **SILENT)


def _elevate(script):
    """Run a PowerShell script through ONE hidden elevated child
    (silent admin-consent doctrine); returns its captured log."""
    import tempfile
    spath = os.path.join(tempfile.gettempdir(), "suite-elevate.ps1")
    lpath = os.path.join(tempfile.gettempdir(), "suite-elevate.log")
    with open(spath, "w", encoding="utf-8") as fh:
        fh.write(script.replace("{LOG}", lpath))
    outer = ("$log='{l}';$ps1='{p}';"
             "$inner=\"& '$ps1' *> '$log'\";"
             "Start-Process powershell -Verb RunAs "
             "-WindowStyle Hidden -Wait "
             "-ArgumentList '-NoProfile','-ExecutionPolicy',"
             "'Bypass','-Command',$inner").format(
        l=lpath.replace("'", "''"), p=spath.replace("'", "''"))
    _run([PS, "-NoProfile", "-NonInteractive", "-Command", outer],
         timeout=600)
    try:
        with open(lpath, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# ----------------------------------------------------------- snapshot

def _root_tasks():
    out = []
    proc = _run([PS, "-NoProfile", "-NonInteractive", "-Command",
                 "Get-ScheduledTask -TaskPath '\\' | ForEach-Object { "
                 "$t=$_; foreach($a in $t.Actions){ "
                 "'{0}|{1}|{2}|{3}|{4}' -f $t.TaskName,$t.State,"
                 "$a.Execute,$a.Arguments,$a.WorkingDirectory } }"],
                timeout=120)
    for line in (proc.stdout or "").splitlines():
        parts = line.split("|", 4)
        if len(parts) == 5:
            name, state, exe, args, work = parts
            stale = bool(work) and not os.path.isdir(work)
            out.append({"task": name, "state": state, "exe": exe,
                        "args": args, "workdir": work,
                        "stale_workdir": stale,
                        "dead_root": OLD_ROOT.lower() in
                        ("%s %s %s" % (exe, args, work)).lower()})
    return out


def _governor_state(ctrl):
    return ctrl.query(GOVERNOR)


# -------------------------------------------------------------- stages

def stage_status():
    ctrl = TaskController()
    tasks = _root_tasks()
    j = None
    gp = data_paths(ROOT)
    try:
        with open(gp["state"], encoding="utf-8") as fh:
            j = json.load(fh)
    except (OSError, ValueError):
        pass
    snap = {
        "ram": ram_sample(),
        "governor": _governor_state(ctrl),
        "holding_journal": j,
        "tasks": tasks,
        "stale_count": sum(1 for t in tasks
                           if t["stale_workdir"] or t["dead_root"]),
    }
    print(json.dumps(snap, indent=1))
    return True


def stage_gates(all_gates=False):
    targets = [os.path.join(ROOT, "kronos", "verify_kronos.py")]
    if all_gates:
        targets = sorted(glob.glob(os.path.join(ROOT, "verify_*.py")))
        targets.append(os.path.join(ROOT, "kronos", "verify_kronos.py"))
    passed, failed = [], []
    for path in targets:
        name = os.path.relpath(path, ROOT)
        proc = _run([sys.executable, path], timeout=900)
        tail = (proc.stdout or "").strip().splitlines()
        verdict = tail[-1] if tail else "(no output)"
        if proc.returncode == 0:
            passed.append(name)
            print("[PASS] %-34s %s" % (name, verdict))
        else:
            failed.append(name)
            print("[FAIL] %-34s %s" % (name, verdict))
    print("gates: %d passed, %d failed" % (len(passed), len(failed)))
    return not failed


def _findings():
    f = {"stale": [], "governor_missing": False}
    ctrl = TaskController()
    for t in _root_tasks():
        if (t["stale_workdir"] or t["dead_root"]) \
                and not t["task"].startswith(("OSRS", "OneDC")):
            f["stale"].append(t)
    if _governor_state(ctrl) != "Running":
        installed = _governor_state(ctrl) is not None
        f["governor_missing"] = not installed
        f["governor_down"] = installed
    return f


def stage_doctor():
    print(json.dumps(_findings(), indent=1))
    return True


def stage_heal():
    """Remap stale fleet tasks onto this home and wake the trio."""
    f = _findings()
    if not f["stale"]:
        print("heal: nothing stale")
    else:
        lines = ["$ErrorActionPreference='Continue'"]
        for t in f["stale"]:
            new = (t["workdir"] or "").replace(OLD_ROOT, ROOT)
            if not os.path.isdir(new):
                new = ROOT
            lines.append(
                "$t=Get-ScheduledTask -TaskName '%s' -ErrorAction "
                "SilentlyContinue; if($t){ foreach($a in $t.Actions){ "
                "if($a.WorkingDirectory -like '%s*'){ "
                "$a.WorkingDirectory=$a.WorkingDirectory.Replace("
                "'%s','%s') } if($a.Arguments -like '*%s*'){ "
                "$a.Arguments=$a.Arguments.Replace('%s','%s') } }; "
                "Set-ScheduledTask -TaskName '%s' -Action $t.Actions "
                "| Out-Null; 'REHOMED %s' }"
                % (t["task"], OLD_ROOT, OLD_ROOT, ROOT,
                   OLD_ROOT, OLD_ROOT, ROOT, t["task"], t["task"]))
        log = _elevate("\n".join(lines) + "\n")
        print("\n".join(x for x in log.splitlines()
                        if x.startswith(("REHOMED", "MISS"))))
    ctrl = TaskController()
    for name in EXPECTED_ON:
        if ctrl.query(name) != "Running":
            ctrl.start(name)
    time.sleep(2)
    states = {n: ctrl.query(n) for n in EXPECTED_ON}
    print(json.dumps({"expected_on": states}, indent=1))
    return all(v == "Running" for v in states.values())


def stage_quiet(mode="status"):
    """Manual patrol override, consistent with the live journal."""
    ctrl = TaskController()
    gov = Governor(controller=ctrl, root=ROOT)
    paths = data_paths(ROOT)
    running = _governor_state(ctrl) == "Running"

    if mode == "status":
        try:
            with open(paths["state"], encoding="utf-8") as fh:
                j = json.load(fh)
        except (OSError, ValueError):
            j = {}
        print(json.dumps({"governor_running": running,
                          "journal": j}, indent=1))
        return True

    if mode == "on":
        if running:
            _run([PS, "-NoProfile", "-NonInteractive", "-Command",
                  "Stop-ScheduledTask -TaskName '%s'" % GOVERNOR])
            time.sleep(1)
        row = gov.do_hold(ram_sample()["load_pct"])
        print(json.dumps(row, indent=1))
        return True

    if mode == "off":
        row = gov.do_release(ram_sample()["load_pct"])
        if _governor_state(ctrl) != "Running":
            ctrl.start(GOVERNOR)
        print(json.dumps(row, indent=1))
        return True

    print("quiet: unknown mode %r" % mode)
    return False


def stage_commission():
    print("[1/4] doctor")
    f = _findings()
    print(json.dumps(f, indent=1))
    if f["stale"]:
        print("[2/4] heal")
        if not stage_heal():
            return 1
    else:
        print("[2/4] heal - skipped, clean")
    print("[3/4] gate (kronos)")
    if not stage_gates(all_gates=False):
        print("gate red - refusing further action")
        return 1
    ctrl = TaskController()
    if _governor_state(ctrl) is None:
        log = _elevate("& '%s'" % REGISTER_PS1)
        print(log.strip().splitlines()[0] if log.strip()
              else "register attempted")
    print("[4/4] estate check")
    tasks = {t["task"]: t for t in _root_tasks()}
    ok = (_governor_state(ctrl) == "Running"
          and all(tasks.get(n, {}).get("state") == "Running"
                  for n in EXPECTED_ON)
          and not _findings()["stale"])
    print("commission: %s" % ("GREEN" if ok else "RED"))
    return 0 if ok else 1


def stage_selftest():
    """Prove the suite's own reflexes without mutating anything."""
    ok = True
    ctrl = TaskController(dry_run=True)
    if ctrl.stop("Olympos ZEUS Guardian") is not False:
        print("[FAIL] ZEUS veto inactive"); ok = False
    else:
        print("[PASS] zeus veto")
    real_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if SILENT.get("creationflags") != real_flags:
        print("[FAIL] windowless flag missing"); ok = False
    else:
        print("[PASS] windowless spawns")
    s = ram_sample()
    if not (0 <= s["load_pct"] <= 100 and s["total_bytes"] > 0):
        print("[FAIL] sampler"); ok = False
    else:
        print("[PASS] sampler (%d%% RAM)" % s["load_pct"])
    tasks = _root_tasks()
    if not tasks:
        print("[FAIL] task inventory empty"); ok = False
    else:
        print("[PASS] inventory (%d root tasks)" % len(tasks))
    print("selftest: %s" % ("GREEN" if ok else "RED"))
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(prog="suite")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    g = sub.add_parser("gates")
    g.add_argument("--all", action="store_true",
                   help="run every root verify gate (heavy)")
    sub.add_parser("doctor")
    sub.add_parser("heal")
    q = sub.add_parser("quiet")
    q.add_argument("mode", nargs="?", default="status",
                   choices=["on", "off", "status"])
    sub.add_parser("commission")
    sub.add_parser("selftest")

    ns = ap.parse_args(argv)
    cmd = ns.cmd or "status"

    if cmd == "status":
        return 0 if stage_status() else 1
    if cmd == "gates":
        return 0 if stage_gates(all_gates=ns.all) else 1
    if cmd == "doctor":
        return 0 if stage_doctor() else 1
    if cmd == "heal":
        return 0 if stage_heal() else 1
    if cmd == "quiet":
        return 0 if stage_quiet(ns.mode) else 1
    if cmd == "commission":
        return stage_commission()
    if cmd == "selftest":
        return 0 if stage_selftest() else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
