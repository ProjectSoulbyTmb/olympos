"""DAEDALUS nymph-hunter blueprint - ARTEMIS's retinue, weavable.

Each ARTEMIS nymph is proven the house way before she hunts: the
workshop weaves her self-contained worker into an ATLAS jail guest,
runs the self-test gate against a synthetic sick workspace, and the
fix-pass machinery can converge her back if she ever ships broken
(fault-injected drills). Same doctrine as every other blueprint -
a nymph that cannot prove herself in isolation does not get deployed.

FILES exports FILES + FAULTS in the blueprint_godot/deskmate shape.
"""

import sys

NYMPH_WORKER = '''"""Standalone hunt worker (DAEDALUS-woven for ARTEMIS).

Reads hunt_spec.json:
  {
    "nymph": "<name>",
    "root": "<workspace root>",
    "post_root": "<ratatosk data/post>",
    "lock_dead_s": 600,
    "corrupt_alert": 10,
    "compile": ["rel/path.py", ...]
  }

Emits one JSON finding per line on stdout; exit 0 when the sweep ran.
Deliberately stdlib-only and filesystem-bound so it stays
deterministic inside the jail.
"""

import json
import glob
import os
import py_compile
import sys
import tempfile
import time

LOCK_DEAD_S = {{LOCK_DEAD_S}}
CORRUPT_ALERT = {{CORRUPT_ALERT}}


def emit(**finding):
    print(json.dumps(finding), flush=True)


def main():
    with open("hunt_spec.json", encoding="utf-8") as fh:
        spec = json.load(fh)
    root = spec.get("root", ".")
    post = spec.get("post_root",
                    os.path.join(root, "data", "post"))
    lock_dead = int(spec.get("lock_dead_s", LOCK_DEAD_S))
    corrupt_alert = int(spec.get("corrupt_alert", CORRUPT_ALERT))

    # --- arethusa duty: dead bus locks -------------------------------
    lockdir = os.path.join(post, "locks")
    now = time.time()
    try:
        names = sorted(os.listdir(lockdir))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".lock"):
            continue
        path = os.path.join(lockdir, name)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age > lock_dead:
            emit(signature="stale-lock", target=name,
                 detail=f"lock abandoned {int(age)}s",
                 severity="T3")

    # --- arethusa duty: quarantined letter accumulation --------------
    try:
        organs = sorted(os.listdir(post))
    except OSError:
        organs = []
    for organ in organs:
        seen_dir = os.path.join(post, organ, "seen")
        if not os.path.isdir(seen_dir):
            continue
        bad = [p for p in glob.glob(os.path.join(seen_dir,
                                                 "corrupt-*"))
               if os.path.isfile(p)]
        if len(bad) >= corrupt_alert:
            emit(signature="corrupt-letters", target=organ,
                 detail=f"{len(bad)} quarantined letters",
                 severity="T2")

    # --- daphne duty: entrypoints must byte-compile -------------------
    for rel in spec.get("compile", []):
        full = os.path.normpath(os.path.join(root, rel))
        if not os.path.isfile(full):
            emit(signature="compile-missing", target=rel,
                 detail="entrypoint absent", severity="T2")
            continue
        try:
            with tempfile.TemporaryDirectory() as td:
                py_compile.compile(full,
                                   cfile=os.path.join(td, "c.pyc"),
                                   doraise=True)
        except py_compile.PyCompileError as exc:
            emit(signature="compile-break", target=rel,
                 detail=str(exc).strip()[:400], severity="T1")

    emit(signature="sweep-done", target=spec.get("nymph", "nymph"),
         detail="worker complete", severity="T3")


if __name__ == "__main__":
    sys.exit(main())
'''

NYMPH_GATE = '''"""Self-test gate for the woven nymph worker (exit 0 = pass).

Weaves a synthetic sick workspace, aims the worker at it, and pins
her three duties: dead locks found (fresh ones spared), quarantined
letters counted, broken entrypoints named with a line number.
"""

import json
import os
import subprocess
import sys
import time

ok = True


def need(cond, why):
    global ok
    if cond:
        print(f"  gate: ok - {why}")
    else:
        ok = False
        print(f"  gate: FAIL - {why}")


root = os.path.abspath("spec-root")
post = os.path.join(root, "data", "post")
lockdir = os.path.join(post, "locks")
seen_dir = os.path.join(post, "hypnos", "seen")
for d in (lockdir, seen_dir):
    os.makedirs(d, exist_ok=True)

dead_lock = os.path.join(lockdir, "res-dead.lock")
live_lock = os.path.join(lockdir, "res-live.lock")
open(dead_lock, "w").close()
open(live_lock, "w").close()
old = time.time() - 700
os.utime(dead_lock, (old, old))

for i in range(12):
    open(os.path.join(seen_dir, f"corrupt-{i}.json"), "w").close()

good_py = os.path.join(root, "good.py")
bad_py = os.path.join(root, "bad.py")
with open(good_py, "w", encoding="utf-8") as fh:
    fh.write("VALUE = 1\\n")
with open(bad_py, "w", encoding="utf-8") as fh:
    fh.write("def broken(:\\n    pass\\n")

spec = {
    "nymph": "{{NYMPH_NAME}}",
    "root": root,
    "post_root": post,
    "lock_dead_s": 600,
    "corrupt_alert": 10,
    "compile": ["good.py", "bad.py"],
}
with open("hunt_spec.json", "w", encoding="utf-8") as fh:
    json.dump(spec, fh)

proc = subprocess.run([sys.executable, "nymph_hunter.py"],
                      capture_output=True, text=True, timeout=60)
need(proc.returncode == 0, f"worker exited 0 (got {proc.returncode})")

findings = []
for ln in proc.stdout.splitlines():
    if ln.strip():
        findings.append(json.loads(ln))

kinds = {}
for f in findings:
    kinds.setdefault(f["signature"], []).append(f)

need(any(f["target"] == "res-dead.lock"
         for f in kinds.get("stale-lock", [])),
     "dead lock hunted")
need(not any(f["target"] == "res-live.lock"
             for f in kinds.get("stale-lock", [])),
     "fresh lock spared")
hyp = kinds.get("corrupt-letters", [])
need(len(hyp) == 1 and hyp[0]["target"] == "hypnos",
     "quarantined letters counted for hypnos")
brk = kinds.get("compile-break", [])
need(len(brk) == 1 and brk[0]["target"] == "bad.py"
     and "line 1" in brk[0]["detail"],
     "broken entrypoint named with line number")
need(not any(f["target"] == "good.py"
             for f in brk + kinds.get("compile-missing", [])),
     "healthy entrypoint silent")
need(any(f["signature"] == "sweep-done" for f in findings),
     "worker completed its board")

print("nymph gate green" if ok else "nymph gate red")
sys.exit(0 if ok else 1)
'''

FILES = {
    "nymph_hunter.py": NYMPH_WORKER,
    "verify_nymph.py": NYMPH_GATE,
}

FAULTS = {
    # blind to death: a worker that can no longer see an old lock
    "mute_locks": ("nymph_hunter.py",
                   "LOCK_DEAD_S = {{LOCK_DEAD_S}}",
                   "LOCK_DEAD_S = 100000000"),
    # blind to quarantine: accumulation never crosses the bar
    "mute_letters": ("nymph_hunter.py",
                     "CORRUPT_ALERT = {{CORRUPT_ALERT}}",
                     "CORRUPT_ALERT = -1"),
}

BLUEPRINT = {
    "description": "ARTEMIS nymph hunt worker "
                   "(self-proving inside the ATLAS jail)",
    "files": FILES,
    "gate": [sys.executable, "verify_nymph.py"],
    "params": {"NYMPH_NAME": "arethusa", "LOCK_DEAD_S": "600",
               "CORRUPT_ALERT": "10"},
    "faults": dict(FAULTS),
}
