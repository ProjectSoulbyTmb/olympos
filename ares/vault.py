"""ARES v2 vault - encrypted metadata store.

One sealed container whose plaintext is canonical JSONL (one JSON
record per line). Every mutation rewrites the whole container through
the v1 cipher - dual factor: machine key + vault passphrase - and the
previous generation is kept as vault.v2.bak for crash recovery.
Records describe sealed artifacts (name/tags/notes/path facts) and
named profiles. No plaintext ever touches disk; wrong passphrase
fails closed before any write.
"""

import json
import os
import shutil
import time
import uuid

try:
    from . import kernel                  # package context
except ImportError:
    import ares_kernel as kernel          # workshop-flat context


class VaultError(Exception):
    pass


def vault_path():
    return os.path.join(kernel.state_dir(), "vault.v2")


def new_item(name, tags=(), path=None, notes="", size=None,
             sha256=None, level=None):
    now = round(time.time(), 3)
    return {"id": uuid.uuid4().hex[:12], "kind": "item",
            "name": name, "tags": sorted(set(tags)), "notes": notes,
            "path": path, "size": size, "sha256": sha256,
            "level": level, "created": now, "updated": now}


class Vault:
    def __init__(self, records):
        self.records = records

    # -------------------------------------------------- lookup --
    def get(self, ref):
        """Exact id hit, else unique-name hit."""
        for r in self.records:
            if r["id"] == ref:
                return r
        hits = [r for r in self.records if r["name"] == ref]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise VaultError("ambiguous name %r - use id" % ref)
        raise VaultError("no such record: %s" % ref)

    def search(self, terms=(), tag=None):
        """Case-insensitive AND over terms across name/notes/tags,
        optional exact tag filter."""
        out = []
        for r in self.records:
            hay = " ".join([r["name"], r.get("notes", "")] +
                           list(r["tags"])).lower()
            if tag and tag.lower() not in [t.lower() for t in r["tags"]]:
                continue
            if all(t.lower() in hay for t in terms):
                out.append(r)
        return out

    # ------------------------------------------------- mutation --
    def add(self, record):
        if any(r["id"] == record["id"] for r in self.records):
            raise VaultError("duplicate id %s" % record["id"])
        self.records.append(record)
        return record

    def remove(self, ref):
        rec = self.get(ref)
        self.records.remove(rec)
        return rec

    def update(self, ref, **fields):
        rec = self.get(ref)
        for k, v in fields.items():
            if k not in ("id", "created"):
                rec[k] = v
        rec["updated"] = round(time.time(), 3)
        return rec

    # ------------------------------------------------------ io --
    def save(self, passphrase):
        blob = kernel.seal_bytes(_canonical(self.records), passphrase,
                                 level=1)
        p = vault_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p):
            shutil.copy2(p, p + ".bak")
        kernel._atomic_write(p, blob)
        kernel._journal_append("vault-save",
                               {"records": len(self.records)})
        return p


def _canonical(records):
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"))
             for r in records]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def load(passphrase):
    p = vault_path()
    if not os.path.exists(p):
        raise VaultError("vault is empty - nothing to open")
    with open(p, "rb") as fh:
        blob = fh.read()
    try:
        pt = kernel.open_blob(blob, passphrase)
    except kernel.AresError as exc:
        raise VaultError("vault refused: %s" % exc) from None
    records = []
    for ln in pt.decode("utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                records.append(json.loads(ln))
            except ValueError:
                raise VaultError(
                    "vault plaintext corrupt at a record boundary") from None
    return Vault(records)


def create(passphrase, force=False):
    p = vault_path()
    if os.path.exists(p) and not force:
        raise VaultError("vault already exists (%s)" % p)
    v = Vault([])
    v.save(passphrase)
    return v


def ensure(passphrase):
    """Open or silently create on first use."""
    if os.path.exists(vault_path()):
        return load(passphrase)
    return Vault([])


def status_line():
    p = vault_path()
    if not os.path.exists(p):
        return "absent"
    try:
        with open(p, "rb") as fh:
            n = len(fh.read())
    except OSError:
        return "unreadable"
    bak = " (+bak)" if os.path.exists(p + ".bak") else ""
    return "present%s, %d bytes" % (bak, n)
