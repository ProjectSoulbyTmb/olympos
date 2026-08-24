"""HYPNOS CLI - the operator's one-way glass.

    python -m hypnos status              # queue, counters, heartbeat
    python -m hypnos submit TASK.json    # drop a task letter on the pillow
    python -m hypnos log 30              # tail the audit trail
    python -m hypnos once                # single tick now
    python -m hypnos serve [--poll S]    # host the sleeper here
    python -m hypnos demo                # end-to-end proof in a scratch dir

submit accepts a JSON file (or `-` for stdin) shaped like:
    {"task": "name", "label": "...", "retry": true,
     "on_error": "stop|continue",
     "actions": [{"do": "run", "argv": ["python", "-V"]}]}
"""

import argparse
import glob
import json
import os
import sys
import time

from hypnos import content
from hypnos.kernel import Kernel


def _fmt_age(epoch):
    if not epoch:
        return "never"
    return "%ds ago" % max(0, int(time.time() - float(epoch)))


def cmd_status(_args):
    post = Kernel().post
    st = {}
    try:
        with open(content.STATE_PATH, "r", encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        pass
    hb_age = post.heartbeat_age(content.ORGAN)
    pending = len(Kernel().pending_claims())
    print("HYPNOS status")
    print("  organ        : %s v%d" % (content.ORGAN, content.VERSION))
    print("  workspace    : %s" % content.WORKSPACE)
    print("  ticks        : %s" % st.get("ticks", 0))
    print("  tasks ok/fail: %s / %s"
          % (st.get("tasks_ok", 0), st.get("tasks_failed", 0)))
    print("  retries      : %s   crash-resumes: %s"
          % (st.get("retries", 0), st.get("resumed", 0)))
    print("  pending      : %d claim(s)" % pending)
    print("  last task    : %s (%s)"
          % (st.get("last_task") or "-", _iso_or(st)))
    print("  last build   : %s" % _build_line())
    print("  heartbeat    : %s"
          % ("%ss ago" % hb_age if hb_age is not None else "never"))
    print("  audit        : %s" % content.AUDIT_PATH)
    return 0


def _iso_or(st):
    return st.get("saved_at", "?") if isinstance(st, dict) else "?"


def _build_line():
    try:
        with open(os.path.join(content.DATA_DIR, "build.json"),
                  "r", encoding="utf-8") as fh:
            b = json.load(fh)
        return "%s ok=%s at %s" % (",".join(g["name"] for g in b["gates"]),
                                   b["ok"], b["ts"])
    except (OSError, ValueError, KeyError, TypeError):
        return "no build yet"


def cmd_submit(args):
    raw = sys.stdin.read() if args.file == "-" \
        else open(args.file, "r", encoding="utf-8").read()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or \
            not isinstance(payload.get("actions"), list):
        print("error: payload must be an object with an actions list",
              file=sys.stderr)
        return 2
    kernel = Kernel()
    lid = kernel.post.send(content.ORGAN, "task", payload, frm="cli")
    print("queued letter %s for HYPNOS" % lid)
    print("it will be handled on the next tick "
          "(daemon) or run `python -m hypnos once`")
    return 0


def cmd_log(args):
    path = content.AUDIT_PATH
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        pass
    tail = lines[-args.n:]
    if not tail:
        print("(audit trail empty)")
    for line in tail:
        try:
            rec = json.loads(line)
            extra = {k: v for k, v in rec.items()
                     if k not in ("t", "ts", "tick", "kind")}
            print("%s t%-5s %-12s %s"
                  % (rec.get("ts", "?"), rec.get("tick", "?"),
                     rec.get("kind", "?"),
                     json.dumps(extra, default=str)[:220]))
        except ValueError:
            print(line[:240])
    return 0


def cmd_once(_args):
    summary = Kernel().tick()
    print(json.dumps(summary))
    return 0


def cmd_serve(args):
    poll = max(0.5, args.poll or content.POLL_SECONDS_REAL)
    kernel = Kernel()
    kernel.audit("serve-start", pid=os.getpid(), poll_s=poll)
    print("HYPNOS hosting here, poll %.1fs - ctrl-c to wake it"
          % poll)
    try:
        while True:
            kernel.tick()
            time.sleep(poll)
    except KeyboardInterrupt:
        kernel.audit("serve-stop")
        print("\nasleep.")
    return 0


def cmd_demo(_args):
    """Full loop proof: drop-in -> claim -> execute -> reply -> build."""
    marker = os.path.join("demo-marker.txt")
    task_file = os.path.join(content.DROPIN_DIR, "demo.task.json")
    os.makedirs(content.DROPIN_DIR, exist_ok=True)
    with open(task_file, "w", encoding="utf-8") as fh:
        json.dump({"task": "demo-hello", "label": "cli demo",
                   "actions": [
                       {"do": "write_file", "path": marker,
                        "text": "hypnos was here\n"},
                       {"do": "broadcast", "topic": content.TOPIC,
                        "kind": "demo", "payload": {"hi": True}},
                   ]}, fh, indent=2)
    print("drop-in written: %s" % task_file)
    summary = Kernel().tick()
    print("tick: %s" % json.dumps(summary))
    target = os.path.join(content.WORKSPACE, marker)
    print("marker exists : %s" % os.path.exists(target))
    print("audit         : python -m hypnos log 20")
    return 0


def cmd_schedules(_args):
    """Recurring duties: cadence, last fire, next due, pending state."""
    kernel = Kernel()
    pending = {os.path.basename(p)[:-5]
               for p in glob.glob(os.path.join(content.QUEUE_DIR,
                                               "*.json"))}
    print("HYPNOS recurring duties")
    if not content.SCHEDULES:
        print("  (none configured - add rows to hypnos/content.py)")
        return 0
    for spec in content.SCHEDULES:
        name = str(spec.get("name", "?"))
        every = float(spec.get("every_s", 3600))
        stamp = float(kernel._sched_stamps.get(name, 0.0))
        due = time.time() - stamp >= every
        queued = "queued" if name in pending else ""
        print("  %-28s every %-6s %s %s"
              % (name, _human(every),
                 ("due now" if due else
                  "next in %s" % _human(max(0.0, stamp + every
                                            - time.time()))),
                 queued))
    return 0


def _human(seconds):
    seconds = int(seconds)
    if seconds >= 86400:
        return "%dd" % (seconds // 86400)
    if seconds >= 3600:
        return "%dh" % (seconds // 3600)
    if seconds >= 60:
        return "%dm" % (seconds // 60)
    return "%ds" % seconds


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hypnos", description="silent task organ of Olympos")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="queue depth + counters")
    sub.add_parser("schedules",
                   help="recurring duties: cadence + next fire")
    p_submit = sub.add_parser("submit", help="queue a task letter")
    p_submit.add_argument("file", help="task JSON file, or - for stdin")
    p_log = sub.add_parser("log", help="tail the audit trail")
    p_log.add_argument("-n", type=int, default=30)
    sub.add_parser("once", help="one tick now")
    p_serve = sub.add_parser("serve", help="host the sleeper here")
    p_serve.add_argument("--poll", type=float, default=None)
    sub.add_parser("demo", help="end-to-end proof")

    args = parser.parse_args(argv)
    table = {"status": cmd_status, "submit": cmd_submit,
             "log": cmd_log, "once": cmd_once,
             "serve": cmd_serve, "demo": cmd_demo,
             "schedules": cmd_schedules}
    fn = table.get(args.cmd)
    if fn is None:
        parser.print_help()
        return 2
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
