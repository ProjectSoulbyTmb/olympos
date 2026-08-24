"""HADES provenance watermarks - invisible, HMAC-authenticated origin marks.

A watermark encodes a payload string into an invisible run of zero-width
characters framed by word joiners, then appends it to a source file. The
payload carries an HMAC tag derived from the local Hades key, so a mark
we find elsewhere is either provably ours (authentic) or a forgery
someone tried to frame us with. Marks survive ordinary copy/paste and
rebranding edits until someone deliberately hunts down invisible chars.

This is evidence-of-origin, not DRM: stripping it is possible for a
determined adversary, which is exactly why the seal + fingerprints
exist independently.
"""

import hashlib
import hmac

OPEN = "\u2060\u2060"
CLOSE = "\u2061\u2061"
BIT0 = "\u200b"
BIT1 = "\u200c"

_PREFIXES = {".py": "#", ".js": "//", ".ts": "//", ".cjs": "//",
             ".mjs": "//", ".java": "//", ".cs": "//", ".c": "//",
             ".cpp": "//", ".h": "//", ".rs": "//"}


def tag(payload, key):
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def token(payload, key):
    data = payload + "|" + tag(payload, key)
    bits = "".join(format(b, "08b") for b in data.encode("utf-8"))
    marks = "".join(BIT0 if b == "0" else BIT1 for b in bits)
    return OPEN + marks + CLOSE


def embed_text(text, tok, prefix="#"):
    lines = text.rstrip("\n").split("\n")
    while lines and OPEN in lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n" + prefix + " " + tok + "\n"


def extract(text):
    found = []
    start = 0
    while True:
        i = text.find(OPEN, start)
        if i < 0:
            break
        j = text.find(CLOSE, i + len(OPEN))
        if j < 0:
            break
        body = text[i + len(OPEN):j]
        bits = []
        ok = len(body) > 0 and len(body) % 8 == 0
        if ok:
            for ch in body:
                if ch == BIT0:
                    bits.append("0")
                elif ch == BIT1:
                    bits.append("1")
                else:
                    ok = False
                    break
        if ok:
            raw = bytearray(
                int("".join(bits[k:k + 8]), 2) for k in range(0, len(bits), 8)
            )
            try:
                found.append(raw.decode("utf-8"))
            except UnicodeDecodeError:
                pass
        start = j + len(CLOSE)
    return found


def authenticate(payload, key):
    body, sep, t = payload.rpartition("|")
    if not sep:
        return False
    return hmac.compare_digest(tag(body, key), t)


def parse_payload(payload):
    parts = payload.split("|")
    if len(parts) >= 2 and parts[0] == "HADES":
        keys = ["kind", "asset", "stamp"]
        return dict(zip(keys, parts[1:]))
    return None


def prefix_for(filename):
    dot = filename.rfind(".")
    ext = filename[dot:].lower() if dot >= 0 else ""
    return _PREFIXES.get(ext, "#")
