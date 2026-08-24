"""POSEIDON CLI - command the tide.

    python -m poseidon once                 # single tide cycle
    python -m poseidon once --dry-run       # plan only, touch nothing
    python -m poseidon watch --interval 300 # the constant workflow
    python -m poseidon status               # sea state
    python -m poseidon resume               # clear quarantine
    python -m poseidon fleet start          # berth every kernel
    python -m poseidon fleet status         # subfleet table
"""

import argparse
import json
import sys

from .kernel import ROOT, TideEngine, default_interval, default_mode


def main(argv=None):
    ap = argparse.ArgumentParser(prog="poseidon")
    ap.add_argument("--mode", default=default_mode(),
                    choices=("squash", "review", "local"))
    ap.add_argument("--interval", type=float,
                    default=default_interval())
    ap.add_argument("--root", default=ROOT,
                    help="workspace root (default: this checkout)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("once")
    o.add_argument("--dry-run", action="store_true")
    w = sub.add_parser("watch")
    w.add_argument("--max-cycles", type=int, default=0)
    f = sub.add_parser("fleet")
    f.add_argument("action", choices=("start", "sync", "status"))
    f.add_argument("--only", default=None,
                   help="comma-separated kernel names")
    sub.add_parser("status")
    sub.add_parser("resume")
    ns = ap.parse_args(argv)

    eng = TideEngine(root=ns.root, mode=ns.mode, interval=ns.interval)

    if ns.cmd == "once":
        rep = eng.once(dry_run=ns.dry_run)
        print(json.dumps(rep, indent=1))
        return 1 if rep.get("verdict") == "failed" else 0

    if ns.cmd == "watch":
        try:
            return eng.watch(max_cycles=ns.max_cycles)
        except KeyboardInterrupt:
            print("tide paused (keyboard interrupt)")
            return 0

    if ns.cmd == "fleet":
        from . import fleet
        fleet.run(ns.action, eng=eng, only=ns.only)
        return 0

    if ns.cmd == "status":
        print(json.dumps(eng.status(), indent=1))
        return 0

    if ns.cmd == "resume":
        st = eng.resume()
        print("lane reopened: failures=%d quarantine cleared"
              % st["failures"])
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
