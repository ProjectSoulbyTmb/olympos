"""ZEUS console - local commands or a wire client to a hosted kernel.

Local:  python -m zeus.cli status|patrol|baseline|verify
Remote: python -m zeus.cli --connect [host port]
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import content


def _local_kernel():
    from kernel import Kernel
    return Kernel()


def cmd_status():
    k = _local_kernel()
    rep = k.status()
    print(f"ZEUS v{rep['version']} - ticks {rep['ticks']}, "
          f"baseline {rep['baseline_files']} files, "
          f"quarantine {rep['quarantined']}")
    for name, br in rep["breakers"].items():
        state = "TRIPPED" if br["tripped"] else "ok"
        print(f"  {name:<10} {state} (fails={br['fails']})")
    return 0


def cmd_patrol(n=1):
    k = _local_kernel()
    for _ in range(max(1, int(n))):
        rep = k.tick()
    print(f"tick {rep['tick']}: {len(rep['findings'])} finding(s), "
          f"{rep['processes']} processes visible")
    for f in rep["findings"]:
        print(f"  [{f['severity']}] {f['text']}")
    return 0


def cmd_baseline():
    k = _local_kernel()
    res = k.aegis.build()
    print(f"baseline built: {res['files']} files -> "
          f"{content.BASELINE_PATH}")
    return 0


def cmd_verify():
    k = _local_kernel()
    if not k.aegis.load() and not k.aegis.baseline:
        print("no baseline on disk - run 'python -m zeus.cli baseline' first")
        return 1
    res = k.aegis.verify()
    if res["clean"]:
        print(f"clean: {res['checked']} files match baseline")
        return 0
    for kind in ("modified", "added", "missing"):
        block = res[kind]
        if block["count"]:
            print(f"{kind}: {block['count']}")
            for p in block["paths"][:20]:
                print(f"  {p}")
    return 1


def cmd_connect(host, port):
    from sdk import ZeusClient
    client = ZeusClient(host, int(port))
    hello = client.connect()
    if hello.get("error"):
        print(f"rejected: {hello['error']}")
        return 1
    result = hello.get("result", {})
    print(f"connected to ZEUS v{result.get('version')} "
          f"(ticks {result.get('ticks')}); type help for commands")
    while True:
        try:
            line = input("zeus> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd, args = parts[0], {}
        if cmd in ("quit", "exit", "close"):
            break
        if cmd == "help":
            print("commands: status diagnose events repairs patrol "
                  "baseline_build baseline_verify procs bolt_kill "
                  "quarantine_list policy_get")
            continue
        for part in parts[1:]:
            if "=" in part:
                key, val = part.split("=", 1)
                args[key] = val
        try:
            out = getattr(client, cmd)(**args)
        except Exception as exc:             # noqa: BLE001 - console UX
            print(f"error: {exc}")
            continue
        print(out if isinstance(out, str) else _pretty(out))
    client.close()
    return 0


def _pretty(obj):
    import json
    return json.dumps(obj, indent=2, default=str)


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--connect":
        host = argv[1] if len(argv) > 1 else content.SERVER_HOST
        port = argv[2] if len(argv) > 2 else content.SERVER_PORT
        return cmd_connect(host, port)
    command = argv[0] if argv else "status"
    if command == "status":
        return cmd_status()
    if command == "patrol":
        return cmd_patrol(argv[1] if len(argv) > 1 else 1)
    if command == "baseline":
        return cmd_baseline()
    if command == "verify":
        return cmd_verify()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
