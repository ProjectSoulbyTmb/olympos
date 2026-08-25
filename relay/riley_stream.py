"""RILEY work stream - DAEDELUS nymph verdicts become studio render jobs.

The third RELAY crossing. When the workshop finalizes a 'nymph-hunter'
build (a retinue nymph proving herself inside her ATLAS jail guest),
the verdict rides the `daedalus` topic on the ratatosk bus. This lane
consumes those records under its own seq cursor ('riley') and streams
each nymph a work order into RILEY's loopback job queue: a seeded,
deterministic proof card rendered by the studio's img.art engine - one
card per gate-green nymph, a witness pair when she ships blind.

Delivery discipline:

  * exactly-once consumption via the persistent consumer cursor;
  * crash-tolerant delivery via a spool (pending/sent/rejected under
    assistant/data/relay/riley/) - a dark studio costs retries, never
    losses;
  * idempotent by construction - seeds derive from the workshop job id
    (sha256), so a rare duplicate POST after a mid-move crash renders
    the identical asset into the same provenance sidecar regime.

PERSEPHONE respect: this lane speaks loopback HTTP to RILEY's public
API only - the same surface its own SPA uses. It never writes into
D:\\riley, %LOCALAPPDATA%\\RILEY, or any other guarded scope.

Every terminal outcome broadcasts `fleet.render` on `updates` and
mirrors into the venus mailbox. Nothing here ever raises - a dark
studio is valid state, not an incident.

CLI:  python -m relay riley [--status]
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ratatosk.bus import Post

from . import content


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def parse_nymph(job_id):
    """'nymph-daphne-a1b2c3' -> 'daphne'; None for foreign jobs."""
    prefix = "nymph-"
    if not isinstance(job_id, str) or not job_id.startswith(prefix):
        return None
    rest = job_id[len(prefix):]
    name = rest.rsplit("-", 1)[0] if "-" in rest else rest
    return name or None


def order_for(nymph, ok, job_id):
    """One render order. Deterministic: same job id, same card."""
    style = content.NYMPH_STYLES.get(nymph, content.NYMPH_DEFAULT_STYLE)
    digest = hashlib.sha256(f"riley:{job_id}".encode("utf-8")).hexdigest()
    return {
        "order": f"riley-{job_id}",
        "nymph": nymph,
        "ok": bool(ok),
        "seed": int(digest[:8], 16),
        "attempts": 0,
        "params": {
            "kind": "img.art",
            "style": style,
            "width": content.CARD_W,
            "height": content.CARD_H,
            "fmt": content.CARD_FMT,
            "count": 1 if ok else content.RED_VARIANTS,
        },
    }


def submit_url(params, seed):
    """The loopback endpoint a work order posts to."""
    query = urllib.parse.urlencode({
        "kind": params["kind"], "style": params["style"],
        "width": params["width"], "height": params["height"],
        "fmt": params["fmt"], "count": params["count"],
        "seed": seed,
    })
    return f"{content.RILEY_URL}/api/jobs?{query}"


def deliver(order):
    """POST one order to the studio.

    Returns (state, detail) with state in {'sent', 'rejected',
    'pending'}: 4xx answers are permanent (the studio validated and
    refused), everything else transient (dark server, 5xx, timeout).
    """
    url = submit_url(order["params"], order["seed"])
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(               # nosec - loopback only
                req, timeout=content.RILEY_TIMEOUT_S) as resp:
            status = getattr(resp, "status", 200)
            body = _parse_body(resp.read())
        if status == 200 and body.get("ok"):
            data = body.get("data") or {}
            return "sent", str(data.get("id") or "queued")
        # 2xx but contract-negative: the studio spoke, refusal is final
        return "rejected", str(body.get("error") or f"http {status}")
    except urllib.error.HTTPError as exc:
        try:
            body = _parse_body(exc.read())
        except Exception:                          # noqa: BLE001 - evidence
            body = {}
        if 500 <= exc.code <= 599 or exc.code in (408, 429):
            return "pending", f"http {exc.code}"
        detail = str(body.get("error") or f"http {exc.code}")
        return "rejected", detail[:200]
    except Exception as exc:                       # noqa: BLE001 - dark
        return "pending", f"{type(exc).__name__}: {exc}"[:200]


def _parse_body(raw):
    try:
        doc = json.loads((raw or b"").decode("utf-8") or "{}")
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


class RileyStream:
    """The lane. All durable state lives in ratatosk cursors plus the
    spool directory moves - a killed daemon resumes with no gaps."""

    def __init__(self, post=None):
        self.post = post if post is not None else Post()

    # ---------------- outbound ----------------

    def _emit(self, payload, kind=content.KIND_RENDER):
        """fleet.render* on updates + venus mailbox mirror (best-effort)."""
        try:
            self.post.broadcast(content.TOPIC, kind,
                                payload, frm=content.ORGAN)
        except Exception:                          # noqa: BLE001 - rules
            pass
        try:
            self.post.send(content.MAILBOX, kind,
                           payload, frm=content.ORGAN)
        except Exception:                          # noqa: BLE001 - mirrors
            pass

    # ---------------- cycle ----------------

    def stream(self, limit=100):
        """Drain retryable orders, then consume fresh workshop
        verdicts. Returns {"queued": n_new, "retried": n_retries}."""
        retried = self.drain_spool()
        queued = 0
        for rec in self.post.since("daedalus", "riley", limit=limit):
            payload = rec.get("payload") or {}
            if payload.get("blueprint") != content.RILEY_BLUEPRINT:
                continue                       # foreign builds don't stream
            job_id = payload.get("id")
            nymph = parse_nymph(job_id)
            if not nymph:
                continue                       # malformed id - skip, cursor moves
            order = order_for(nymph, rec.get("kind") != "build-failed",
                              job_id)
            self._spool(order)
            self._attempt(order)
            queued += 1
        return {"queued": queued, "retried": retried}

    def drain_spool(self):
        """Retry every order parked in pending/. Returns how many
        orders were retried this pass."""
        os.makedirs(content.RILEY_PENDING_DIR, exist_ok=True)
        names = sorted(n for n in os.listdir(content.RILEY_PENDING_DIR)
                       if n.endswith(".order.json"))
        retried = 0
        for name in names:
            path = os.path.join(content.RILEY_PENDING_DIR, name)
            order = _read_json(path)
            if not isinstance(order, dict):
                _file_away(path, content.RILEY_REJECTED_DIR,
                           {"outcome": {"state": "rejected",
                                        "detail": "corrupt spool order"}})
                continue
            self._attempt(order, path=path)
            retried += 1
        return retried

    # ---------------- completions lane ----------------

    def completions(self):
        """Announce finished studio jobs the fleet did not submit.

        Polls GET /api/jobs (the same surface the SPA uses), keeps a
        monotonic j<N> cursor under the relay data dir, and emits
        fleet.render-done onto updates + venus for every done job with
        outputs above the cursor. A dark studio costs nothing: silence,
        zero, retry next cycle. Returns how many jobs were announced.
        """
        last = _read_cursor(content.RILEY_CURSOR)
        items = _fetch_jobs(content.RILEY_URL, content.RILEY_TIMEOUT_S)
        if items is None:
            return 0                               # dark studio - valid
        announced = 0
        top = last
        for job in items:
            n = _job_num(job.get("id"))
            if n is None or n <= last:
                continue
            top = max(top, n)
            if job.get("status") != "done" or not job.get("out"):
                continue                           # pending/failed/empty
            outs = [o for o in job.get("out") or []
                    if not str(o).endswith(".riley.json")]
            self._emit({
                "source": "riley-completions",
                "job": job.get("id"),
                "kind": job.get("kind"),
                "engine": job.get("engine"),
                "outputs": outs[:12],
                "count": len(outs),
                "at": _iso(),
            }, kind=content.KIND_RENDER_DONE)
            announced += 1
        if top != last:
            _write_cursor(content.RILEY_CURSOR, top)
        return announced

    # ---------------- internals ----------------

    def _spool(self, order):
        """Park the order durably before first dial."""
        path = os.path.join(content.RILEY_PENDING_DIR,
                            f"{order['order']}.order.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(order, fh, indent=1, default=str)
        os.replace(tmp, path)

    def _attempt(self, order, path=None):
        """Dial once, then file by verdict and publish the outcome."""
        order["attempts"] = int(order.get("attempts") or 0) + 1
        state, detail = deliver(order)
        if state == "sent":
            if path is None:
                path = os.path.join(content.RILEY_PENDING_DIR,
                                    f"{order['order']}.order.json")
            _file_away(path, content.RILEY_SENT_DIR,
                       {"outcome": {"state": state, "detail": detail}})
            self._emit(_payload(order, state, detail))
        elif state == "rejected":
            if path is None:
                path = os.path.join(content.RILEY_PENDING_DIR,
                                    f"{order['order']}.order.json")
            _file_away(path, content.RILEY_REJECTED_DIR,
                       {"outcome": {"state": state, "detail": detail}})
            self._emit(_payload(order, state, detail))
        # pending: refresh attempts in place; silence until it lands
        else:
            if path is None:
                path = os.path.join(content.RILEY_PENDING_DIR,
                                    f"{order['order']}.order.json")
            _rewrite(path, order)


def _payload(order, state, detail):
    job_id = (order.get("order") or "")
    if job_id.startswith("riley-"):
        job_id = job_id[len("riley-"):]
    return {
        "source": "riley-stream",
        "nymph": order.get("nymph"),
        "job": job_id,
        "ok": state == "sent",
        "state": state,
        "verdict": "green" if order.get("ok") else "red",
        "attempts": order.get("attempts"),
        "detail": str(detail)[:200],
        "at": _iso(),
    }


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _job_num(jid):
    """'j42' -> 42; None for foreign ids."""
    s = str(jid or "")
    if not s.startswith("j"):
        return None
    try:
        return int(s[1:])
    except ValueError:
        return None


def _read_cursor(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _write_cursor(path, n):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(str(n))
        os.replace(tmp, path)
    except OSError:
        pass                                   # cursor lag costs re-announce


def _fetch_jobs(url, timeout_s):
    """GET /api/jobs items, or None when the studio is dark/refusing."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/jobs",
                                     headers={"User-Agent": "relay"})
        with urllib.request.urlopen(               # nosec - loopback only
                req, timeout=timeout_s) as resp:
            doc = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:                              # noqa: BLE001 - dark
        return None
    if not isinstance(doc, dict) or doc.get("ok") is not True:
        return None
    items = doc.get("data", {}).get("items")
    return items if isinstance(items, list) else None


def _rewrite(path, order):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(order, fh, indent=1, default=str)
        os.replace(tmp, path)
    except OSError:
        pass


def _file_away(src, dest_dir, extra):
    """Move an order to its terminal folder, merging the outcome."""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        body = _read_json(src)
        if not isinstance(body, dict):
            body = {"raw": None}
        body.update(extra)
        body["filed_at"] = _iso()
        dest = os.path.join(dest_dir, os.path.basename(src))
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=1, default=str)
        try:
            os.remove(src)
        except OSError:
            pass
        os.replace(tmp, dest)
    except OSError:
        pass                                   # filing must never kill the lane
