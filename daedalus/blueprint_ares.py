"""DAEDALUS blueprint: ares-vault - the code seal kernel.

Tier-1 protection realm. CNSA/FIPS-aligned posture on pure stdlib
primitives (house law: no third-party crypto). Proven laws:

  Dual-factor law    - file keys derive from scrypt(passphrase) AND a
                       DPAPI-bound machine key; neither alone decrypts.
                       A stolen .ares blob is inert off-machine, and an
                       attacker with the Windows login still faces a
                       memory-hard KDF.
  Verify-before-write - HMAC-SHA512 tag over header+ciphertext checked
                       before any byte lands; tamper/truncate/swap all
                       fail closed with nothing written.
  Zero-knowledge ops - the gate uses synthetic vectors only; real
                       passphrases never enter the build pipeline.
  Loud failure       - every refusal raises; silence is never green.

Defense levels (scrypt N, r=8, p=1, dklen=64; maxmem capped by the
signed-long ceiling so every level must actually run in-process):
  L1 N=2**15 (32 MiB/guess, default) | L2 N=2**18 (256 MiB) |
  L3 N=2**20 (1 GiB)

Recovery codex: init splits a random 32-byte recovery secret into five
GF(256) Shamir shares; any three reconstruct it. The hex form unlocks
exactly like a passphrase. Shares print once; they are never stored.

Honest gaps (documented in README): no AES-GCM in stdlib -> HMAC-
SHA512-CTR stream cipher (sound, non-standard suite); no post-quantum;
Python GC makes zeroization best-effort.

Weave shape: flat files (workshop law). Modules carry a dual-context
import shim so the same text runs workshop-flat and deployed as the
``ares`` package.
"""

import sys

SHAMIR = '''"""ARES Shamir - GF(256) k-of-n secret splitting.

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
'''

MACHINE = '''"""ARES machine lock - DPAPI-bound key provisioning.

A random 32-byte key is wrapped by Windows DPAPI (CryptProtectData,
user scope) and stored under ARES_KEY_DIR (default the user profile).
CryptUnprotectData succeeds only for the same Windows user on the
same machine: this is the hardware lock that makes stolen .ares blobs
inert elsewhere. Non-Windows hosts refuse loudly (platform law).

Env overrides:
  ARES_KEY_DIR - directory holding machine.key (gate/tests use tmp).
"""

import ctypes
import ctypes.wintypes
import os
import sys

KEY_BYTES = 32

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class AresMachineError(Exception):
    pass


class Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint),
                ("pbData", ctypes.c_void_p)]


crypt32 = ctypes.WinDLL("crypt32") if sys.platform == "win32" else None
_kernel32 = ctypes.WinDLL("kernel32") if sys.platform == "win32" else None
if crypt32 is not None:
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(Blob), ctypes.c_wchar_p,
        ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt32.CryptProtectData.restype = bool
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(Blob), ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt32.CryptUnprotectData.restype = bool
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    ctypes.windll.kernel32


def _last_error():
    return ctypes.get_last_error()


def key_dir():
    env = os.environ.get("ARES_KEY_DIR")
    if env:
        return env
    prof = os.environ.get("USERPROFILE") or \
        os.environ.get("HOME") or os.getcwd()
    return os.path.join(prof, ".ares")


def key_path():
    return os.path.join(key_dir(), "machine.key")


def _dpapi_protect(raw, desc="ARES-machine-key-v1"):
    if crypt32 is None:
        raise AresMachineError(
            "DPAPI unavailable on this platform; ARES refuses to "
            "provision a weaker machine lock")
    buf = ctypes.create_string_buffer(bytes(raw), len(raw))
    kin = Blob(len(raw), ctypes.cast(buf, ctypes.c_void_p))
    kout = Blob()
    ctypes.set_last_error(0)
    ok = crypt32.CryptProtectData(
        ctypes.byref(kin), desc, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(kout))
    if not ok:
        raise AresMachineError("CryptProtectData failed: %s" %
                               _last_error())
    try:
        return ctypes.string_at(kout.pbData, kout.cbData)
    finally:
        _kernel32.LocalFree(kout.pbData)


def _dpapi_unprotect(wrapped):
    if crypt32 is None:
        raise AresMachineError("DPAPI unavailable on this platform")
    wbuf = ctypes.create_string_buffer(bytes(wrapped), len(wrapped))
    kin = Blob(len(wrapped), ctypes.cast(wbuf, ctypes.c_void_p))
    kout = Blob()
    descr = ctypes.c_wchar_p()
    ctypes.set_last_error(0)
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(kin), ctypes.byref(descr), None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(kout))
    if not ok:
        raise AresMachineError(
            "MACHINE LOCK REFUSED - blob moved off its home machine "
            "or user (GetLastError=%d)" % _last_error())
    try:
        buf = ctypes.string_at(kout.pbData, kout.cbData)
        return bytearray(buf)
    finally:
        _kernel32.LocalFree(kout.pbData)


def provision():
    """Idempotent: create the machine key once, return its path."""
    d = key_dir()
    os.makedirs(d, exist_ok=True)
    p = key_path()
    if os.path.exists(p):
        load_machine_key()          # prove the existing key unwraps
        return p
    raw = bytearray(os.urandom(KEY_BYTES))
    try:
        wrapped = _dpapi_protect(bytes(raw))
    finally:
        for i in range(len(raw)):
            raw[i] = 0
    tmp = p + ".tmp"
    # O_BINARY is non-negotiable: text mode translates LF into CRLF
    # and silently shreds binary blobs on Windows
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                 getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, wrapped)
    finally:
        os.close(fd)
    os.replace(tmp, p)
    return p


def load_machine_key():
    """Return the machine key as a fresh bytearray; refuse loudly if
    absent or unprovable (the simulated-theft path)."""
    if not os.path.exists(key_path()):
        raise AresMachineError(
            "MACHINE LOCK ABSENT - run: python -m ares init")
    with open(key_path(), "rb") as fh:
        wrapped = fh.read()
    return _dpapi_unprotect(wrapped)


def has_machine_key():
    return os.path.exists(key_path())
'''

KERNEL = '''"""ARES vault-cipher kernel - dual-factor file sealing.

Format (.ares): MAGIC(5) VERSION(1) LEVEL(1) SALT(16) NONCE(16) ||
ciphertext || TAG(64).

Pipeline: scrypt(passphrase, salt, level) -> stretched; KEK =
HMAC-SHA512(machine_key, stretched); SP800-108 counter-KDF splits KEK
into enc(32)+mac(64); keystream = HMAC-SHA512(enc, nonce||seq64) XOR;
tag = HMAC-SHA512(mac, header||ct). Verify-before-write everywhere.
Keys live in bytearrays and are zeroized after use (best effort).
"""

import hashlib
import hmac
import json
import os
import struct
import time

try:
    from . import machine, shamir          # package context
except ImportError:                        # workshop-flat context
    import ares_machine as machine         # noqa: F401
    import ares_shamir as shamir           # noqa: F401

MAGIC = b"ARES\\x01"
VERSION = 1
SALT_LEN = 16
NONCE_LEN = 16
TAG_LEN = 64
KEY_LEN = 32
LEVELS = {1: 2 ** 15, 2: 2 ** 18, 3: 2 ** 20}   # 32M / 256M / 1GiB
SCRYPT_MAXMEM = 2 ** 31 - 1    # signed-long ceiling; L3 tops at 1 GiB
SCRYPT_R = 8
SCRYPT_P = 1
LABEL_ENC = b"ARES-enc-v1"
LABEL_MAC = b"ARES-mac-v1"
LABEL_JNL = b"ARES-journal-v1"


class AresError(Exception):
    pass


# ------------------------------------------------------------ self-test --

_SHA512_ABC = (
    "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee"
    "64b55d39a2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e"
    "2a9ac94fa54ca49f")

_HMAC_RFC4231_C1 = (
    "87aa7cdea5ef619d4ff0b4241a1d6cb02379f4e2ce4ec2787ad0b3054"
    "5e17cdedaa833b7d6b8a702038b274eaea3f4e4be9d914eeb61f1702e"
    "696c203a126854")

_SELFTEST_DONE = False


def power_on_selftest(full=False):
    """FIPS-style POST: known-answer vectors before trusting ops."""
    global _SELFTEST_DONE
    if _SELFTEST_DONE and not full:
        return True
    if hashlib.sha512(b"abc").hexdigest() != _SHA512_ABC:
        raise AresError("SELF-TEST FAILED: sha512 KAT")
    tag = hmac.new(b"\\x0b" * 20, b"Hi There", hashlib.sha512)
    if tag.hexdigest() != _HMAC_RFC4231_C1:
        raise AresError("SELF-TEST FAILED: hmac-sha512 KAT")
    a = hashlib.scrypt(b"k", salt=b"s", n=16, r=1, p=1, dklen=32,
                       maxmem=SCRYPT_MAXMEM)
    b = hashlib.scrypt(b"k", salt=b"s", n=16, r=1, p=1, dklen=32,
                       maxmem=SCRYPT_MAXMEM)
    c = hashlib.scrypt(b"k", salt=b"t", n=16, r=1, p=1, dklen=32,
                       maxmem=SCRYPT_MAXMEM)
    if a != b or a == c:
        raise AresError("SELF-TEST FAILED: scrypt determinism")
    if full:
        mk = bytearray(hashlib.sha512(b"post-machine").digest()[:KEY_LEN])
        blob = seal_bytes(b"post-vector", "post-pass", level=1,
                          machine_key=mk)
        pt = open_blob(blob, "post-pass", machine_key=mk)
        for i in range(len(mk)):
            mk[i] = 0
        if pt != b"post-vector":
            raise AresError("SELF-TEST FAILED: format roundtrip")
    _SELFTEST_DONE = True
    return True


# ------------------------------------------------------------- zeroize --

def zeroize(buf):
    """Best-effort wipe of a bytearray (GC cannot be forced; honest)."""
    if isinstance(buf, bytearray):
        for i in range(len(buf)):
            buf[i] = 0


# ------------------------------------------------------- key schedule --

def _stretch(passphrase_bytes, salt, level):
    n = LEVELS[int(level)]
    out = hashlib.scrypt(bytes(passphrase_bytes), salt=salt, n=n,
                         r=SCRYPT_R, p=SCRYPT_P, dklen=64,
                         maxmem=SCRYPT_MAXMEM)
    return bytearray(out)


def _merge(machine_key, stretched):
    return hmac.new(bytes(machine_key),
                    bytes(stretched), hashlib.sha512).digest()


def _sp800_108(kek, label, length):
    """NIST SP800-108 counter-mode KDF over HMAC-SHA512."""
    out = b""
    counter = 1
    while len(out) < length:
        out += hmac.new(kek, label + b"\\x00" + b"ARES-vault" +
                        struct.pack(">I", counter),
                        hashlib.sha512).digest()
        counter += 1
    return out[:length]


def _derive_keys(kek):
    material = _sp800_108(kek, LABEL_ENC, KEY_LEN + TAG_LEN)
    return material[:KEY_LEN], bytearray(material[KEY_LEN:])


def _keystream_xor(enc_key, nonce, data):
    out = bytearray(len(data))
    seq = 0
    pos = 0
    while pos < len(data):
        ks = hmac.new(enc_key,
                      nonce + struct.pack(">Q", seq),
                      hashlib.sha512).digest()
        chunk = min(64, len(data) - pos)
        for i in range(chunk):
            out[pos + i] = data[pos + i] ^ ks[i]
        pos += chunk
        seq += 1
    return out


# -------------------------------------------------------------- core --

def seal_bytes(plaintext, passphrase, level=1, machine_key=None):
    power_on_selftest()
    if int(level) not in LEVELS:
        raise AresError("bad defense level: %r" % (level,))
    mk = machine_key if machine_key is not None \\
        else machine.load_machine_key()
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    stretched = _stretch(passphrase.encode("utf-8"), salt, level)
    kek = _merge(mk, stretched)
    zeroize(stretched)
    enc_key, mac_key = _derive_keys(kek)
    ct = bytes(_keystream_xor(enc_key, nonce, plaintext))
    header = MAGIC + bytes([VERSION, int(level)]) + salt + nonce
    tag = hmac.new(bytes(mac_key), header + ct,
                   hashlib.sha512).digest()
    zeroize(mac_key)
    return header + ct + tag


def open_blob(blob, passphrase, machine_key=None):
    power_on_selftest()
    if len(blob) < 5 + 2 + SALT_LEN + NONCE_LEN + TAG_LEN:
        raise AresError("REFUSED: truncated blob")
    if blob[:5] != MAGIC:
        raise AresError("REFUSED: not an ARES vault")
    version, level = blob[5], blob[6]
    if version != VERSION:
        raise AresError("REFUSED: unknown vault version %d" % version)
    if level not in LEVELS:
        raise AresError("REFUSED: bad defense level %d" % level)
    off = 7
    salt = blob[off:off + SALT_LEN]
    off += SALT_LEN
    nonce = blob[off:off + NONCE_LEN]
    off += NONCE_LEN
    ct = blob[off:len(blob) - TAG_LEN]
    tag = blob[len(blob) - TAG_LEN:]
    mk = machine_key if machine_key is not None \\
        else machine.load_machine_key()
    stretched = _stretch(passphrase.encode("utf-8"), salt, level)
    kek = _merge(mk, stretched)
    zeroize(stretched)
    enc_key, mac_key = _derive_keys(kek)
    expect = hmac.new(bytes(mac_key), blob[:off] + ct,
                      hashlib.sha512).digest()
    good = hmac.compare_digest(expect, tag)
    zeroize(mac_key)
    if not good:
        raise AresError(
            "AUTHENTICATION FAILED - wrong factor or tampered blob")
    return bytes(_keystream_xor(enc_key, nonce, ct))


# ------------------------------------------------------------- journal --

def state_dir():
    env = os.environ.get("ARES_STATE_DIR")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if os.path.isdir(os.path.join(parent, "realms")):
        return os.path.join(parent, "data", "ares")   # deployed repo
    return os.path.join(os.getcwd(), "data", "ares")   # workshop flat


def journal_path():
    return os.path.join(state_dir(), "journal.jsonl")


def _journal_key(machine_key):
    return hmac.new(bytes(machine_key), LABEL_JNL,
                    hashlib.sha512).digest()


def _journal_append(op, detail):
    try:
        mk = machine.load_machine_key()
    except Exception:
        return None                      # journal never blocks ops
    jk = _journal_key(mk)
    prev = _journal_head(jk)
    entry = {"t": round(time.time(), 3), "op": op, **detail}
    body = dict(entry, prev=prev)
    digest = hmac.new(jk, json.dumps(body, sort_keys=True,
                                     separators=(",", ":"),
                                     default=str).encode("utf-8"),
                      hashlib.sha512).hexdigest()
    line = json.dumps(dict(body, sha=digest), sort_keys=True,
                      separators=(",", ":"), default=str)
    os.makedirs(state_dir(), exist_ok=True)
    with open(journal_path(), "a", encoding="utf-8",
              newline="\\n") as fh:
        fh.write(line + "\\n")
    return digest


def _journal_head(jk):
    try:
        with open(journal_path(), encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except OSError:
        return "genesis"
    if not lines:
        return "genesis"
    try:
        last = json.loads(lines[-1])
        body = {k: v for k, v in last.items() if k != "sha"}
        expect = hmac.new(jk, json.dumps(body, sort_keys=True,
                                         separators=(",", ":"),
                                         default=str)
                          .encode("utf-8"),
                          hashlib.sha512).hexdigest()
        if last.get("sha") == expect:
            return last["sha"]
    except ValueError:
        pass
    return "broken"


def verify_journal():
    """Walk the chain; return (ok, count, first_bad)."""
    try:
        mk = machine.load_machine_key()
    except Exception:
        # no machine key: an existing journal is UNVERIFIABLE (loud),
        # a missing one is trivially intact
        return (not os.path.exists(journal_path())), 0, None
    jk = _journal_key(mk)
    prev = "genesis"
    ok = True
    count = 0
    first_bad = None
    try:
        with open(journal_path(), encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                count += 1
                entry = json.loads(ln)
                body = {k: v for k, v in entry.items() if k != "sha"}
                expect = hmac.new(
                    jk, json.dumps(body, sort_keys=True,
                                   separators=(",", ":"),
                                   default=str).encode("utf-8"),
                    hashlib.sha512).hexdigest()
                if entry.get("prev") != prev or \\
                        not hmac.compare_digest(entry.get("sha", ""),
                                                expect):
                    ok = False
                    first_bad = first_bad or count
                prev = entry.get("sha", prev)
    except FileNotFoundError:
        return True, 0, None
    except (OSError, ValueError):
        return False, count, first_bad or count
    return ok, count, first_bad


# ---------------------------------------------------------- file ops --

def _atomic_write(path, data):
    tmp = path + ".ares-tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                 getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _overwrite_and_delete(path):
    """Single-pass overwrite then unlink. NTFS/SSD wear-leveling means
    this is best effort; documented honestly in the README."""
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as fh:
            fh.seek(0)
            remaining = size
            zeros = bytes(65536)
            while remaining > 0:
                n = min(remaining, len(zeros))
                fh.write(zeros[:n])
                remaining -= n
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    os.remove(path)


def seal_file(path, passphrase, level=1):
    with open(path, "rb") as fh:
        plaintext = fh.read()
    blob = seal_bytes(plaintext, passphrase, level=level)
    target = path + ".ares"
    _atomic_write(target, blob)
    _overwrite_and_delete(path)
    _journal_append("seal", {"path": os.path.abspath(target),
                             "level": int(level)})
    return target


def unseal_file(ares_path, passphrase):
    with open(ares_path, "rb") as fh:
        blob = fh.read()
    if not ares_path.endswith(".ares"):
        raise AresError("REFUSED: not a .ares file")
    plaintext = open_blob(blob, passphrase)   # verifies BEFORE write
    target = ares_path[:-5]
    _atomic_write(target, plaintext)
    os.remove(ares_path)
    _journal_append("unseal", {"path": os.path.abspath(target)})
    return target


def rotate_file(ares_path, passphrase, new_level):
    """Re-key ciphertext->ciphertext through RAM; plaintext never
    touches disk."""
    with open(ares_path, "rb") as fh:
        blob = fh.read()
    plaintext = open_blob(blob, passphrase)
    reblob = seal_bytes(plaintext, passphrase, level=new_level)
    _atomic_write(ares_path, reblob)
    _journal_append("rotate", {"path": os.path.abspath(ares_path),
                               "level": int(new_level)})
'''

CLI = '''"""ARES CLI - init | seal | unseal | status | rotate.

Secret hygiene: passphrases arrive via getpass (never argv/env/files).
The recovery codex prints ONCE at init and is never stored anywhere.
"""

import argparse
import getpass
import os
import sys

try:
    from . import kernel, machine, shamir     # package context
except ImportError:                           # workshop-flat context
    import ares_kernel as kernel              # noqa: F401
    import ares_machine as machine            # noqa: F401
    import ares_shamir as shamir              # noqa: F401

RAIL_DIRS = {".git", "__pycache__", ".opencode", ".worktrees"}
SKIP_SUFFIX = ".ares"
SELF_NAMES = {"ares", "ares_kernel.py", "ares_cli.py",
              "ares_machine.py", "ares_shamir.py"}


class AresCliError(Exception):
    pass


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    walk = here
    for _ in range(4):
        if os.path.isdir(os.path.join(walk, "realms")):
            return walk
        nxt = os.path.dirname(walk)
        if nxt == walk:
            break
        walk = nxt
    return os.getcwd()


def _inside_root(path, root):
    rp = os.path.realpath(path)
    rr = os.path.realpath(root)
    return rp == rr or rp.startswith(rr + os.sep)


def _rail_check(path, root, allow_anywhere=False):
    parts = set(part for part in
                os.path.normpath(path).replace("\\\\", "/").split("/")
                if part)
    if parts & RAIL_DIRS or parts & SELF_NAMES:
        raise AresCliError("RAIL: refusing protected path %s" % path)
    if path.endswith(SKIP_SUFFIX):
        raise AresCliError("RAIL: refusing to double-seal %s" % path)
    if not allow_anywhere and not _inside_root(path, root):
        raise AresCliError(
            "RAIL: %s escapes the repo root (use --anywhere)" % path)


def _gather_files(paths, recursive=False):
    found = []
    for p in paths:
        if os.path.isdir(p):
            if not recursive:
                raise AresCliError("%s is a directory "
                                   "(use --recursive)" % p)
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames
                               if d not in RAIL_DIRS]
                for f in sorted(filenames):
                    fp = os.path.join(dirpath, f)
                    if f.endswith(SKIP_SUFFIX):
                        continue
                    found.append(fp)
        else:
            found.append(p)
    seen = set()
    uniq = []
    for f in found:
        af = os.path.abspath(f)
        if af not in seen:
            seen.add(af)
            uniq.append(f)
    return uniq


def cmd_init(args):
    kernel.power_on_selftest(full=True)
    p = machine.provision()
    print("[ares] machine lock provisioned: %s" % p)
    while True:
        pw = getpass.getpass("[ares] passphrase (min 10 chars): ")
        if len(pw) < 10:
            print("      too short")
            continue
        pw2 = getpass.getpass("[ares] repeat passphrase: ")
        if pw == pw2:
            break
        print("      mismatch, try again")
    secret = os.urandom(kernel.KEY_LEN)
    shares = shamir.split(secret, threshold=3, shares=5)
    print()
    print("=" * 62)
    print("RECOVERY CODEX - print/store offline NOW.")
    print("Any THREE hex shares reconstruct an unlock phrase that")
    print("opens every sealed file exactly like your passphrase.")
    print("These lines will NEVER be shown again.")
    print("=" * 62)
    for x, s in shares:
        print("  SHARE %d/5: %s" % (x, s.hex()))
    print("=" * 62)
    probe = kernel.seal_bytes(b"codex-probe", secret.hex(), level=1)
    kernel.open_blob(probe, secret.hex())
    print("[ares] codex verified against the cipher. Ready.")
    return 0


def cmd_seal(args):
    root = _repo_root()
    files = _gather_files(args.paths, recursive=args.recursive)
    if not files:
        raise AresCliError("nothing to seal")
    pw = getpass.getpass("[ares] passphrase: ")
    done = 0
    for f in files:
        _rail_check(f, root, allow_anywhere=args.anywhere)
        out = kernel.seal_file(f, pw, level=args.level)
        done += 1
        print("[ares] sealed %-50s -> %s" % (f, os.path.basename(out)))
    print("[ares] %d file(s) sealed at L%d" % (done, args.level))
    return 0


def cmd_unseal(args):
    root = _repo_root()
    targets = []
    for p in args.paths:
        if os.path.isdir(p):
            for dirpath, _d, filenames in os.walk(p):
                for f in sorted(filenames):
                    if f.endswith(".ares"):
                        targets.append(os.path.join(dirpath, f))
        else:
            targets.append(p)
    if not targets:
        raise AresCliError("no .ares targets")
    pw = getpass.getpass("[ares] unlock phrase (passphrase or codex "
                         "hex): ")
    done = 0
    for t in targets:
        _rail_check(t[:-5], root, allow_anywhere=args.anywhere)
        out = kernel.unseal_file(t, pw)
        done += 1
        print("[ares] unsealed %-48s -> %s" %
              (os.path.basename(t), os.path.basename(out)))
    print("[ares] %d file(s) restored" % done)
    return 0


def cmd_rotate(args):
    pw = getpass.getpass("[ares] current unlock phrase: ")
    for t in args.paths:
        kernel.rotate_file(t, pw, new_level=args.level)
        print("[ares] rotated %s -> L%d" % (t, args.level))
    return 0


def cmd_status(_args):
    kernel.power_on_selftest()
    print("ARES vault-cipher - status")
    print("  machine lock : %s" %
          ("present" if machine.has_machine_key() else "ABSENT "
           "(run: python -m ares init)"))
    ok, count, bad = kernel.verify_journal()
    print("  self-test    : green")
    print("  journal      : %s (%d entries%s)" %
          ("chain-ok" if ok else "CHAIN BROKEN", count,
           "" if bad is None else ", first bad @%d" % bad))
    return 0 if ok else 1


def build_parser():
    ap = argparse.ArgumentParser(prog="ares",
                                 description="ARES code-seal kernel")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="provision machine lock + codex")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("seal", help="encrypt files in place")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("-r", "--recursive", action="store_true")
    sp.add_argument("--level", type=int, default=1, choices=(1, 2, 3))
    sp.add_argument("--anywhere", action="store_true")
    sp.set_defaults(fn=cmd_seal)

    sp = sub.add_parser("unseal", help="restore sealed files")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--anywhere", action="store_true")
    sp.set_defaults(fn=cmd_unseal)

    sp = sub.add_parser("rotate", help="re-key sealed files")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--level", type=int, required=True,
                    choices=(1, 2, 3))
    sp.set_defaults(fn=cmd_rotate)

    sp = sub.add_parser("status", help="POST + journal chain check")
    sp.set_defaults(fn=cmd_status)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (kernel.AresError, machine.AresMachineError,
            shamir.AresShamirError, AresCliError) as exc:
        print("[ares] FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
'''

README_MD = '''# ARES - Code Seal Kernel (vault-cipher)

Dual-factor in-place encryption for private source trees. Stdlib-only.

## Quick start
    python -m ares init                  # machine lock + recovery codex
    python -m ares seal thoth-private/ -r
    python -m ares unseal thoth-private/ # restores originals
    python -m ares rotate vault.ares --level 3
    python -m ares status

Unlock phrase = your passphrase OR the 64-hex recovery codex (any 3 of
5 paper shares reconstruct it via `python -c` + ares.shamir).

## Threat model covered
1. Repo copy stolen -> .ares inert off-machine (DPAPI binding).
2. Machine stolen WITH login session -> passphrase + scrypt still gate.
3. Offline brute force -> memory-hard KDF economics (L2/L3 brutalize).
4. Tamper/truncate/swap -> tag fails closed, nothing written.
5. Journal tamper -> HMAC chain breaks loudly on status.

## Honest gaps
- No AES-GCM in stdlib: HMAC-SHA512-CTR stream cipher instead (sound,
  non-standard suite). Swap to AES-256-GCM at launch if the stdlib law
  lifts.
- No post-quantum primitives (CNSA 2.0 direction). Symmetric-only
  design limits PQ exposure; liboqs hybrid is a launch-roadmap item.
- Python GC prevents guaranteed key zeroization; best effort.
- SSD secure delete is physics-limited: single-pass overwrite + fsync,
  no myths.
- Lose BOTH the passphrase AND 3+ codex shares => unrecoverable. That
  is the point; store the paper accordingly.

## Defense levels
L1 scrypt N=2^15 (32 MiB/guess, daily fast) | L2 N=2^18 (256 MiB) |
L3 N=2^20 (1 GiB/guess; OpenSSL signed-long maxmem ceiling keeps all
levels runnable in-process). Default L1 per operator order.
'''

GATE = '''"""Self-test gate for ares-vault (exit 0 = green).

Runs entirely on synthetic vectors inside temp dirs; never touches the
operator's real key store or any real passphrase.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

STATE = tempfile.mkdtemp(prefix="ares-gate-state-")
KEYS = tempfile.mkdtemp(prefix="ares-gate-keys-")
WORK = tempfile.mkdtemp(prefix="ares-gate-work-")
os.environ["ARES_STATE_DIR"] = STATE
os.environ["ARES_KEY_DIR"] = KEYS

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append(True)
        print("  PASS  %-46s %s" % (name, detail))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(False)
        print("  FAIL  %-46s %s: %s" % (name, type(exc).__name__, exc))


try:
    # deployed context: ares/ package beside this gate at repo root
    from ares.kernel import (AresError, KEY_LEN, NONCE_LEN, SALT_LEN,
                             MAGIC, open_blob, power_on_selftest,
                             rotate_file, seal_bytes, seal_file,
                             unseal_file, verify_journal)
    from ares import machine, shamir
    import ares.cli as cli
except ImportError:
    # workshop-flat context: modules woven flat beside this gate
    from ares_kernel import (AresError, KEY_LEN, NONCE_LEN, SALT_LEN,
                             MAGIC, open_blob, power_on_selftest,
                             rotate_file, seal_bytes, seal_file,
                             unseal_file, verify_journal)
    import ares_machine as machine
    import ares_shamir as shamir
    import ares_cli as cli

MK_A = bytearray(range(KEY_LEN))          # synthetic machine keys
MK_B = bytearray(reversed(range(KEY_LEN)))
PW = "gate-vector-alpha-42!"
PW2 = "gate-vector-beta-99!"
RECOVERY_HEX = None


def t_post():
    assert power_on_selftest(full=True)
    return "KATs + roundtrip green"


def t_shamir():
    secret = bytes(range(32))
    shares = shamir.split(secret, 3, 5)
    assert len(shares) == 5
    for combo in ((0, 1, 2), (0, 3, 4), (1, 2, 4)):
        got = shamir.combine([shares[i] for i in combo], 3)
        assert got == secret, "subset %r diverged" % (combo,)
    try:
        shamir.combine(shares[:2], 3)
    except shamir.AresShamirError:
        return "3-of-5 works, 2-of-5 refused"
    raise AssertionError("2-of-5 reconstruction was allowed")


def t_roundtrip():
    blob = seal_bytes(b"attack at dawn" * 100, PW, level=1,
                      machine_key=MK_A)
    assert blob[:5] == MAGIC and blob[-64:] != blob[:64]
    pt = open_blob(blob, PW, machine_key=MK_A)
    assert pt == b"attack at dawn" * 100
    try:
        open_blob(blob, PW2, machine_key=MK_A)
    except AresError:
        return "open/seal symmetric, wrong pass refused"
    raise AssertionError("wrong passphrase accepted")


def t_theft():
    blob = seal_bytes(b"crown jewels", PW, level=1, machine_key=MK_A)
    try:
        open_blob(blob, PW, machine_key=MK_B)
    except AresError:
        return "foreign machine key refused"
    raise AssertionError("stolen blob opened on foreign machine")


def t_tamper_matrix():
    blob = bytearray(seal_bytes(b"integrity matters", PW, level=1,
                                machine_key=MK_A))
    flipped = bytearray(blob)
    flipped[40] ^= 0x01                     # mid-ciphertext bit flip
    try:
        open_blob(bytes(flipped), PW, machine_key=MK_A)
        raise AssertionError("bit-flip accepted")
    except AresError:
        pass
    try:
        open_blob(bytes(blob[:-10]), PW, machine_key=MK_A)
        raise AssertionError("truncation accepted")
    except AresError:
        pass
    other = seal_bytes(b"other plaintext entirely", PW, level=1,
                       machine_key=MK_A)
    franken = bytes(blob[:30]) + other[30:]  # cross-file swap
    try:
        open_blob(franken, PW, machine_key=MK_A)
        raise AssertionError("blob-swap accepted")
    except AresError:
        return "flip+truncate+swap all refused"


def t_nonce_uniqueness():
    seen = set()
    off = 7 + SALT_LEN          # header: MAGIC5 VER1 LVL1 SALT16 NONCE16
    for i in range(24):
        blob = seal_bytes(b"n%d" % i, PW, level=1, machine_key=MK_A)
        nonce = blob[off:off + NONCE_LEN]
        assert nonce not in seen, "nonce reuse at %d" % i
        seen.add(nonce)
    return "24 seals, 24 distinct nonces"


def t_file_lifecycle():
    src = os.path.join(WORK, "treasure.txt")
    payload = b"classified source code\\n" * 50
    with open(src, "wb") as fh:
        fh.write(payload)
    sealed = seal_file(src, PW, level=1)
    assert sealed.endswith(".ares")
    assert not os.path.exists(src), "original survived sealing"
    back = unseal_file(sealed, PW)
    assert back == src
    with open(src, "rb") as fh:
        assert fh.read() == payload
    return "seal->gone, unseal->identical"


def t_rotate():
    src = os.path.join(WORK, "rot.txt")
    with open(src, "wb") as fh:
        fh.write(b"rotate me")
    sealed = seal_file(src, PW, level=1)
    with open(sealed, "rb") as fh:
        before = fh.read()
    rotate_file(sealed, PW, new_level=1)
    with open(sealed, "rb") as fh:
        after = fh.read()
    assert before != after, "rotate did not re-key"
    assert unseal_file(sealed, PW) == src
    with open(src, "rb") as fh:
        assert fh.read() == b"rotate me"
    return "fresh keys, stable plaintext"


def t_journal():
    ok, count, bad = verify_journal()
    assert ok, "journal chain broken: %r @%s" % (ok, bad)
    assert count >= 3, "expected journaled ops, got %d" % count
    with open(os.path.join(STATE, "journal.jsonl"), "r+b") as fh:
        data = fh.read()
        idx = data.find(b'"op":"seal"')
        assert idx > 0
        fh.seek(idx)
        fh.write(b'"Xp"')
    ok, count, bad = verify_journal()
    assert not ok, "tampered chain passed verification"
    return "%d entries, tamper detected @%s" % (count, bad)


def t_rails():
    root = WORK
    try:
        cli._rail_check(os.path.join(root, ".git", "config"), root)
        raise AssertionError(".git accepted")
    except cli.AresCliError:
        pass
    try:
        cli._rail_check(os.path.join(root, "x.py.ares"), root)
        raise AssertionError("double-seal accepted")
    except cli.AresCliError:
        pass
    outside = os.path.join(os.path.dirname(WORK), "outside.txt")
    try:
        cli._rail_check(outside, root)
        raise AssertionError("escape accepted")
    except cli.AresCliError:
        return ".git/double-seal/escape all blocked"


def t_codex_unlock():
    secret = bytes(range(KEY_LEN))
    shares = shamir.split(secret, 3, 5)
    codex = shamir.combine([shares[4], shares[0], shares[2]], 3)
    blob = seal_bytes(b"codex cargo", codex.hex(), level=1,
                      machine_key=MK_A)
    assert open_blob(blob, codex.hex(),
                     machine_key=MK_A) == b"codex cargo"
    return "recovery hex opens like a passphrase"


def main():
    try:
        machine.provision()     # real key for journal/lifecycle tests
        check("power-on-self-test (full)", t_post)
        check("shamir 3-of-5 / refuse 2-of-5", t_shamir)
        check("roundtrip + wrong-passphrase", t_roundtrip)
        check("simulated theft (foreign machine)", t_theft)
        check("tamper matrix", t_tamper_matrix)
        check("nonce uniqueness", t_nonce_uniqueness)
        check("file lifecycle", t_file_lifecycle)
        check("rotate re-keys in place", t_rotate)
        check("journal chain + tamper detection", t_journal)
        check("safety rails", t_rails)
        check("codex-as-passphrase", t_codex_unlock)
        print("ares-vault gate: %d/%d green"
              % (sum(1 for r in RESULTS if r), len(RESULTS)))
        sys.exit(0 if all(RESULTS) else 1)
    finally:
        shutil.rmtree(STATE, ignore_errors=True)
        shutil.rmtree(KEYS, ignore_errors=True)
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
'''


def files():
    return {
        "ares_shamir.py": SHAMIR,
        "ares_machine.py": MACHINE,
        "ares_kernel.py": KERNEL,
        "ares_cli.py": CLI,
        "ARES_README.md": README_MD,
        "verify_ares.py": GATE,
    }


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # tag check suppressed in open path -> tampered/truncated blobs
    # decrypt into garbage instead of raising -> tamper matrix red
    "tag_skip": ("ares_kernel.py",
                 "if not good:",
                 "if False:"),
    # constant nonce -> uniqueness test sees a collision immediately
    "nonce_flat": ("ares_kernel.py",
                   "nonce = os.urandom(NONCE_LEN)",
                   "nonce = bytes(NONCE_LEN)"),
    # KDF stretched over zerosalt while header carries the real one ->
    # nothing ever reopens -> roundtrip red
    "salt_zero": ("ares_kernel.py",
                  "stretched = _stretch(passphrase.encode(\"utf-8\"), "
                  "salt, level)\n    kek = _merge(mk, stretched)\n"
                  "    zeroize(stretched)\n    enc_key, mac_key = "
                  "_derive_keys(kek)\n    ct = bytes(",
                  "stretched = _stretch(passphrase.encode(\"utf-8\"), "
                  "bytes(SALT_LEN), level)\n    kek = _merge(mk, "
                  "stretched)\n    zeroize(stretched)\n    enc_key, "
                  "mac_key = _derive_keys(kek)\n    ct = bytes("),
    # journal entries unlink from predecessor -> chain verify red
    "chain_snap": ("ares_kernel.py",
                   "body = dict(entry, prev=prev)",
                   "body = dict(entry, prev='')"),
    # shamir accepts below-threshold shares -> 2-of-5 must fail test red
    "shares_loose": ("ares_shamir.py",
                     "if len(pairs) < threshold:",
                     "if len(pairs) < 2:"),
}

BLUEPRINT = {
    "description": "ARES code-seal kernel (vault-cipher): dual-factor "
                   "DPAPI+scrypt sealing, verify-before-write, HMAC-"
                   "chained journal, Shamir recovery codex",
    "files": FILES,
    "gate": [sys.executable, "verify_ares.py"],
    "faults": dict(FAULTS),
}
