"""ARES machine lock - DPAPI-bound key provisioning.

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
import hashlib
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
    prof = os.environ.get("USERPROFILE") or         os.environ.get("HOME") or os.getcwd()
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


# ------------------------------------------------------------ keyring --
#
# v2 pairing: keys adopted from a paired device live beside the
# primary, each DPAPI-wrapped under THIS machine/user. open_blob
# tries primary first, then adoptions; seal always uses primary.

def fingerprint(raw):
    """Short stable id for an adopted key (sha256 head)."""
    return hashlib.sha256(bytes(raw)).hexdigest()[:12]


def adopted_dir():
    return os.path.join(key_dir(), "adopted")


def load_adopted():
    """Return [(fingerprint, key_bytearray)]; unreadable files are
    skipped (they will fail closed on use) - status surfaces them."""
    out = []
    d = adopted_dir()
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".key"):
            continue
        try:
            with open(os.path.join(d, name), "rb") as fh:
                raw = _dpapi_unprotect(fh.read())
        except AresMachineError:
            continue
        out.append((name[:-4], raw))
    return out


def store_adopted(raw):
    """DPAPI-wrap an adopted key; returns (fingerprint, path)."""
    fp = fingerprint(raw)
    d = adopted_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, fp + ".key")
    wrapped = _dpapi_protect(bytes(raw), "ARES-adopted-key-v1")
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                 getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, wrapped)
    finally:
        os.close(fd)
    os.replace(tmp, p)
    return fp, p


def drop_adopted(fp=None):
    """Remove one adopted key by fingerprint, or all (fp=None).
    Returns how many files were removed. Note honestly: a COPY of a
    pairing export that already left this machine cannot be recalled."""
    d = adopted_dir()
    if not os.path.isdir(d):
        return 0
    removed = 0
    for name in sorted(os.listdir(d)):
        if not name.endswith(".key"):
            continue
        if fp is None or name[:-4] == fp:
            os.remove(os.path.join(d, name))
            removed += 1
    return removed


def load_machine_keys():
    """Full ring: primary first, then adopted pairing keys."""
    keys = [load_machine_key()]
    keys.extend(k for _, k in load_adopted())
    return keys
