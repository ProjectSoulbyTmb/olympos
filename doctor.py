"""Yggdrasil doctor - automatic stabilization foundation.

One command that keeps continuous development safe:

    python doctor.py            # full local check + safe auto-repairs
    python doctor.py --ci       # environment-independent subset (CI)

Check phase: entrypoint syntax, component gates (ZEUS, Vulcan, Hades,
PTAH, Ratatosk), protected directories, ZEUS baseline age, owned-port
squatters, stale bytecode caches.

Repair phase: every fix is safe and idempotent - stale __pycache__
purges, missing data directories recreated, stale integrity baselines
rebuilt, then anything that failed compilation is re-verified so a fix
is never claimed without proof. Exit 0 only when nothing remains broken.
"""

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ENTRYPOINTS = [
    "doctor.py", "sentinel.py",
]
SUITES = [
    ("zeus", os.path.join("zeus", "verify_zeus.py")),
    ("vulcan", os.path.join("vulcan", "verify_vulcan.py")),
    ("hades", os.path.join("hades", "verify_hades.py")),
    ("ptah", os.path.join("ptah", "verify_ptah.py")),
    ("ratatosk", os.path.join("ratatosk", "verify_ratatosk.py")),
    ("norn", os.path.join("norn", "verify_norn.py")),
    ("hypnos", os.path.join("hypnos", "verify_hypnos.py")),
]
REQUIREMENTS_IMPORTS = {}
ENSURE_DIRS = [
    os.path.join("zeus", "data"),
    os.path.join("zeus", "data", "quarantine"),
    os.path.join("data", "post"),
]
BASELINE_MAX_AGE_S = 7 * 24 * 3600
OWNED_PORTS = [43901, 43902, 43903]
PYCACHE_SKIP = {".git", "node_modules", "dist", "release"}
REPORT_PATH = os.path.join("data", "health_report.json")
SUITE_TIMEOUT_S = 240


class Doctor:
    def __init__(self, ci=False, fix_deps=False):
        self.ci = ci
        self.fix_deps = fix_deps
        self.rows = []

    def record(self, check, status, detail=""):
        self.rows.append({"check": check, "status": status,
                          "detail": detail})

    # ---------- checks ----------

    def check_entrypoints(self):
        bad = []
        for rel in ENTRYPOINTS:
            path = os.path.join(HERE, rel)
            if not os.path.exists(path):
                bad.append(f"{rel} (missing)")
                continue
            try:
                with open(path, "rb") as fh:
                    compile(fh.read(), rel, "exec")
            except SyntaxError as exc:
                bad.append(f"{rel} (line {exc.lineno}: {exc.msg})")
        return bad

    def check_suites(self):
        failures = []
        for name, rel in SUITES:
            path = os.path.join(HERE, rel)
            if not os.path.exists(path):
                failures.append(f"{name}: gate script missing ({rel})")
                continue
            proc = subprocess.run(
                [sys.executable, path],
                capture_output=True, text=True,
                timeout=SUITE_TIMEOUT_S, cwd=HERE)
            if proc.returncode != 0:
                tail = (proc.stdout or "").strip().splitlines()[-3:]
                failures.append(f"{name}: {' | '.join(tail)}")
        return failures

    def check_requirements(self):
        missing = []
        for dist, mod in REQUIREMENTS_IMPORTS.items():
            try:
                __import__(mod)
            except ImportError:
                missing.append(dist)
        return missing

    def fix_requirements(self, missing):
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", *missing],
            capture_output=True, text=True, timeout=900)
        still = []
        for dist, mod in REQUIREMENTS_IMPORTS.items():
            if dist not in missing:
                continue
            try:
                __import__(mod)
            except ImportError:
                still.append(dist)
        return still, proc.returncode == 0

    def check_dirs(self):
        missing = [d for d in ENSURE_DIRS
                   if not os.path.isdir(os.path.join(HERE, d))]
        return missing

    def check_baseline(self):
        from zeus import content as zc
        path = zc.BASELINE_PATH
        if not os.path.exists(path):
            return None                       # never built - not an error
        try:
            with open(path, encoding="utf-8") as fh:
                built_at = json.load(fh).get("built_at") or 0
        except (OSError, ValueError):
            return -1                         # corrupt -> rebuild
        age = time.time() - float(built_at)
        return age if age > BASELINE_MAX_AGE_S else 0

    def fix_baseline(self):
        from zeus.aegis import Aegis
        result = Aegis().build()
        return result["files"]

    def check_ports(self):
        import socket
        squatters = []
        for port in OWNED_PORTS:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    squatters.append(port)
        return squatters                    # info only - who owns it matters

    def collect_pycache(self):
        found = []
        for dirpath, dirnames, _files in os.walk(HERE):
            if os.path.basename(dirpath) == "__pycache__":
                found.append(dirpath)
                dirnames[:] = []     # caches have no subdirs - stop here
                continue
            dirnames[:] = [d for d in dirnames
                           if d not in PYCACHE_SKIP]
        return found

    def purge_pycache(self):
        purged = 0
        for cache in self.collect_pycache():
            shutil.rmtree(cache, ignore_errors=True)
            purged += 1
        return purged

    # ---------- orchestration ----------

    def run(self):
        t0 = time.time()

        bad = self.check_entrypoints()
        self.record("entrypoints compile",
                    "fail" if bad else "pass",
                    f"{len(ENTRYPOINTS) - len(bad)}/{len(ENTRYPOINTS)}"
                    + (f"; bad: {', '.join(bad)}" if bad else ""))

        if not self.ci:
            caches = len(self.collect_pycache())
            if caches:
                purged = self.purge_pycache()
                recheck = self.check_entrypoints()
                self.record(
                    "stale bytecode purge",
                    "fixed" if not recheck else "fail",
                    f"{purged} __pycache__ dirs removed"
                    + ("; recompiled clean" if not recheck else
                       f"; still failing: {recheck}"))
                bad = recheck
            else:
                self.record("stale bytecode purge", "pass", "nothing stale")

        missing_dirs = self.check_dirs()
        if missing_dirs:
            for d in missing_dirs:
                os.makedirs(os.path.join(HERE, d), exist_ok=True)
            self.record("protected directories", "fixed",
                        "created: " + ", ".join(missing_dirs))
        else:
            self.record("protected directories", "pass",
                        f"{len(ENSURE_DIRS)} present")

        if not self.ci:
            age = self.check_baseline()
            if age is None:
                files = self.fix_baseline()
                self.record("zeus integrity baseline", "fixed",
                            f"built fresh: {files} files")
            elif isinstance(age, (int, float)) and age < 0:
                files = self.fix_baseline()
                self.record("zeus integrity baseline", "fixed",
                            f"corrupt baseline rebuilt: {files} files")
            elif age == 0:
                self.record("zeus integrity baseline", "pass", "fresh")
            else:
                files = self.fix_baseline()
                self.record("zeus integrity baseline", "fixed",
                            f"stale ({age / 3600:.0f}h) rebuilt: "
                            f"{files} files")

            squatters = self.check_ports()
            self.record("owned ports",
                        "warn" if squatters else "pass",
                        f"in use: {squatters}" if squatters
                        else f"{len(OWNED_PORTS)} ports clear")

        missing = self.check_requirements()
        if missing and self.fix_deps and not self.ci:
            still, ok = self.fix_requirements(missing)
            self.record("requirements", "fixed" if ok and not still
                        else "fail",
                        "installed: " + ", ".join(missing)
                        if not still else f"unresolved: {still}")
        elif missing:
            self.record("requirements", "fail",
                        "missing: " + ", ".join(missing)
                        + " (rerun with --fix-deps)")
        else:
            self.record("requirements", "pass",
                        f"{len(REQUIREMENTS_IMPORTS)} importable")

        suite_failures = self.check_suites()
        self.record("component gates",
                    "fail" if suite_failures else "pass",
                    f"{len(SUITES) - len(suite_failures)}/"
                    f"{len(SUITES)} suites green"
                    + (f"; {suite_failures}" if suite_failures else ""))

        elapsed = time.time() - t0
        fails = sum(1 for r in self.rows if r["status"] == "fail")
        fixed = sum(1 for r in self.rows if r["status"] == "fixed")
        warns = sum(1 for r in self.rows if r["status"] == "warn")
        summary = {"mode": "ci" if self.ci else "full",
                   "elapsed_s": round(elapsed, 1),
                   "fail": fails, "fixed": fixed, "warn": warns,
                   "checks": self.rows}
        try:
            os.makedirs(os.path.dirname(
                os.path.join(HERE, REPORT_PATH)), exist_ok=True)
            with open(os.path.join(HERE, REPORT_PATH), "w",
                      encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2)
        except OSError:
            pass
        return summary


def main():
    ci = "--ci" in sys.argv
    fix_deps = "--fix-deps" in sys.argv
    print("=" * 64)
    print(f"YGGDRASIL DOCTOR - {'CI subset' if ci else 'full'} mode")
    print("=" * 64)
    doc = Doctor(ci=ci, fix_deps=fix_deps)
    summary = doc.run()
    icons = {"pass": "PASS ", "fail": "FAIL ", "fixed": "FIXED",
             "warn": "WARN "}
    for row in summary["checks"]:
        print(f"  {icons[row['status']]}  {row['check']:<26}"
              f"{row['detail']}")
    print("-" * 64)
    verdict = ("STABLE" if summary["fail"] == 0 else
               f"{summary['fail']} UNRESOLVED")
    print(f"{summary['elapsed_s']}s - {summary['fixed']} auto-fixes, "
          f"{summary['warn']} warnings -> {verdict}")
    print(f"report: {REPORT_PATH}")
    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
