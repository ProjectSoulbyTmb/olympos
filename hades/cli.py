"""HADES command surface.

Run from the workspace root:

    python hades/cli.py status                 what does the kernel know
    python hades/cli.py seal                   fresh seal of all protected assets
    python hades/cli.py verify                 check assets against the seal
    python hades/cli.py ghosts [DIR]           hunt rebranded copies of our logic
    python hades/cli.py scan                   verify + ghost sweep (patrol mode)
    python hades/cli.py watermark FILE [...]   embed provenance into source files
    python hades/cli.py detect [PATH]          find and authenticate Hades marks
    python hades/cli.py audit [--tail N]       validate the hash-chained log
    python hades/cli.py watch --interval 300   live sentinel loop

Exit codes: 0 clean, 1 violations/hits, 2 error.
"""

import argparse
import json
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hades.kernel import ROOT, Hades, HadesError, TamperError


def _print_report(rep):
    print("seal: %s (%d files)" % (rep.get("sealed_at"), rep["files"]))
    for v in rep["violations"]:
        print("  [%s] %s" % (v["kind"], v["path"]))
    if not rep["violations"]:
        print("  all sealed assets intact")
    print("status: %s (%d violation(s))" % (rep["status"], len(rep["violations"])))


def cmd_status(args):
    st = _hades(args).status()
    print(json.dumps(st, indent=1, sort_keys=True))
    return 0 if st.get("chain_ok") else 2


def cmd_seal(args):
    counts = _hades(args).seal()
    total = sum(counts.values())
    print("sealed %d file(s):" % total)
    for name in sorted(counts):
        print("  %-12s %4d" % (name, counts[name]))
    return 0


def cmd_verify(args):
    rep = _hades(args).verify()
    if args.json:
        print(json.dumps(rep, indent=1))
    else:
        _print_report(rep)
    return 0 if not rep["violations"] else 1


def cmd_ghosts(args):
    hits = _hades(args).ghosts(args.target)
    if not hits:
        print("no ghost matches")
        return 0
    print("%d suspect file(s):" % len(hits))
    for h in hits:
        level = "HIGH" if h["high"] else "medium"
        syms = ", ".join(h["high"] or h["medium"])
        print("  [%s] %s :: %s" % (level, h["file"], syms))
        for ref in h["evidence"]:
            print("        <- %s" % ref)
    return 1


def cmd_scan(args):
    h = _hades(args)
    rep = h.verify()
    hits = h.ghosts(h.root)
    hard = [v for v in rep["violations"] if v["kind"] != "UNREGISTERED"]
    clean = not hard and not hits
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = "%s verify=%s ghosts=%d files=%d" % (
        stamp, rep["status"], len(hits), rep["files"])
    try:
        os.makedirs(os.path.dirname(h.patrol_log), exist_ok=True)
        with open(h.patrol_log, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if args.json:
        print(json.dumps({"verify": rep, "ghosts": hits}, indent=1))
    else:
        print(line)
        for v in hard:
            print("  [%s] %s" % (v["kind"], v["path"]))
        for g in hits:
            level = "HIGH" if g["high"] else "medium"
            print("  [ghost/%s] %s" % (level, g["file"]))
    print("patrol: %s" % ("clean" if clean else "attention needed"))
    return 0 if clean else 1


def cmd_watermark(args):
    h = _hades(args)
    for path in args.files:
        payload = h.watermark_file(path, kind=args.kind)
        print("watermarked %s -> %s" % (path, payload))
    return 0


def cmd_detect(args):
    recs = _hades(args).detect(args.target)
    if not recs:
        print("no provenance marks found")
        return 0
    for r in recs:
        mark = "OURS" if r["authentic"] else "foreign/forged"
        print("[%s] %s" % (mark, r["file"]))
        print("      %s" % r["payload"])
    ours = sum(1 for r in recs if r["authentic"])
    print("%d mark(s), %d authenticate as ours" % (len(recs), ours))
    return 0


def cmd_audit(args):
    h = _hades(args)
    ok, problems, count = h.audit.verify()
    print("audit chain: %s (%d events)" % ("intact" if ok else "BROKEN", count))
    for p in problems:
        print("  ! %s" % p)
    for e in h.audit.tail(args.tail):
        ev = dict(e["event"])
        body = json.dumps(ev, sort_keys=True)
        if len(body) > 110:
            body = body[:107] + "..."
        print("  #%-5d %s  %s" % (e["seq"], e["ts"], body))
    return 0 if ok else 2


def cmd_watch(args):
    h = _hades(args)
    try:                    # NORN pulse: SLO-paced scans, late-beat aware
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from norn.pulse import Pulse
    except ImportError:
        Pulse = None
    rep_cell = {}
    pulse = None
    if Pulse is not None:
        def scan():
            rep_cell["r"] = h.verify()
        pulse = Pulse(name="hades", beat_s=float(args.interval))
        pulse.add_organ("verify_scan", scan,
                        slo_max_ms=args.interval * 600.0,
                        slo_max_late=3, revive_after=2)
    print("sentinel awake - ctrl-c to stand down")
    try:
        while True:
            if pulse is None:
                rep = h.verify()
            else:
                pulse.beat()
                snap = pulse.organs["verify_scan"].snapshot()
                if snap["state"] == "quarantined":
                    print("%s  scan QUARANTINED (%s)" % (
                        time.strftime("%H:%M:%S"), snap["reason"]))
                    time.sleep(args.interval)
                    continue
                rep = rep_cell.get("r")
                if rep is None:
                    time.sleep(args.interval)
                    continue
            hard = [v for v in rep["violations"] if v["kind"] != "UNREGISTERED"]
            print("%s  files=%d  hard=%d  unreg=%d" % (
                time.strftime("%H:%M:%S"), rep["files"], len(hard),
                len(rep["violations"]) - len(hard)))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("sentinel standing down")
        return 0


def _hades(args):
    return Hades(root=args.root)


def build_parser():
    p = argparse.ArgumentParser(prog="hades", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=ROOT, help="workspace root (default: repo root)")

    sub = p.add_subparsers(dest="verb")

    s = sub.add_parser("status", help="kernel state summary")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("seal", help="seal all protected assets now")
    s.set_defaults(fn=cmd_seal)

    s = sub.add_parser("verify", help="check assets against the seal")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("ghosts", help="hunt rebranded copies of protected logic")
    s.add_argument("target", nargs="?", default=None, help="directory to sweep")
    s.set_defaults(fn=cmd_ghosts)

    s = sub.add_parser("scan", help="verify + ghost sweep; patrol entry point")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("watermark", help="embed provenance marks into files")
    s.add_argument("files", nargs="+")
    s.add_argument("--kind", default="release", help="payload kind tag")
    s.set_defaults(fn=cmd_watermark)

    s = sub.add_parser("detect", help="find and authenticate provenance marks")
    s.add_argument("target", nargs="?", default=None)
    s.set_defaults(fn=cmd_detect)

    s = sub.add_parser("audit", help="validate the hash-chained audit log")
    s.add_argument("--tail", type=int, default=10)
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("watch", help="live sentinel loop")
    s.add_argument("--interval", type=int, default=300)
    s.set_defaults(fn=cmd_watch)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        build_parser().print_help()
        return 2
    try:
        return args.fn(args)
    except TamperError as e:
        print("TAMPER: %s" % e, file=sys.stderr)
        return 2
    except HadesError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
