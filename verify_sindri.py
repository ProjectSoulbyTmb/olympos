"""Verify suite for the SINDRI sandboxed-execution forge."""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sindri import run  # noqa: E402

PY = sys.executable
RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name))
        print(f"  PASS  {name:<44} {detail}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name))
        print(f"  FAIL  {name:<44} {type(exc).__name__}: {exc}")


def _child(tmpdir, body):
    path = os.path.join(tmpdir, "child.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return [PY, path]


def t_normal_capture():
    with tempfile.TemporaryDirectory() as tmp:
        r = run(_child(tmp, "print('forged')"), cwd=tmp,
                seconds=10, mem_mb=128)
        assert r["exit"] == 0 and not r["timed_out"], r
        assert "forged" in r["stdout"], r
    return "stdout + exit 0"


def t_nonzero_exit():
    with tempfile.TemporaryDirectory() as tmp:
        r = run(_child(tmp, "raise SystemExit(3)"), cwd=tmp,
                seconds=10, mem_mb=128)
        assert r["exit"] == 3 and not r["timed_out"], r
    return "exit 3 propagated"


def t_wallclock_kill():
    with tempfile.TemporaryDirectory() as tmp:
        r = run(_child(tmp, "import time; time.sleep(60)"), cwd=tmp,
                seconds=1, mem_mb=128)
        assert r["timed_out"] and r["exit"] is None, r
        assert r["secs"] < 6, f"killed late: {r['secs']}s"
    return f"tree killed at {r['secs']}s"


def t_memory_fence():
    if os.environ.get("SINDRI_WIN_JOBS") != "1" and sys.platform == "win32":
        return "skipped (needs SINDRI_WIN_JOBS=1 job fence)"
    with tempfile.TemporaryDirectory() as tmp:
        body = "b = bytearray(300 * 1024 * 1024)\nprint(len(b))"
        r = run(_child(tmp, body), cwd=tmp, seconds=20, mem_mb=96)
        assert not r["timed_out"], r
        assert r["exit"] != 0, "300MB alloc survived a 96MB fence"
    return "oversized alloc denied"


def t_process_cap():
    if os.environ.get("SINDRI_WIN_JOBS") != "1" or not sys.platform == "win32":
        return "skipped (needs SINDRI_WIN_JOBS=1 job fence)"
    with tempfile.TemporaryDirectory() as tmp:
        body = (
            "import subprocess, sys\n"
            "ok = 0\n"
            "for _ in range(12):\n"
            "    try:\n"
            "        p = subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(30)'])\n"
            "        ok += 1\n"
            "    except Exception:\n"
            "        pass\n"
            "print('SPAWNED', ok)\n")
        r = run(_child(tmp, body), cwd=tmp, seconds=25,
                mem_mb=256, max_procs=3)
        assert r["exit"] == 0, r
        n = int(r["stdout"].split("SPAWNED")[1].strip() or 0)
        assert n < 12, f"process cap never engaged (spawned {n})"
        return f"spawn attempts capped at {n}/12"


def main():
    print("verify_sindri")
    check("normal run captures stdout", t_normal_capture)
    check("nonzero exit propagates", t_nonzero_exit)
    check("wall-clock tree kill", t_wallclock_kill)
    check("memory fence denies oversized alloc", t_memory_fence)
    check("process-count brake", t_process_cap)
    failed = [n for ok, n in RESULTS if not ok]
    print(f"sindri: {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          "checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
