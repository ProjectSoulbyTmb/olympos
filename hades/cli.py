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
    python hades/cli.py artifact FILE [...]    fingerprint release artifacts
    python hades/cli.py artifact --verify      verify artifacts against manifest

Operator override authority (only the enrolled operator can use these):

    python hades/cli.py authorize --confirm    enroll/rotate THIS machine's secret
    python hades/cli.py mint --op OP [--arg k=v ...] [--ttl 600]
                                               sign one privileged op -> token
    python hades/cli.py override --token '{...}'   execute a signed token

Privileged ops:
    force-seal                        accept current tree as the new baseline
    exempt  path=REL reason=...       accept a deviation; verify stays green
    unexempt path=                    revoke an exemption
    unseal                            retire seal state (backed up)
    rotate-key                        new signing key + immediate re-seal
    raw     call=<method> args={json} uncensored grammar: any public kernel
                                      method, arbitrary arguments

Exit codes: 0 clean, 1 violations/hits, 2 error, 3 DENIED (authority).
"""

import argparse
import json
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hades import authority
from hades.kernel import ROOT, Hades, HadesError, TamperError


DENIED = 3                                  # authority refusal exit code


def _print_report(rep):
    print("seal: %s (%d files)" % (rep.get("sealed_at"), rep["files"]))
    for v in rep["violations"]:
        print("  [%s] %s" % (v["kind"], v["path"]))
    for v in rep.get("exempted", []):
        print("  [exempt/%s] %s - %s" % (v["kind"], v["path"],
                                         v.get("reason", "")))
    if not rep["violations"]:
        print("  all sealed assets intact")
    print("status: %s (%d violation(s), %d exempted)"
          % (rep["status"], len(rep["violations"]),
             len(rep.get("exempted", []))))


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


# ---------------- operator override authority ----------------

def cmd_authorize(args):
    if not args.confirm:
        print("refusing to change operator authority without --confirm")
        return 2
    fp = authority.enroll()
    authority.write_fingerprint(_hades(args).state_dir, fp)
    print("operator secret: %s" % authority.secret_path())
    print("fingerprint    : %s" % fp["fingerprint"])
    print("enrolled       : %s (policy %d)" % (fp["enrolled_at"],
                                               fp["policy"]))
    print("back that file up - it IS the override identity on this machine.")
    return 0


def cmd_mint(args):
    op_args = {}
    for kv in (args.arg or []):
        if "=" not in kv:
            print("bad --arg (want k=v): %s" % kv, file=sys.stderr)
            return 2
        k, v = kv.split("=", 1)
        op_args[k] = v
    if args.args_json:
        try:
            op_args.update(json.loads(args.args_json))
        except ValueError as e:
            print("bad --args-json: %s" % e, file=sys.stderr)
            return 2
    try:
        tok = authority.mint(args.op, op_args, ttl_s=args.ttl)
    except authority.AuthorityError as e:
        print("DENIED: %s" % e, file=sys.stderr)
        return DENIED
    print(json.dumps(tok, sort_keys=True))
    return 0


def _exec_override(h, token):
    """Verify + dispatch one signed token. Returns process exit code."""
    try:
        tok = json.loads(token)
    except (ValueError, TypeError) as e:
        h.audit.append({"kind": "override", "ok": False,
                        "reason": "malformed token (%s)" % e})
        print("DENIED: malformed token", file=sys.stderr)
        return DENIED
    try:
        tok = authority.verify_token(h.state_dir, tok)
    except authority.AuthorityError as e:
        h.audit.append({"kind": "override",
                        "op": str(tok.get("op", "?"))
                        if isinstance(tok, dict) else "?",
                        "ok": False, "reason": str(e)[:120]})
        print("DENIED: %s" % e, file=sys.stderr)
        return DENIED
    op, a = tok["op"], tok["args"]
    h.audit.append({"kind": "override", "op": op, "ok": True})
    if op == "force-seal":
        counts = h.seal()
        print("force-seal ok: %s" % json.dumps(counts, sort_keys=True))
        return 0
    if op == "exempt":
        info = h.grant_exemption(a.get("path", ""), a.get("reason", ""))
        print("exempt %s (%s)" % (a.get("path"), info["granted"]))
        return 0
    if op == "unexempt":
        print("unexempt %s: %s" % (a.get("path"),
                                   h.revoke_exemption(a.get("path", ""))))
        return 0
    if op == "unseal":
        print("unseal moved: %s" % h.unseal())
        return 0
    if op == "rotate-key":
        counts = h.rotate_seal_key()
        print("key rotated; re-sealed %d file(s)" % sum(counts.values()))
        return 0
    if op == "raw":
        try:
            out = authority.raw_call(h, str(a.get("call", "")),
                                     a.get("args") or {})
        except authority.AuthorityError as e:
            print("DENIED: %s" % e, file=sys.stderr)
            return DENIED
        except TypeError as e:
            print("error: bad arguments for %s: %s"
                  % (a.get("call"), e), file=sys.stderr)
            return 2
        print(json.dumps(out, indent=1, sort_keys=True, default=str))
        return 0
    print("unknown op %r" % op, file=sys.stderr)
    return 2


def cmd_override(args):
    h = _hades(args)
    token = args.token
    if token and os.path.exists(token):
        with open(token, "r", encoding="utf-8") as f:
            token = f.read()
    return _exec_override(h, token or "")


def cmd_artifact(args):
    from hades.artifacts import seal_artifacts, verify_artifacts, export_manifest
    if args.verify:
        ok, report = verify_artifacts(args.manifest)
        if args.json:
            print(json.dumps({"ok": ok, **report}, indent=2))
        else:
            print("artifact verification: %s" % ("PASS" if ok else "FAIL"))
            for a in report.get("artifacts", []):
                status = a.get("status", "?")
                name = a.get("name", "?")
                if status == "OK":
                    print("  OK   %s" % name)
                elif status == "MISSING":
                    print("  MISS %s  (%s)" % (name, a.get("detail", "")))
                elif status == "MODIFIED":
                    print("  MOD  %s  (digest mismatch)" % name)
            if report.get("error"):
                print("  error: %s" % report["error"])
        return 0 if ok else 1
    if args.export:
        dest = export_manifest(args.manifest, args.export)
        print("exported manifest -> %s" % dest)
        return 0
    paths = args.files
    if not paths:
        print("usage: artifact FILE [FILE...] [--tag TAG] [--verify] [--export DEST]",
              file=sys.stderr)
        return 2
    manifest = seal_artifacts(paths, tag=args.tag)
    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        print("sealed %d artifact(s) for tag=%s:" %
              (len(manifest["artifacts"]), manifest["tag"]))
        for a in manifest["artifacts"]:
            print("  %s  sha256=%s  size=%d" %
                  (a["name"], a["sha256"][:16] + "...", a["size"]))
        print("manifest: hades/state/artifacts/artifact_manifest.json")
    return 0


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

    # ---- operator override authority ----
    s = sub.add_parser("authorize",
                       help="enroll/rotate THIS machine's operator secret")
    s.add_argument("--confirm", action="store_true")
    s.set_defaults(fn=cmd_authorize)

    s = sub.add_parser("mint", help="sign one privileged op -> token")
    s.add_argument("--op", required=True,
                   help="force-seal | exempt | unexempt | unseal | "
                        "rotate-key | raw")
    s.add_argument("--arg", action="append", default=None,
                   help="k=v argument (repeatable)")
    s.add_argument("--args-json", default=None,
                   help="arguments as one JSON object")
    s.add_argument("--ttl", type=int, default=600, help="token lifetime (s)")
    s.set_defaults(fn=cmd_mint)

    s = sub.add_parser("override", help="execute a signed token")
    s.add_argument("--token", required=True,
                   help="token JSON, or a path to a file holding it")
    s.set_defaults(fn=cmd_override)

    s = sub.add_parser("artifact",
                       help="fingerprint release artifacts (installers, archives)")
    s.add_argument("files", nargs="*", help="artifact file paths to seal")
    s.add_argument("--tag", default=None, help="release tag (e.g. v1.2.3)")
    s.add_argument("--verify", action="store_true",
                   help="verify artifacts against existing manifest")
    s.add_argument("--manifest", default=None,
                   help="manifest path (default: hades/state/artifacts/)")
    s.add_argument("--export", default=None,
                   help="export manifest to this path for release shipping")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(fn=cmd_artifact)

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
    except authority.AuthorityError as e:
        print("DENIED: %s" % e, file=sys.stderr)
        return DENIED


if __name__ == "__main__":
    sys.exit(main())
