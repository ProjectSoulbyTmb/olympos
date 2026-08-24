"""FORSETI CLI: hold, inspect, or run inside the arbitration lane."""

import argparse
import json
import subprocess
import sys
import time

from .locker import LaneLock, status


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forseti")
    ap.add_argument("--name", default="push-main")
    ap.add_argument("--stale-s", type=float, default=60.0)
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("hold", help="hold the lane for N seconds")
    h.add_argument("--seconds", type=float, default=5.0)
    h.add_argument("--timeout", type=float, default=10.0,
                   help="max wait to acquire; fail fast when 0")

    s = sub.add_parser("status", help="report lane occupancy")

    r = sub.add_parser("run", help="run a command holding the lane")
    r.add_argument("command", nargs="+")

    ns = ap.parse_args(argv)

    if ns.cmd == "status":
        print(json.dumps(status(ns.name)))
        return 0

    if ns.cmd == "hold":
        lock = LaneLock(ns.name, stale_s=max(ns.stale_s,
                                             ns.seconds + 30))
        if not lock.acquire(timeout=max(0.0, ns.timeout)):
            print(json.dumps({"acquired": False,
                              "holder": status(ns.name)}))
            return 3
        print(json.dumps({"acquired": True, "name": ns.name}))
        time.sleep(ns.seconds)
        lock.release()
        return 0

    # run
    lock = LaneLock(ns.name, note=" ".join(ns.command)[:120],
                    stale_s=max(ns.stale_s, 300.0))
    if not lock.acquire(timeout=30.0):
        print(json.dumps({"error": "lane busy",
                          "holder": status(ns.name)}))
        return 3
    try:
        code = subprocess.run(ns.command).returncode
    finally:
        lock.release()
    return code


if __name__ == "__main__":
    sys.exit(main())
