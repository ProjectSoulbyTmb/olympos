"""NORN WITNESS: append-only attestation journals (PCC model).

Every mutating verb that crosses an SDK surface is recorded with its
tick, actor, argument digest and state deltas. A journal line plus the
session seed is enough to re-run any session and compare digests:
attestation IS replay with provenance.

Journals are sidecar artifacts; they rotate like saves.
"""

import hashlib
import json
import os
import time

ROTATE_BYTES = 5 * 1024 * 1024
KEEP = 5


def args_digest(args):
    payload = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Witness:
    """Append-only JSONL journal for one session."""

    def __init__(self, log_dir, actor="session", world=None,
                 rotate_bytes=ROTATE_BYTES, keep=KEEP):
        self.actor = actor
        self.world = world
        self.rotate_bytes = rotate_bytes
        self.keep = keep
        os.makedirs(log_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(
            log_dir, f"{stamp}-{actor.replace('/', '_')}.jsonl")
        self._rotate_old()
        self.entries = 0
        self._fh = open(self.path, "a", encoding="utf-8")

    def _rotate_old(self):
        folder = os.path.dirname(self.path)
        prefix = self.actor.replace("/", "_").split("-")[0]
        olds = sorted(p for p in os.listdir(folder)
                      if p.endswith(".jsonl") and
                      p.split("-", 1)[-1].startswith(prefix))
        while len(olds) >= self.keep:
            try:
                os.remove(os.path.join(folder, olds.pop(0)))
            except OSError:
                break

    def record(self, verb, args, ok, error=None, tick=None,
               xp_delta=0, coins_delta=0):
        w = self.world
        entry = {
            "ts": round(time.time(), 3),
            "tick": w.tick if w is not None else tick,
            "actor": self.actor,
            "verb": verb,
            "args_sha": args_digest(args),
            "ok": bool(ok),
            "xp_delta": int(xp_delta),
            "coins_delta": int(coins_delta),
        }
        if error:
            entry["error"] = str(error)[:120]
        self._fh.write(json.dumps(entry, separators=(",", ":"),
                                  default=str) + "\n")
        self._fh.flush()
        self.entries += 1
        try:                    # mirror across the tree; never raise
            from ratatosk import publish
            publish("witness",
                    {"actor": self.actor, "verb": verb,
                     "ok": bool(ok), "tick": entry.get("tick"),
                     "xp_delta": entry["xp_delta"],
                     "coins_delta": entry["coins_delta"]},
                    frm="norn", kind="witness")
        except Exception:
            pass
        if self._fh.tell() >= self.rotate_bytes:
            self._reopen()

    def _reopen(self):
        self.close()
        self._fh = open(self.path, "a", encoding="utf-8")

    def close(self):
        fh = getattr(self, "_fh", None)
        if fh and not fh.closed:
            fh.close()


class WitnessSDK:
    """Wraps any SDK object; every public method call is journalled."""

    SKIP = {"_VALID"}

    def __init__(self, inner, witness, actor="agent"):
        self._inner = inner
        self._witness = witness
        self._actor = actor

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name.startswith("_") or name in self.SKIP \
                or not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            w = self._witness
            world = w.world
            before_xp = sum(world.xp.values()) if world is not None else 0
            before_coins = world.coins if world is not None else 0
            try:
                result = attr(*args, **kwargs)
            except Exception as exc:
                w.record(name, list(args), False, error=exc)
                raise
            xp_delta = coins_delta = 0
            if world is not None:
                xp_delta = int(sum(world.xp.values()) - before_xp)
                coins_delta = int(world.coins - before_coins)
            w.record(name, list(args), True,
                     xp_delta=xp_delta, coins_delta=coins_delta)
            return result

        return wrapped
