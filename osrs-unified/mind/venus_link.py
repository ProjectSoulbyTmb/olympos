"""VENUS link engine for MIND.

Venus (the desktop companion in ../assistant) can drive this suite through
the shared durable bus (runs/osrs_bus/, same transport as the Thoth relay):

    envelope: {id, at, from: "venus", type: "venus.request",
               status: "queued", payload: {action, args}}

Drain semantics mirror relay pump: `drain(..., execute=False)` previews,
`--execute` takes each request, dispatches to the matching daemon command
with stdout captured, and completes the envelope with a result record that
Venus surfaces to her user. Every action is logged via MindState; failures
complete as failed envelopes with the error text - never raise out.

Conservative by design: release/autonomic only run when the request carries
explicit consent flags (args.release / args.autonomic_ok), so a stray or
forged envelope cannot ship code.
"""
import contextlib
import io
import json
import os
import time

from mind.bus import EventBus

MAX_OUTPUT_CHARS = 800


def _tail(text, limit=MAX_OUTPUT_CHARS):
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def policy_consent(root, action):
    """Growth-Gate auto-consent: a TTL-bounded policy block published by the
    THOTH growth gate (runs/growth_policy.json) pre-consents SAFE actions
    (status/patrol/update-data/heal/net/metrics). Release/autonomic are
    never in that set - they stay human-gated. Expired policy = no consent."""
    path_ = os.path.join(root, "runs", "growth_policy.json")
    try:
        with open(path_, encoding="utf-8") as f:
            pol = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not pol.get("enabled"):
        return False
    if float(pol.get("expires", 0)) < time.time():
        return False
    return action in pol.get("actions", [])


def _run_action(root, state, action, args):
    """Dispatch one action; returns (ok, output). Never raises."""
    from mind import daemon

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            if action == "status":
                daemon.cmd_status(root, state)
            elif action == "patrol":
                daemon.cmd_patrol(root, state, loop=int(args.get("loop", 0)),
                                  llm=bool(args.get("llm")),
                                  skip_tests=False)
            elif action == "update-data":
                daemon.cmd_update_data(root, state)
            elif action == "heal":
                daemon.cmd_heal(root, state,
                                dry_run=bool(args.get("dry_run")))
            elif action == "net":
                daemon.cmd_net(root, state,
                               loop=int(args.get("loop", 0)))
            elif action == "metrics":
                daemon.cmd_metrics(root, state)
            elif action == "release":
                if not args.get("release"):
                    return False, ("refused: release needs explicit "
                                   "args.release=true in the request")
                daemon.cmd_release(root, state,
                                   level=args.get("level", "patch"),
                                   dry_run=bool(args.get("dry_run", True)))
            elif action == "autonomic":
                if not args.get("autonomic_ok"):
                    return False, ("refused: autonomic needs explicit "
                                   "args.autonomic_ok=true in the request")
                daemon.cmd_autonomic(root, state,
                                     dry_run=bool(args.get("dry_run", True)),
                                     no_release=bool(args.get("no_release")))
            else:
                return False, f"unknown action '{action}'"
        return True, _tail(buf.getvalue())
    except Exception as e:  # noqa: BLE001 - report, never propagate
        state.log("venus", "action-error", f"{action}: {e}")
        combined = buf.getvalue()
        detail = f"{e}"[:200]
        return False, _tail(combined + ("\n" + detail if detail else ""))


def drain(root, state, execute=False, bus=None,
          sources=("venus", "thoth")):
    """Process pending venus.request envelopes. Returns a summary dict.

    Sources: "venus" always; "thoth" lets the operator kernel dispatch
    repair actions (fleet incidents -> concrete sweeps) through the same
    conservative consent gates - elevated actions still require explicit
    flags inside the payload, whatever source they arrive from."""
    bus = bus or EventBus(root)
    reqs = []
    for src in sources:
        reqs += bus.pending(type_="venus.request", source=src)
    reqs.sort(key=lambda e: e.get("id", ""))
    summary = {"pending": len(reqs), "executed": 0, "results": []}
    if not execute:
        return summary
    for evt in reqs:
        payload = evt.get("payload") or {}
        action = str(payload.get("action", "")).lower()
        args = payload.get("args") or {}
        try:
            bus.take(evt["id"])
        except FileNotFoundError:
            continue
        state.log("venus", "request-start",
                  f"{evt['id']} action={action}")
        # Source-aware gate (Growth Gate): thoth-sourced requests run only
        # read-only verbs, actions pre-consented by the published policy,
        # or requests carrying explicit elevation.
        if evt.get("from") == "thoth" \
                and action not in ("status", "metrics") \
                and not policy_consent(root, action) \
                and not args.get("elevated_ok"):
            refusal = (f"refused: thoth-sourced '{action}' needs "
                       "growth-gate policy or args.elevated_ok=true")
            bus.complete(evt["id"],
                         {"ok": False, "action": action,
                          "output": refusal}, ok=False)
            state.log("venus", "refused",
                      f"{evt['id']} {action} (outside growth policy)")
            summary["executed"] += 1
            summary["results"].append({"id": evt["id"],
                                       "action": action, "ok": False})
            continue
        ok, output = _run_action(root, state, action, args)
        bus.complete(evt["id"], {"ok": ok, "action": action,
                                 "output": output}, ok=ok)
        state.log("venus", "request-done",
                  f"{evt['id']} ok={ok} chars={len(output)}")
        summary["executed"] += 1
        summary["results"].append({"id": evt["id"], "action": action,
                                   "ok": ok})
    return summary


def publish_to_venus(root, type_, payload, state=None):
    """Convenience for engines that want to notify Venus directly."""
    eid = EventBus(root).publish(type_, payload, source="mind")
    if state is not None:
        state.log("venus", "publish", f"{type_} -> {eid}")
    return eid
