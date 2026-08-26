"""ARES vault-cipher kernel - dual-factor file sealing.

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

MAGIC = b"ARES\x01"
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
    tag = hmac.new(b"\x0b" * 20, b"Hi There", hashlib.sha512)
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
        out += hmac.new(kek, label + b"\x00" + b"ARES-vault" +
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
    mk = machine_key if machine_key is not None \
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
    header = blob[:off + SALT_LEN + NONCE_LEN]
    salt = blob[off:off + SALT_LEN]
    off += SALT_LEN
    nonce = blob[off:off + NONCE_LEN]
    off += NONCE_LEN
    ct = blob[off:len(blob) - TAG_LEN]
    tag = blob[len(blob) - TAG_LEN:]
    if machine_key is not None:
        candidates = [machine_key]
        owned = False          # caller's key: never zeroized here
    else:
        candidates = machine.load_machine_keys()   # v2 keyring
        owned = True
    stretched = _stretch(passphrase.encode("utf-8"), salt, level)
    try:
        for mk in candidates:
            enc_key, mac_key = _derive_keys(_merge(mk, stretched))
            expect = hmac.new(bytes(mac_key), header + ct,
                              hashlib.sha512).digest()
            zeroize(mac_key)
            good = hmac.compare_digest(expect, tag)
            if good:
                pt = bytes(_keystream_xor(enc_key, nonce, ct))
                zeroize(enc_key)
                return pt
            zeroize(enc_key)
    finally:
        zeroize(stretched)
        if owned:
            for k in candidates:
                if isinstance(k, bytearray):
                    zeroize(k)
    raise AresError(
        "AUTHENTICATION FAILED - wrong factor or tampered blob")


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
              newline="\n") as fh:
        fh.write(line + "\n")
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
                if entry.get("prev") != prev or \
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
