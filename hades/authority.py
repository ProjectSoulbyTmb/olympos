"""HADES Operator Override Authority - who may command the kernel.

The operator (and only the operator) holds a 32-byte secret at
%LOCALAPPDATA%\\HADES\\operator_key.bin (or HADES_AUTHORITY_DIR).
The repo keeps ONLY a SHA-256 fingerprint of that secret under
hades/state/operator.json - never the secret itself.

Privileged commands are issued as signed tokens:

    token = {
      "op":    "force-seal" | "raw" | "exempt" | ...,
      "args":  {...},
      "ts":    issued unix time,
      "exp":   ts + ttl,
      "nonce": one-shot hex,
      "sig":   HMAC-SHA256(secret, canonical(token-without-sig)),
    }

`mint` requires reading the secret, so it can only happen on the
operator's own machine with deliberate intent. `override` verifies
sig + expiry + single-use nonce before touching anything, then logs
the attempt into the hash-chained audit trail either way.

Fleet agents and remote actors hold no secret and no code path that
mints one: denial is the default, and every denial is evidence.
"""

import hashlib
import hmac
import json
import os
import secrets
import time

CANON = dict(sort_keys=True, separators=(",", ":"))
NONCE_TTL = 24 * 3600


class AuthorityError(RuntimeError):
    """Override refused."""


def authority_dir():
    d = os.environ.get("HADES_AUTHORITY_DIR")
    if not d:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "HADES")
    return d


def secret_path():
    return os.path.join(authority_dir(), "operator_key.bin")


def _load_secret():
    p = secret_path()
    if not os.path.exists(p):
        raise AuthorityError(
            "no operator secret enrolled on this machine (%s) - "
            "run: python hades/cli.py authorize --confirm" % p)
    with open(p, "rb") as f:
        key = f.read()
    if len(key) != 32:
        raise AuthorityError("operator secret corrupt - re-enroll")
    return key


def _hash_secret():
    return hashlib.sha256(_load_secret()).hexdigest()


def enroll():
    """Create or rotate the operator secret. Returns the public
    fingerprint document (safe to keep in state)."""
    d = authority_dir()
    os.makedirs(d, exist_ok=True)
    p = secret_path()
    key = secrets.token_bytes(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    fp_doc = {
        "fingerprint": hashlib.sha256(key).hexdigest(),
        "enrolled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "policy": 1,
    }
    return fp_doc


def write_fingerprint(state_dir, fp_doc):
    os.makedirs(state_dir, exist_ok=True)
    tmp = os.path.join(state_dir, "operator.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fp_doc, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(state_dir, "operator.json"))


def read_fingerprint(state_dir):
    p = os.path.join(state_dir, "operator.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def _canonical(obj):
    return json.dumps(obj, **CANON).encode("utf-8")


def mint(op, args=None, ttl_s=600):
    """Sign one privileged operation with the operator secret."""
    key = _load_secret()
    ts = int(time.time())
    tok = {
        "op": str(op),
        "args": dict(args or {}),
        "ts": ts,
        "exp": ts + int(ttl_s),
        "nonce": secrets.token_hex(8),
    }
    tok["sig"] = hmac.new(key, _canonical(tok), hashlib.sha256).hexdigest()
    return tok


def _nonces_path(state_dir):
    return os.path.join(state_dir, "override_nonces.json")


def _load_nonces(state_dir):
    p = _nonces_path(state_dir)
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_nonces(state_dir, nonces):
    tmp = _nonces_path(state_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(nonces, f, indent=1, sort_keys=True)
    os.replace(tmp, _nonces_path(state_dir))


def verify_token(state_dir, token, now=None):
    """Full gate: fingerprint binding, signature, expiry, replay.
    Returns the token on success; raises AuthorityError otherwise."""
    now = int(now if now is not None else time.time())
    fp = read_fingerprint(state_dir)
    if not fp:
        raise AuthorityError("no enrolled operator fingerprint in state")
    try:
        sig = str(token["sig"])
        body = {k: v for k, v in token.items() if k != "sig"}
        op = str(body["op"])
        args = dict(body["args"])
        ts, exp, nonce = int(body["ts"]), int(body["exp"]), str(body["nonce"])
    except (KeyError, TypeError, ValueError) as e:
        raise AuthorityError("malformed token (%s)" % e)
    key = _load_secret()
    want = hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, sig):
        raise AuthorityError("signature invalid - not minted by the operator")
    fp_now = hashlib.sha256(key).hexdigest()
    if fp_now != fp.get("fingerprint"):
        raise AuthorityError(
            "secret does not match enrolled fingerprint - re-enroll")
    if now > exp:
        raise AuthorityError("token expired (%d s past)" % (now - exp))
    nonces = _load_nonces(state_dir)
    cut = now - NONCE_TTL
    nonces = {n: t for n, t in nonces.items() if t >= cut}
    if nonce in nonces:
        raise AuthorityError("replay detected - nonce already used")
    nonces[nonce] = now
    _save_nonces(state_dir, nonces)
    return token


# ---- raw grammar policy -------------------------------------------------
# The uncensored surface: any PUBLIC kernel method may be invoked with
# arbitrary JSON arguments. Private machinery stays private; that is a
# correctness boundary, not censorship.

DENIED_PREFIX = "_"


def raw_allowed(method_name):
    return bool(method_name) and not method_name.startswith(DENIED_PREFIX)


def raw_call(instance, method_name, kwargs):
    if not raw_allowed(method_name):
        raise AuthorityError("method %r is not part of the public kernel "
                             "surface" % method_name)
    fn = getattr(instance, method_name, None)
    if not callable(fn):
        raise AuthorityError("kernel has no callable %r" % method_name)
    return fn(**dict(kwargs or {}))
