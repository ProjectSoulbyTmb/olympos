"""ARES v2 pairing - move trust between your own machines.

pair-begin exports THIS machine's key sealed under a one-time 128-bit
code (passphrase-only factor, L2 scrypt economics; the code is the
only secret). pair-adopt on machine B unwraps it with the same code
and stores it DPAPI-wrapped in B's keyring, after which B can open
blobs A sealed (and vice versa). Honest risk: whoever holds BOTH the
pairing file and the code holds your machine identity; a copy that
already left cannot be recalled - only adoption can be revoked.
"""

import getpass
import os
import re
import secrets

try:
    from . import kernel, machine             # package context
except ImportError:
    import ares_kernel as kernel              # workshop-flat context
    import ares_machine as machine


class PairingError(Exception):
    pass


CODE_BYTES = 16                              # 128-bit one-time code
_GROUP_RE = re.compile(r"[^0-9a-fA-F]")


def format_code(raw):
    h = bytes(raw).hex().upper()
    return " ".join(h[i:i + 4] for i in range(0, len(h), 4))


def normalize_code(text):
    hexish = _GROUP_RE.sub("", text).lower()
    if len(hexish) != CODE_BYTES * 2:
        raise PairingError("code must be %d hex digits"
                           % (CODE_BYTES * 2))
    return hexish


def pair_begin(out_path=None):
    raw = machine.load_machine_key()         # DPAPI unwrap, bytearray
    fp = machine.fingerprint(raw)
    code = secrets.token_bytes(CODE_BYTES)
    code_text = normalize_code(format_code(code))
    try:
        blob = kernel.seal_bytes(bytes(raw), code_text, level=2,
                                 machine_key=bytearray())
    finally:
        for i in range(len(raw)):
            raw[i] = 0
    out = os.path.abspath(out_path or "ares-pairing.pair")
    fd = os.open(out + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                 getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, blob)
    finally:
        os.close(fd)
    os.replace(out + ".tmp", out)
    kernel._journal_append("pair-begin", {"out": out, "fp": fp})
    return out, format_code(code)


def pair_adopt(pair_path, code_text=None):
    if not os.path.exists(pair_path):
        raise PairingError("no such pairing file: %s" % pair_path)
    if code_text is None:
        code_text = getpass.getpass("[ares] pairing code: ")
    code = normalize_code(code_text)
    with open(pair_path, "rb") as fh:
        blob = fh.read()
    try:
        pt = kernel.open_blob(blob, code, machine_key=bytearray())
    except kernel.AresError as exc:
        raise PairingError("adoption refused: %s" % exc) from None
    if len(pt) != machine.KEY_BYTES:
        raise PairingError("pairing payload corrupt")
    raw = bytearray(pt)
    primary_fp = machine.fingerprint(machine.load_machine_key())
    fp = machine.fingerprint(raw)
    if fp == primary_fp:
        raise PairingError("that is this machine's own key")
    for known, _ in machine.load_adopted():
        if known == fp:
            raise PairingError("already adopted (%s)" % fp)
    path = machine.store_adopted(raw)[1]
    kernel._journal_append("pair-adopt", {"fp": fp, "from": pair_path})
    return fp, path


def pair_revoke(fp=None):
    n = machine.drop_adopted(fp)
    if n:
        kernel._journal_append("pair-revoke",
                               {"fp": fp or "ALL", "removed": n})
    return n


def pair_list():
    return [(fp, "%d bytes" % len(k)) for fp, k in machine.load_adopted()]
