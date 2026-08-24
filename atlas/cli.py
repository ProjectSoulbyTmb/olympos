"""ATLAS CLI - drive the hypervisor from any shell.

    python -m atlas.cli status
    python -m atlas.cli create --name build1
    python -m atlas.cli exec --name build1 -- python -c "print('hi')"
    python -m atlas.cli stop --name build1
    python -m atlas.cli purge --name build1
    python -m atlas.cli host                 # serve on 43904

Run `python -m atlas` for the hosted daemon (same as cli host).
"""

import argparse
import json
import sys

from atlas.sdk import AtlasSDK


def cmd_status(_a):
    print(json.dumps(AtlasSDK().status(), indent=2, default=str))
    return 0


def cmd_guests(_a):
    print(json.dumps(AtlasSDK().guests(), indent=2, default=str))
    return 0


def cmd_create(a):
    print(json.dumps(AtlasSDK().create(a.name)))
    return 0


def cmd_exec(a):
    print(json.dumps(AtlasSDK().exec(a.name, a.argv,
                                     timeout_s=a.timeout_s),
                     indent=2, default=str))
    return 0


def cmd_stop(a):
    print(json.dumps(AtlasSDK().stop(a.name)))
    return 0


def cmd_purge(a):
    print(json.dumps(AtlasSDK().purge(a.name)))
    return 0


def cmd_host(_a):
    from atlas.server import AtlasServer
    server = AtlasServer()
    server.start_async()
    print(f"[atlas] hosting on {server.host}:{server.port}")
    try:
        while True:
            import time as t
            t.sleep(3600)
    except KeyboardInterrupt:
        server.running = False
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="atlas", description="hypervisor")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status");  s.set_defaults(fn=cmd_status)
    s = sub.add_parser("guests");  s.set_defaults(fn=cmd_guests)
    s = sub.add_parser("create")
    s.add_argument("--name", required=True); s.set_defaults(fn=cmd_create)
    s = sub.add_parser("exec")
    s.add_argument("--name", required=True)
    s.add_argument("--timeout-s", dest="timeout_s", type=float,
                   default=None)
    s.add_argument("argv", nargs="+")
    s.set_defaults(fn=cmd_exec)
    s = sub.add_parser("stop")
    s.add_argument("--name", required=True); s.set_defaults(fn=cmd_stop)
    s = sub.add_parser("purge")
    s.add_argument("--name", required=True); s.set_defaults(fn=cmd_purge)
    s = sub.add_parser("host");    s.set_defaults(fn=cmd_host)
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
