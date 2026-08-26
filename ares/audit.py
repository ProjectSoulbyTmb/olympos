"""ARES v2 audit - chain-aware viewer for the operations journal.

Walks journal.jsonl verifying the HMAC chain exactly like
kernel.verify_journal, then renders filtered rows. A broken chain is
displayed loudly; export reports carry the verdict header so a saved
audit can never masquerade as verified.
"""

import calendar
import hashlib
import hmac
import json
import os
import time

try:
    from . import kernel, machine             # package context
except ImportError:
    import ares_kernel as kernel              # workshop-flat context
    import ares_machine as machine


class AuditError(Exception):
    pass


def walk():
    """Return (ok, entries, first_bad). entries are parsed lines in
    order; each keeps its verdict under '_ok' (a broken chain marks
    every entry from first_bad onward)."""
    try:
        mk = machine.load_machine_key()
    except Exception:
        if not os.path.exists(kernel.journal_path()):
            return True, [], None
        return False, [], 0                  # unverifiable = loud
    jk = kernel._journal_key(mk)
    prev = "genesis"
    ok = True
    first_bad = None
    entries = []
    try:
        with open(kernel.journal_path(), encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    entry = json.loads(ln)
                except ValueError:
                    ok = False
                    first_bad = first_bad or (len(entries) + 1)
                    break
                body = {k: v for k, v in entry.items() if k != "sha"}
                expect = hmac_of(jk, body)
                good = (entry.get("prev") == prev and
                        hmac.compare_digest(expect,
                                            entry.get("sha", "")))
                if not good and ok:
                    ok = False
                    first_bad = len(entries) + 1
                row = dict(entry)
                row["_ok"] = bool(good) and ok
                entries.append(row)
                prev = entry.get("sha", prev)
    except FileNotFoundError:
        return True, [], None
    return ok, entries, first_bad


def hmac_of(jk, body):
    return hmac.new(jk, json.dumps(body, sort_keys=True,
                                   separators=(",", ":"),
                                   default=str).encode("utf-8"),
                    hashlib.sha512).hexdigest()


def _since_ts(text):
    """'YYYY-MM-DD[ HH:MM[:SS]]' or 'Nd' days-ago."""
    text = text.strip()
    if text.endswith("d") and text[:-1].isdigit():
        return time.time() - int(text[:-1]) * 86400
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return calendar.timegm(time.strptime(text, fmt))
        except ValueError:
            continue
    raise AuditError("bad --since %r (use YYYY-MM-DD or Nd)" % text)


def filter_rows(entries, op=None, since=None, tail=None):
    rows = entries
    if op:
        rows = [r for r in rows if r.get("op") == op]
    if since:
        cut = _since_ts(since)
        rows = [r for r in rows if r.get("t", 0) >= cut]
    if tail:
        rows = rows[-int(tail):]
    return rows


def render(rows, chain_ok, first_bad):
    out = []
    head = "journal: CHAIN-OK" if chain_ok else \
        "journal: CHAIN BROKEN (first bad @%s)" % first_bad
    out.append(head)
    if not rows:
        out.append("  (no matching entries)")
    for r in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                              time.gmtime(r.get("t", 0)))
        mark = " " if r["_ok"] else "!"
        detail = {k: v for k, v in r.items()
                  if k not in ("t", "op", "sha", "prev", "_ok")}
        out.append("  %s%s %-12s %s" % (mark, stamp, r.get("op", "?"),
                                        json.dumps(detail, default=str)))
    return "\n".join(out)


def show(op=None, since=None, tail=None):
    ok, entries, first_bad = walk()
    rows = filter_rows(entries, op=op, since=since, tail=tail)
    return render(rows, ok, first_bad), ok


def export(path, op=None, since=None, tail=None):
    text, ok = show(op=op, since=since, tail=tail)
    header = ("ARES audit export %s (UTC)\n"
              "verdict: %s\n" % (
                  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "CHAIN-OK" if ok else "CHAIN BROKEN - UNTRUSTED"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + text + "\n")
    return ok
