"""DAEDALUS blueprint: ops-domain - L2 verbs with single-use confirms.

Batch V9 enterprise hardening. The ops verbs (quarantine/grant/
revoke/escalate/seal/doctor) are the most privileged surface in the
OS, so their law is structural, not behavioral:

  Single-use confirmation - a ConfirmToken is consumed by exactly one
  privileged action; the session layer mints a fresh token only after
  human acknowledgment (ptah re-arm convention). A spent token
  refuses by name: "confirmation required ... (re-arms)".
  Quarantine never destroys - the quarantine verb's record marks
  containment; no verb in this domain has a delete effect.
  Every action is hashed - ledger records carry action_sha256 so the
  ops trail seals like any other artifact.

Extension shape: register(executors) wires ops verbs onto APOLLO's
drop-in protocol; the token arrives via ctx minted per confirmation."""

import sys

OPS = '''"""Ops domain - privileged verbs under single-use confirmations."""

import hashlib
import json
import time

PRIVILEGED = ("quarantine", "grant", "revoke", "escalate",
              "seal", "doctor")


class ConfirmToken(object):
    """One human acknowledgment = one privileged action."""

    def __init__(self):
        self.used = False

    def spend(self):
        if self.used:
            return False
        self.used = True
        return True


class OpsLedger(object):
    def __init__(self):
        self.actions = []

    def _record(self, verb, target):
        rec = {"verb": verb, "target": str(target or ""),
               "contained": verb == "quarantine",
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        rec["action_sha256"] = hashlib.sha256(json.dumps(
            {"verb": verb, "target": rec["target"], "ts": rec["ts"]},
            sort_keys=True).encode("utf-8")).hexdigest()
        self.actions.append(rec)
        return rec


def execute_op(ledger, verb, target, token):
    if verb not in PRIVILEGED:
        return {"ok": False, "error": "unknown op %r" % verb}
    if token is None or not isinstance(token, ConfirmToken) \\
            or not token.spend():
        return {"ok": False,
                "error": "confirmation required for %r "
                         "(re-arms after every privileged action)"
                         % verb}
    rec = ledger._record(verb, target)
    return {"ok": True, "rearmed": True, "record": rec}


def register(executors):
    """APOLLO drop-in adapter: ops domain lands here. ctx carries
    the shared OpsLedger and a freshly minted ConfirmToken whenever
    the operator has just acknowledged."""

    def _op(verb):
        def handler(session, cmd, ctx):
            return execute_op(ctx.get("ops_ledger") or OpsLedger(),
                              verb, cmd.target,
                              ctx.get("confirm_token"))
        return handler

    for v in PRIVILEGED:
        executors[("ops", v)] = _op(v)
'''

GATE = '''"""Self-test gate for ops-domain (exit 0 = green)."""

import sys

from ops_domain import ConfirmToken, OpsLedger, execute_op


def main():
    led = OpsLedger()

    # unknown ops refuse before anything else
    r = execute_op(led, "delete-everything", "root", ConfirmToken())
    assert not r["ok"] and "unknown op" in r["error"], r

    # no token at all -> named refusal
    r = execute_op(led, "quarantine", "rogue.exe", None)
    assert not r["ok"] and "confirmation required" in r["error"], r

    # fresh token -> quarantine executes as CONTAINMENT
    tok = ConfirmToken()
    r = execute_op(led, "quarantine", "rogue.exe", tok)
    assert r["ok"] and r["rearmed"] and r["record"]["contained"], r
    assert len(led.actions) == 1 and led.actions[0]["action_sha256"]

    # THE RE-ARM: the same spent token refuses the next privilege
    r = execute_op(led, "grant", "editor@studio", tok)
    assert not r["ok"] and "confirmation required" in r["error"], \\
        {"r": r, "law": "one acknowledgment, one action"}

    # a fresh mint (new human ack) grants lawfully
    r = execute_op(led, "grant", "editor@studio", ConfirmToken())
    assert r["ok"] and not r["record"]["contained"], r

    # ledger is append-only and every action hashed
    assert [a["verb"] for a in led.actions] == ["quarantine",
                                                "grant"]
    assert all(len(a["action_sha256"]) == 64 for a in led.actions)

    print("ops-domain gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"ops_domain.py": OPS, "verify_opsdomain.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # spend() always true -> one token authorizes unlimited actions;
    # the re-arm refusal assertion goes red (independent breaker)
    "sticky_confirm": ("ops_domain.py",
                       'def spend(self):\n'
                       '        if self.used:\n'
                       '            return False\n'
                       '        self.used = True\n'
                       '        return True',
                       'def spend(self):\n'
                       '        return True'),
}

BLUEPRINT = {
    "description": "VOLTAGE ops-domain: single-use confirmations, "
                   "quarantine-not-destroy, hashed ops ledger",
    "files": FILES,
    "gate": [sys.executable, "verify_opsdomain.py"],
    "faults": dict(FAULTS),
}
