"""DAEDALUS CLI - commission builds and steer the planning station.

    python -m daedalus blueprints
    python -m daedalus build --blueprint jsonl-echo --name web1
    python -m daedalus build --blueprint jsonl-echo --fault drop_echo
    python -m daedalus status

Planning station:

    python -m daedalus plan submit --file brief.json
    python -m daedalus plan list [--status approved]
    python -m daedalus plan show --id plan-<slug>-<hex>
    python -m daedalus plan approve --id <pid> --who operator --how "session"
    python -m daedalus plan approve --id <pid> --who op --how session --commission
    python -m daedalus plan reject --id <pid> --reason "obsolete"
    python -m daedalus plan step-done --id <pid> --index 2 --note "docs green"

Fleet shape:

    python -m daedalus fleet resize --lanes 12
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


# ------------------------------------------------------- planning --

def _load_plan_doc(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_plan_submit(a):
    from daedalus.blueprints import blueprint_names
    ws = Workshop()
    doc = _load_plan_doc(a.file)
    plan = ws.plans.submit(doc, known_blueprints=blueprint_names())
    print(json.dumps(plan, indent=2, default=str))
    return 0


def cmd_plan_list(a):
    ws = Workshop()
    rows = ws.plans.list(status=a.status)
    print(json.dumps(rows, indent=2, default=str))
    return 0


def cmd_plan_show(a):
    ws = Workshop()
    print(json.dumps(ws.plans.show(a.plan_id), indent=2, default=str))
    return 0


def cmd_plan_approve(a):
    ws = Workshop()
    sign_off = {"who": a.who, "how": a.how}
    if a.commission:
        ws.plans.approve(a.plan_id, sign_off)
        out = ws.plans.commission(a.plan_id)
    else:
        out = {"approved": ws.plans.approve(a.plan_id, sign_off)}
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_plan_reject(a):
    ws = Workshop()
    print(json.dumps(
        {"rejected": ws.plans.reject(a.plan_id, a.reason)},
        indent=2, default=str))
    return 0


def cmd_plan_step_done(a):
    ws = Workshop()
    plan = ws.plans.step_done(a.plan_id, a.index, note=a.note or "")
    print(json.dumps(plan, indent=2, default=str))
    return 0 if plan["status"] != "quarantined" else 1


# ---------------------------------------------------------- fleet --

def cmd_fleet_resize(a):
    ws = Workshop()
    report = ws.fleet.resize(a.lanes)
    report["lanes"] = len(ws.fleet.lanes)
    print(json.dumps(report, indent=2, default=str))
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

    ps = sub.add_parser("plan", help="planning station")
    psub = ps.add_subparsers(dest="sub")

    q = psub.add_parser("submit"); q.add_argument("--file", required=True)
    q.set_defaults(fn=cmd_plan_submit)
    q = psub.add_parser("list")
    q.add_argument("--status", default=None,
                   choices=["draft", "approved", "commissioned",
                            "done", "rejected", "quarantined"])
    q.set_defaults(fn=cmd_plan_list)
    q = psub.add_parser("show")
    q.add_argument("--id", dest="plan_id", required=True)
    q.set_defaults(fn=cmd_plan_show)
    q = psub.add_parser("approve")
    q.add_argument("--id", dest="plan_id", required=True)
    q.add_argument("--who", required=True)
    q.add_argument("--how", required=True)
    q.add_argument("--commission", action="store_true",
                   help="also hand build steps to the workshop now")
    q.set_defaults(fn=cmd_plan_approve)
    q = psub.add_parser("reject")
    q.add_argument("--id", dest="plan_id", required=True)
    q.add_argument("--reason", default="")
    q.set_defaults(fn=cmd_plan_reject)
    q = psub.add_parser("step-done")
    q.add_argument("--id", dest="plan_id", required=True)
    q.add_argument("--index", type=int, required=True)
    q.add_argument("--note", default=None)
    q.set_defaults(fn=cmd_plan_step_done)

    fs = sub.add_parser("fleet", help="fleet shape")
    fsub = fs.add_subparsers(dest="sub")
    q = fsub.add_parser("resize")
    q.add_argument("--lanes", type=int, required=True)
    q.set_defaults(fn=cmd_fleet_resize)

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
