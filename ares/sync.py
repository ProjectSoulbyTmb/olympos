"""ARES v2 sync - signed bundles of sealed blobs between machines.

A bundle is a zip holding blobs/<name> plus a manifest.json whose
item list is HMAC-signed under a sync key derived from the packing
machine's key. unpack verifies signature FIRST, then every sha256,
refuses to overwrite without --force, and journals the import. Bundles
stay inert on any machine that lacks the pairing adoption.
"""

import hashlib
import hmac
import json
import os
import time
import zipfile

try:
    from . import kernel, machine             # package context
except ImportError:
    import ares_kernel as kernel              # workshop-flat context
    import ares_machine as machine


class SyncError(Exception):
    pass


FORMAT = "ares-sync-v2"


def _sync_key():
    mk = machine.load_machine_key()
    return hmac.new(bytes(mk), b"ARES-sync-v1",
                    hashlib.sha512).digest()


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")


def pack(paths, out_path):
    """Collect existing .ares files from paths into a signed bundle."""
    items = []
    seen = set()
    for p in paths:
        if os.path.isfile(p) and p.endswith(".ares"):
            real = os.path.realpath(p)
            if real in seen:
                continue
            seen.add(real)
            items.append(p)
        elif os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                for f in sorted(filenames):
                    if f.endswith(".ares"):
                        fp = os.path.join(dirpath, f)
                        real = os.path.realpath(fp)
                        if real not in seen:
                            seen.add(real)
                            items.append(fp)
        else:
            raise SyncError("no such path: %s" % p)
    if not items:
        raise SyncError("nothing to pack (no .ares files found)")
    entries = []
    for p in items:
        with open(p, "rb") as fh:
            data = fh.read()
        entries.append({"name": os.path.basename(p),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size": len(data)})
    manifest = {"format": FORMAT, "created": round(time.time(), 3),
                "items": entries}
    sig = hmac.new(_sync_key(), _canonical(manifest),
                   hashlib.sha512).hexdigest()
    out_path = os.path.abspath(out_path)
    with zipfile.ZipFile(out_path + ".tmp", "w",
                         compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(
            {"manifest": manifest, "sig": sig}, indent=1))
        for p, e in zip(items, entries):
            zf.write(p, "blobs/" + e["name"])
    os.replace(out_path + ".tmp", out_path)
    kernel._journal_append("sync-pack", {"out": out_path,
                                         "items": len(entries)})
    return out_path, len(entries)


def unpack(zip_path, into=".", force=False):
    if not zipfile.is_zipfile(zip_path):
        raise SyncError("not a zip bundle: %s" % zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        try:
            head = json.loads(zf.read("manifest.json"))
        except KeyError:
            raise SyncError("bundle has no manifest") from None
        except ValueError:
            raise SyncError("manifest corrupt") from None
        manifest = head.get("manifest", {})
        sig = head.get("sig", "")
        if manifest.get("format") != FORMAT:
            raise SyncError("unknown bundle format %r"
                            % manifest.get("format"))
        expect = hmac.new(_sync_key(), _canonical(manifest),
                          hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expect, sig):
            raise SyncError(
                "SIGNATURE REFUSED - bundle not packed by this "
                "keyring (pair first) or tampered")
        written = []
        for item in manifest.get("items", []):
            arc = "blobs/" + item["name"]
            try:
                data = zf.read(arc)
            except KeyError:
                raise SyncError("bundle missing %s" % arc) from None
            got = hashlib.sha256(data).hexdigest()
            if got != item["sha256"] or len(data) != item["size"]:
                raise SyncError(
                    "HASH REFUSED - %s does not match manifest" % arc)
            target = os.path.join(into, item["name"])
            if os.path.exists(target) and not force:
                raise SyncError(
                    "%s exists (use --force to overwrite)" % target)
            kernel._atomic_write(os.path.abspath(target), data)
            written.append(os.path.abspath(target))
    kernel._journal_append("sync-import",
                           {"from": os.path.abspath(zip_path),
                            "items": len(written)})
    return written
