"""HERMOD CLI - feed pipeline control.

    python -m hermod ingest              # drain data/feeds/incoming
    python -m hermod status
    python -m hermod latest [source]     # newest entries
    python -m hermod watch --every 30    # self-running ingest cadence
"""

import argparse
import json
import sys
import time

from hermod.kernel import FeedRoom


def cmd_ingest(_a):
    print(json.dumps(FeedRoom().ingest(), indent=2))
    return 0


def cmd_status(_a):
    print(json.dumps(FeedRoom().status(), indent=2))
    return 0


def cmd_latest(a):
    print(json.dumps(FeedRoom().latest(source=a.source, n=a.n),
                     indent=2, default=str))
    return 0


def cmd_watch(a):
    room = FeedRoom()
    print(f"[hermod] watching {content_dir()} every {a.every}s")
    try:
        while True:
            rep = room.ingest()
            if rep["bundles"]:
                print(json.dumps(rep))
            time.sleep(a.every)
    except KeyboardInterrupt:
        return 0


def content_dir():
    from hermod import content
    return content.INBOX_DIR


def build_parser():
    p = argparse.ArgumentParser(prog="hermod", description="feed pipes")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("ingest");  s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("status");  s.set_defaults(fn=cmd_status)
    s = sub.add_parser("latest")
    s.add_argument("source", nargs="?", default=None)
    s.add_argument("-n", type=int, default=20)
    s.set_defaults(fn=cmd_latest)
    s = sub.add_parser("watch")
    s.add_argument("--every", type=float, default=30.0)
    s.set_defaults(fn=cmd_watch)
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
