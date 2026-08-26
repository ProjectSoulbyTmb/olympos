"""KRONOS CLI - govern the machine's breathing room.

    python -m kronos              # governor loop (default)
    python -m kronos once         # a single evaluate cycle
    python -m kronos status       # live load, held set, task states

Flags ride after the subcommand:
    python -m kronos run --interval 15 --dry-run
    python -m kronos once --dry-run
"""

import argparse
import json
import sys

from . import content as C
from .kernel import ROOT, Governor, TaskController


def _opts(p):
    p.add_argument("--interval", type=float, default=C.SAMPLE_S,
                   help="seconds between RAM samples")
    p.add_argument("--dry-run", action="store_true",
                   help="decide and log, but touch no task")
    p.add_argument("--root", default=ROOT,
                   help="workspace root for the journal")
    p.add_argument("--max-cycles", type=int, default=0,
                   help="stop after N samples (0 = run forever)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kronos")
    sub = ap.add_subparsers(dest="cmd")
    _opts(sub.add_parser("run", help="governor loop (the default)"))
    _opts(sub.add_parser("once", help="one evaluate cycle"))
    st = sub.add_parser("status",
                        help="load + held set + task states")
    st.add_argument("--root", default=ROOT)
    st.add_argument("--dry-run", action="store_true")

    ns = ap.parse_args(argv)
    cmd = ns.cmd or "run"
    gov = Governor(
        controller=TaskController(dry_run=getattr(ns, "dry_run", False)),
        root=getattr(ns, "root", ROOT))

    if cmd == "status":
        print(json.dumps(gov.status(), indent=1))
        return 0

    if cmd == "once":
        s = gov.sampler()
        print(json.dumps(gov.step(s["load_pct"]), indent=1))
        return 0

    try:
        gov.run(interval=getattr(ns, "interval", C.SAMPLE_S),
                max_cycles=getattr(ns, "max_cycles", 0))
        return 0
    except KeyboardInterrupt:
        print("governor paused (keyboard interrupt)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
