import json
import socket
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

from olympus import config  # noqa: E402

USAGE = """olympusctl — control the Olympus Orchestrator

usage: olympusctl <command> [job]

commands:
  status              full fleet snapshot (json)
  muster              fleet roll-call with readiness verdict
  start <job>         start a stopped singleton / run oneshot now
  stop <job>          stop a singleton
  restart <job>       restart a singleton
  shutdown            graceful orchestrator shutdown
"""


def send(cmd, arg=None, timeout=30):
    s = socket.create_connection((config.CONTROL_HOST, config.CONTROL_PORT), timeout=3)
    try:
        s.settimeout(timeout)
        payload = json.dumps({"cmd": cmd, "arg": arg}) + "\n"
        s.sendall(payload.encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                break
        return json.loads(buf.decode("utf-8"))
    finally:
        s.close()


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    cmd = argv[0]
    arg = argv[1] if len(argv) > 1 else None
    try:
        resp = send(cmd, arg)
    except (ConnectionRefusedError, OSError) as e:
        print(f"orchestrator unreachable at {config.CONTROL_HOST}:{config.CONTROL_PORT}: {e}")
        print("MUSTER: 0/0 GREEN — FLEET NOT READY")
        return 2
    if not resp.get("ok"):
        print(f"error: {resp.get('error')}")
        return 1
    if cmd == "muster":
        print(resp["report"])
        return 0 if resp["ready"] else 3
    if cmd == "status":
        print(json.dumps(resp["jobs"], indent=2))
        return 0
    print(json.dumps(resp, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
