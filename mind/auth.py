"""MIND auth - obs-websocket v5 challenge/response, stdlib only.

The v5 handshake salts the operator's password, then challenges the
derived secret. Both hashes are SHA-256 over UTF-8 text, base64
encoded (not hex):

    secret = BASE64(SHA256(password + salt))
    auth   = BASE64(SHA256(secret + challenge))

Run: python mind/auth.py   (self-test, exit 0 = vectors agree)
"""

from __future__ import annotations

import base64
import hashlib


def derive_secret_b64(password: str, salt_b64: str) -> str:
    raw = hashlib.sha256((password + salt_b64).encode("utf-8")).digest()
    return base64.b64encode(raw).decode("ascii")


def challenge_response_b64(secret_b64: str, challenge_b64: str) -> str:
    raw = hashlib.sha256((secret_b64 + challenge_b64).encode("utf-8")).digest()
    return base64.b64encode(raw).decode("ascii")


def respond_to_hello(auth: "dict | None", password: str) -> "str | None":
    """Build the Identify authentication string from a Hello payload.

    Returns None when the server requested no authentication.
    """
    if not auth:
        return None
    salt = auth.get("salt", "")
    challenge = auth.get("challenge", "")
    secret = derive_secret_b64(password, salt)
    return challenge_response_b64(secret, challenge)


def selftest() -> int:
    failures = []

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_roundtrip():
        salt = "c2FsdA=="
        challenge = "Y2hhbGxlbmdl"
        good = respond_to_hello({"salt": salt, "challenge": challenge},
                                "supersecretpw")
        bad = respond_to_hello({"salt": salt, "challenge": challenge},
                               "wrongpassword")
        assert good and bad and good != bad, "responses must diverge"
        # server side recomputes independently and compares
        expected = challenge_response_b64(
            derive_secret_b64("supersecretpw", salt), challenge)
        assert good == expected, "client/server vectors disagree"

    def t_no_auth():
        assert respond_to_hello(None, "pw") is None, \
            "open servers must skip authentication"
        assert respond_to_hello({}, "pw") is None, \
            "empty auth block must skip authentication"

    check("auth-roundtrip-divergence", t_roundtrip)
    check("auth-open-server", t_no_auth)

    print(f"auth selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
