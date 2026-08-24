"""Verify suite for FORSETI push-lane arbitration."""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from forseti.locker import LaneLock, status  # noqa: E402

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


def t_acquire_release():
    with tempfile.TemporaryDirectory() as tmp:
        lock = LaneLock("t1", root=tmp)
        assert lock.acquire(timeout=1) and lock.release()
        assert not os.path.exists(lock.path), "lock file leaked"
    return "clean acquire/release"


def t_mutual_exclusion():
    with tempfile.TemporaryDirectory() as tmp:
        a = LaneLock("t2", root=tmp)
        b = LaneLock("t3same", root=tmp)  # different obj, same path? no
        assert a.acquire(timeout=1)
        other = LaneLock("t2", root=tmp)
        got = other.acquire(timeout=0.3)
        assert not got, "second holder broke exclusion"
        assert a.release()
        assert other.acquire(timeout=1) and other.release()
    return "exclusion + handoff"


def t_stale_takeover():
    with tempfile.TemporaryDirectory() as tmp:
        lock = LaneLock("t4", root=tmp, stale_s=5.0)
        os.makedirs(os.path.dirname(lock.path), exist_ok=True)
        with open(lock.path, "w", encoding="utf-8") as fh:
            fh.write('{"pid": 999999, "ts": "old"}')
        old = time.time() - 120
        os.utime(lock.path, (old, old))  # stale it
        assert lock.acquire(timeout=1), "stale lock not reclaimed"
        assert lock.release()
    return "crashed holder reclaimed"


def t_live_holder_reported():
    with tempfile.TemporaryDirectory() as tmp:
        a = LaneLock("t5", root=tmp)
        a.acquire(timeout=1)
        st = status("t5", root=tmp)
        assert not st["free"] and st["pid"] == os.getpid(), st
        a.release()
        assert status("t5", root=tmp)["free"]
    return "status reflects occupancy"


def t_cli_hold_blocks_other():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, RATATOSK_ROOT=os.path.join(tmp, "post"))
        holder = subprocess.Popen(
            [PY, "-u", "-m", "forseti", "--stale-s", "120", "hold",
             "--seconds", "4"],
            cwd=HERE, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        time.sleep(0)  # deterministic handshake below
        line = holder.stdout.readline()  # waits for {"acquired": true}
        assert json.loads(line).get("acquired") is True, \
            f"holder failed to take lane: {line!r}"
        blocked = subprocess.run(
            [PY, "-m", "forseti", "--stale-s", "120", "hold",
             "--seconds", "0.2", "--timeout", "0.3"],
            cwd=HERE, env=env, capture_output=True, text=True)
        out = json.loads(blocked.stdout or "{}")
        assert blocked.returncode == 3 and out.get("acquired") is False, \
            f"lane should be busy: {blocked.stdout!r}"
        holder.wait(10)
        free = subprocess.run(
            [PY, "-m", "forseti", "status"],
            cwd=HERE, env=env, capture_output=True, text=True)
        assert json.loads(free.stdout)["free"], free.stdout
    return "cross-process exclusion via CLI"


def main():
    print("verify_forseti")
    check("acquire/release cycle", t_acquire_release)
    check("mutual exclusion + handoff", t_mutual_exclusion)
    check("stale takeover", t_stale_takeover)
    check("live holder reported", t_live_holder_reported)
    check("CLI cross-process exclusion", t_cli_hold_blocks_other)
    failed = [n for ok, n in RESULTS if not ok]
    print(f"forseti: {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          "checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
