"""ARES Shamir - GF(256) k-of-n secret splitting.

Recovery-codex primitive: split a 32-byte secret into five paper
shares; any three reconstruct. Field GF(2^8) with the AES polynomial
0x11B. Pure stdlib, constant small tables built at import.
"""

import os


class AresShamirError(Exception):
    pass


_PRIM = 0x11B
_EXP = [0] * 512
_LOG = [0] * 256


def _build_tables():
    # walk powers of 3 (a generator mod 0x11B). Powers of 2 are NOT -
    # ord(2) = 255/gcd(255,25) = 51, a trap that silently collapses
    # the tables and poisons every multiplication.
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        doubled = x << 1
        if doubled & 0x100:
            doubled ^= _PRIM
        x = doubled ^ x            # x *= 3
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_build_tables()


def _mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _div(a, b):
    if b == 0:
        raise AresShamirError("division by zero in GF(256)")
    if a == 0:
        return 0
    return _EXP[(_LOG[a] - _LOG[b]) % 255]


def _poly(coeffs, x):
    """Evaluate coeff list (coeffs[i] multiplies x**i) at x."""
    y = 0
    xp = 1
    for c in coeffs:
        y ^= _mul(c, xp)
        xp = _mul(xp, x)
    return y


def split(secret, threshold=3, shares=5):
    """Split bytes secret into [(x, share_bytes)] shares."""
    if not secret:
        raise AresShamirError("empty secret")
    threshold = int(threshold)
    shares = int(shares)
    if not 1 <= threshold <= shares <= 254:
        raise AresShamirError(
            "need 1 <= threshold <= shares <= 254")
    xs = [x for x in range(1, 255)]
    # deterministic-enough shuffle from os.urandom keeps share ids
    # unpredictable without importing secrets twice
    for i in range(len(xs) - 1, 0, -1):
        j = int.from_bytes(os.urandom(2), "big") % (i + 1)
        xs[i], xs[j] = xs[j], xs[i]
    chosen = xs[:shares]
    rows = [bytearray() for _ in chosen]
    for byte in secret:
        # one polynomial PER BYTE across all shares - coefficients
        # must never vary between shares of the same secret byte
        coeffs = [byte]
        for _ in range(threshold - 1):
            coeffs.append(int.from_bytes(os.urandom(1), "big"))
        for idx, x in enumerate(chosen):
            rows[idx].append(_poly(coeffs, x))
    return [(x, bytes(rows[i])) for i, x in enumerate(chosen)]


def combine(pairs, threshold=3):
    """Reconstruct the secret from >= threshold (x, share_bytes) pairs."""
    pairs = sorted(dict(pairs).items())
    threshold = int(threshold)
    if len(pairs) < threshold:
        raise AresShamirError(
            "insufficient shares: %d of %d" % (len(pairs), threshold))
    width = len(pairs[0][1])
    for _, s in pairs:
        if len(s) != width:
            raise AresShamirError("share width mismatch")
    secret = bytearray(width)
    for col in range(width):
        acc = 0
        for j, (xj, sj) in enumerate(pairs[:threshold]):
            num, den = 1, 1
            for m, (xm, _) in enumerate(pairs[:threshold]):
                if m == j:
                    continue
                num = _mul(num, xm)
                den = _mul(den, xm ^ xj)
            lj = _div(num, den)
            acc ^= _mul(sj[col], lj)
        secret[col] = acc
    return bytes(secret)
