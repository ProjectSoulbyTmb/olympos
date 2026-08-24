"""DAEDALUS CLI - commission builds from any shell.

    python -m daedalus blueprints
    python -m daedalus build --blueprint jsonl-echo --name web1
    python -m daedalus build --blueprint jsonl-echo --fault drop_echo
    python -m daedalus status
"""

import argparse
import json
import sys

from daedalus.kernel import Workshop


def cmd_blueprints(_a):
    from daedalus.blueprints import BLUEPRINTS
    for name, bp in sorted(BLUEPRINTS.items()):
        print(f"{name:<14} {bp['description']}")
    return 0


def cmd_build(a):
    ws = Workshop()
    spec = {"blueprint": a.blueprint, "name": a.name}
    if a.fault:
        spec["faults"] = a.fault
    if a.attempts:
        spec["attempts"] = a.attempts
    ws.submit(spec)
    r = ws.build_next()
    while r and r.get("retrying"):
        r = ws.build_next()
    print(json.dumps(r, indent=2, default=str))
    if not (r and r.get("ok")):
        return 1
    return 0


def cmd_status(_a):
    print(json.dumps(Workshop().status(), indent=2, default=str))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="daedalus", description="workshop")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("blueprints"); s.set_defaults(fn=cmd_blueprints)
    s = sub.add_parser("build")
    s.add_argument("--blueprint", required=True)
    s.add_argument("--name", default=None)
    s.add_argument("--fault", action="append", default=[])
    s.add_argument("--attempts", type=int, default=None)
    s.set_defaults(fn=cmd_build)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    return p


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    fn = getattr(args, "fn", None)
    if fn is None:
        p.print_help()
        return 2
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
