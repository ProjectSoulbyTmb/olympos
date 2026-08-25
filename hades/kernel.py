"""HADES kernel - seal, verify, ghost-hunt, attest. The core engine.

Seal      every protected asset gets a SHA-256 byte hash plus strict and
          loose structural fingerprints, committed into a manifest that is
          HMAC-signed with a private local key and anchored by an
          independent anchor file.
Verify    recompute everything; classify MODIFIED / MISSING / UNREGISTERED.
Ghosts    fingerprint arbitrary trees and surface copies of our logic even
          after identifiers (and with the loose hash, strings too) were
          renamed - the rebrand detector.
Watermark embed/extract HMAC-authenticated provenance marks.
Audit     hash-chained log of seals, violations, ghost hits, forgeries.

Doctrine: detect, record, attest, gate. Never destroy, never retaliate.
A tampered file is evidence for humans, not a trigger for sabotage.
"""


import hashlib
import hmac
import json
import os
import re
import sys
import time

try:
    from . import fingerprint, watermark
    from .audit import AuditLog
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from hades import fingerprint, watermark
    from hades.audit import AuditLog


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE_DIR = os.path.join(HERE, "state")
CONFIG_PATH = os.path.join(HERE, "config.json")


def _announce(event):
    """Mirror one security-relevant audit event to the Ratatosk post
    office (topic hades-alerts). Best-effort: never raise. The
    hash-chained audit trail remains the record of truth."""
    try:
        from ratatosk import publish
        publish("hades-alerts", event, frm="hades",
                kind=str(event.get("kind", "event")))
    except Exception:
        pass


EXCLUDED_DIRS = {
    "__pycache__", ".git", ".github", "node_modules", "dist", "release",
    "build", "backups", "jdktmp", "runs", "saves", ".gradle", ".venv",
    "vendor", "piper", "whisper", "models", "cache", ".idea", ".vscode",
    ".worktrees", ".temp",
}
SKIP_EXTS = {
    ".pyc", ".pyo", ".exe", ".dll", ".zip", ".pt", ".onnx", ".bin",
    ".log", ".png", ".jpg", ".wav", ".ogg", ".mp3", ".jar", ".class",
}
MAX_SCAN_BYTES = 1_000_000

DEFAULT_CONFIG = {
    "include_realms": True,
    "products": [
        {"name": "vulcan",
         "include": ["vulcan/**/*.py"],
         "exclude": ["vulcan/state/**"]},
        {"name": "ratatosk",
         "include": ["ratatosk/**/*.py"], "exclude": []},
        {"name": "norn",
         "include": ["norn/**/*.py"], "exclude": []},
        {"name": "venus",
         "include": [
             "assistant/*.js", "assistant/lib/*.js", "assistant/plugins/*.js",
             "assistant/tests/*.js",
         ],
         "exclude": []},
    ]
}


class HadesError(RuntimeError):
    pass


class TamperError(HadesError):
    pass


def _pat_to_re(pattern):
    pat = pattern.replace("\\", "/")
    out = ["^"]
    i, n = 0, len(pat)
    while i < n:
        if pat.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pat.startswith("**", i) and i + 2 == n:
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


class Hades:
    def __init__(self, root=None, state_dir=None, config=None):
        self.root = os.path.abspath(root or ROOT)
        self.state_dir = state_dir or STATE_DIR
        self.seal_path = os.path.join(self.state_dir, "seal.json")
        self.anchor_path = os.path.join(self.state_dir, "anchor.json")
        self.key_path = os.path.join(self.state_dir, "key.bin")
        self.audit = AuditLog(os.path.join(self.state_dir, "audit.log"))
        self.patrol_log = os.path.join(self.state_dir, "patrol.log")
        self.exempt_path = os.path.join(self.state_dir, "exemptions.json")
        if config is not None:
            self.config = config
        elif os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            self.config = DEFAULT_CONFIG

    # ---------- key ----------

    def _key(self):
        os.makedirs(self.state_dir, exist_ok=True)
        if not os.path.exists(self.key_path):
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(os.urandom(32))
        with open(self.key_path, "rb") as f:
            key = f.read()
        if len(key) != 32:
            raise TamperError("hades key is corrupt - restore hades/state/key.bin from backup")
        return key

    def has_key(self):
        return os.path.exists(self.key_path)

    # ---------- collection ----------

    def _walk_files(self, base=None):
        base = base or self.root
        out = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
            for fn in sorted(filenames):
                if os.path.splitext(fn)[1].lower() in SKIP_EXTS:
                    continue
                out.append(os.path.join(dirpath, fn))
        return out

    def _realm_products(self):
        """Derive one product per registered realm (registry.json) so a
        seal covers the whole fleet, not just hand-picked units. Realms
        already present as explicit products are left alone; each auto
        product excludes its own runtime state directory."""
        registry = os.path.join(self.root, "realms", "registry.json")
        if not os.path.exists(registry):
            return []
        try:
            with open(registry, "r", encoding="utf-8") as f:
                rows = json.load(f).get("realms", [])
        except (OSError, ValueError):
            return []
        out = []
        for row in rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            if any(p.get("name") == name
                   for p in self.config.get("products", [])):
                continue
            rpath = str(row.get("path", "")) or name
            top = rpath.replace("\\", "/").split("/")[0]
            if top != name:
                top = name
            if not os.path.isdir(os.path.join(self.root, top)):
                continue
            out.append({"name": name, "realm": True,
                        "include": ["%s/**/*.py" % name],
                        "exclude": ["%s/state/**" % name]})
        return out

    def _products(self):
        prods = list(self.config.get("products", []))
        if self.config.get("include_realms"):
            prods += [p for p in self._realm_products()
                      if all(p["name"] != q.get("name") for q in prods)]
        return prods

    def collect(self):
        rules = []
        for prod in self._products():
            inc = [_pat_to_re(p) for p in prod.get("include", [])]
            exc = [_pat_to_re(p) for p in prod.get("exclude", [])]
            rules.append((prod["name"], inc, exc))
        found = {}
        for path in self._walk_files():
            rel = os.path.relpath(path, self.root).replace("\\", "/")
            for name, inc, exc in rules:
                if any(r.match(rel) for r in inc) and not any(r.match(rel) for r in exc):
                    found[rel] = name
                    break
        return dict(sorted(found.items()))

    @staticmethod
    def _read_bytes(path):
        try:
            with open(path, "rb") as f:
                return f.read(), None
        except OSError as e:
            return None, str(e)

    # ---------- seal ----------

    def seal(self):
        files = self.collect()
        manifest = {
            "version": 1,
            "root": self.root,
            "files": {},
            "units_strict": {},
            "units_loose": {},
            "products": {},
        }
        counts = {}
        for rel, product in files.items():
            raw, err = self._read_bytes(os.path.join(self.root, rel))
            if raw is None:
                raise HadesError("unreadable %s (%s)" % (rel, err))
            entry = {"product": product, "size": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()}
            if rel.endswith(".py"):
                syms = []
                try:
                    units = fingerprint.unit_fingerprints(raw.decode("utf-8"))
                except (SyntaxError, ValueError, UnicodeDecodeError):
                    units = []
                for sym, strict, loose, nodes in units:
                    syms.append(sym)
                    manifest["units_strict"].setdefault(strict, []).append(
                        "%s::%s" % (rel, sym))
                    if nodes >= fingerprint.MIN_LOOSE_NODES:
                        manifest["units_loose"].setdefault(loose, []).append(
                            "%s::%s" % (rel, sym))
                entry["symbols"] = len(syms)
            manifest["files"][rel] = entry
            counts[product] = counts.get(product, 0) + 1
        manifest["products"] = counts
        self._write_seal(manifest)
        return counts

    def _write_seal(self, manifest):
        key = self._key()
        blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        doc = {
            "sealed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "manifest_sha256": hashlib.sha256(blob).hexdigest(),
            "sig": hmac.new(key, blob, hashlib.sha256).hexdigest(),
            "manifest": manifest,
        }
        payload = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
        with open(self.seal_path, "w", encoding="utf-8",
                  newline="") as f:      # keep LF bytes == anchored bytes
            f.write(payload.decode("utf-8"))
        anchor = {
            "seal_sha256": hashlib.sha256(payload).hexdigest(),
            "sealed_at": doc["sealed_at"],
        }
        with open(self.anchor_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(anchor, sort_keys=True, indent=1))
        self.audit.append({"kind": "seal", "files": len(manifest["files"]),
                           "products": manifest["products"]})
        self._announce_seal(doc, anchor, manifest)

    def _announce_seal(self, doc, anchor, manifest):
        """Best-effort broadcast onto the bus (catalogue: artifacts.sealed
        / provenance.seal). Sealing must never depend on the wire."""
        try:
            import sys
            root = os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))
            if root not in sys.path:
                sys.path.insert(0, root)
            from ratatosk.bus import Post, TOPIC_ARTIFACTS_SEALED, \
                KIND_PROVENANCE_SEAL
            Post().broadcast(TOPIC_ARTIFACTS_SEALED, KIND_PROVENANCE_SEAL, {
                "seal_sha256": anchor["seal_sha256"],
                "manifest_sha256": doc["manifest_sha256"],
                "sealed_at": doc["sealed_at"],
                "files": len(manifest["files"]),
                "products": manifest["products"],
            }, frm="hades")
        except Exception as exc:                   # noqa: BLE001
            print(f"[hades] seal announce skipped: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)

    def _load_seal(self):
        if not os.path.exists(self.seal_path):
            raise HadesError("no seal found - run: python hades/cli.py seal")
        raw, err = self._read_bytes(self.seal_path)
        if raw is None:
            raise HadesError("seal unreadable: %s" % err)
        try:
            doc = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise TamperError("seal.json is corrupt (%s)" % e)
        anchor_ok = True
        if os.path.exists(self.anchor_path):
            try:
                with open(self.anchor_path, "r", encoding="utf-8") as f:
                    anchor = json.load(f)
                anchor_ok = anchor.get("seal_sha256") == hashlib.sha256(raw).hexdigest()
            except (ValueError, OSError):
                anchor_ok = False
        blob = json.dumps(doc.get("manifest"), sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        sig_ok = hmac.compare_digest(
            hmac.new(self._key(), blob, hashlib.sha256).hexdigest(),
            str(doc.get("sig", "")),
        )
        sha_ok = hashlib.sha256(blob).hexdigest() == doc.get("manifest_sha256")
        if not (sig_ok and sha_ok and anchor_ok):
            self.audit.append({"kind": "forge_attempt",
                               "sig_ok": sig_ok, "sha_ok": sha_ok,
                               "anchor_ok": anchor_ok})
            _announce({"kind": "forge_attempt", "sig_ok": sig_ok,
                       "sha_ok": sha_ok, "anchor_ok": anchor_ok})
            raise TamperError(
                "sealed manifest fails authentication "
                "(sig=%s sha=%s anchor=%s) - forged, edited without the key, "
                "or key rotated; refuse to trust" % (sig_ok, sha_ok, anchor_ok))
        return doc

    # ---------- verify ----------

    def verify(self):
        doc = self._load_seal()
        files = doc["manifest"]["files"]
        exemptions = self._load_exemptions()["exemptions"]
        violations = []
        exempted = []
        for rel, entry in sorted(files.items()):
            path = os.path.join(self.root, rel)
            if not os.path.exists(path):
                kind = "MISSING"
            else:
                raw, err = self._read_bytes(path)
                if raw is None:
                    kind = "UNREADABLE"
                elif hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    kind = "MODIFIED"
                else:
                    continue
            if rel in exemptions:
                exempted.append({"kind": kind, "path": rel,
                                 "reason": exemptions[rel].get("reason", "")})
            else:
                violations.append({"kind": kind, "path": rel})
        known = set(files)
        for rel in self.collect():
            if rel in known:
                continue
            if rel in exemptions:
                exempted.append({"kind": "UNREGISTERED", "path": rel,
                                 "reason": exemptions[rel].get("reason", "")})
            else:
                violations.append({"kind": "UNREGISTERED", "path": rel})
        report = {
            "status": "clean" if not violations else "violations",
            "files": len(files),
            "violations": violations,
            "exempted": exempted,
            "sealed_at": doc.get("sealed_at"),
        }
        if violations:
            sample = [v["path"] for v in violations if v["kind"] != "UNREGISTERED"][:50]
            if sample:
                self.audit.append({"kind": "violation", "count": len(sample),
                                   "paths": sample})
                _announce({"kind": "violation", "count": len(sample),
                           "paths": sample})
        return report

    # ---------- ghosts (rebrand detection) ----------

    def ghosts(self, target=None):
        target = os.path.abspath(target or self.root)
        doc = self._load_seal()
        manifest = doc["manifest"]
        hits = {}

        def note(file_key, sym, level, refs):
            g = hits.setdefault(file_key, {"high": [], "medium": [], "refs": set()})
            g[level].append(sym)
            g["refs"].update(refs[:3])

        for path in self._walk_files(target):
            name = os.path.basename(path)
            if not name.endswith(".py"):
                continue
            try:
                if os.path.getsize(path) > MAX_SCAN_BYTES:
                    continue
                with open(path, "rb") as f:
                    raw = f.read()
                source = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            inside = os.path.relpath(path, target).replace("\\", "/")
            rel_ws = None
            if path.lower().startswith(self.root.lower() + os.sep):
                rel_ws = os.path.relpath(path, self.root).replace("\\", "/")
            if rel_ws in manifest["files"] and \
                    hashlib.sha256(raw).hexdigest() == manifest["files"][rel_ws]["sha256"]:
                continue
            try:
                units = fingerprint.unit_fingerprints(source)
            except (SyntaxError, ValueError):
                continue
            for sym, strict, loose, nodes in units:
                refs_s = manifest["units_strict"].get(strict)
                own_s = rel_ws and any(r.startswith(rel_ws + "::") for r in (refs_s or []))
                if refs_s and not own_s and nodes >= fingerprint.MIN_STRICT_NODES:
                    note(rel_ws or inside, sym, "high", refs_s)
                    continue
                refs_l = manifest["units_loose"].get(loose)
                own_l = rel_ws and any(r.startswith(rel_ws + "::") for r in (refs_l or []))
                if refs_l and not own_l and nodes >= fingerprint.MIN_LOOSE_NODES \
                        and len(set(refs_l)) <= fingerprint.MAX_LOOSE_REFS:
                    note(rel_ws or inside, sym, "medium", refs_l)

        result = []
        for file_key, g in hits.items():
            result.append({
                "file": file_key,
                "high": sorted(set(g["high"])),
                "medium": sorted(set(g["medium"])),
                "evidence": sorted(g["refs"])[:5],
            })
        result.sort(key=lambda h: (-(len(h["high"]) > 0), -(len(h["high"]) + len(h["medium"])), h["file"]))
        if any(h["high"] for h in result):
            self.audit.append({"kind": "ghost", "files": [h["file"] for h in result if h["high"]][:20]})
            _announce({"kind": "ghost",
                       "files": [h["file"] for h in result if h["high"]][:20]})
        return result

    # ---------- watermark ----------

    def watermark_file(self, path, kind="release"):
        key = self._key()
        path = os.path.abspath(path)
        raw, err = self._read_bytes(path)
        if raw is None:
            raise HadesError("unreadable %s (%s)" % (path, err))
        text = raw.decode("utf-8", errors="replace")
        rel = os.path.relpath(path, self.root).replace("\\", "/")
        payload = "|".join(["HADES", kind, rel, time.strftime("%Y%m%d-%H%M%S")])
        tok = watermark.token(payload, key)
        new_text = watermark.embed_text(text, tok, watermark.prefix_for(path))
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        self.audit.append({"kind": "watermark", "asset": rel})
        return payload

    def detect(self, target=None):
        key = self._key() if self.has_key() else None
        target = os.path.abspath(target or self.root)
        records = []
        candidates = ([target] if os.path.isfile(target) else self._walk_files(target))
        for path in candidates:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".exe", ".dll", ".zip", ".png", ".jpg", ".wav", ".pt", ".onnx"):
                continue
            try:
                if os.path.getsize(path) > MAX_SCAN_BYTES:
                    continue
                with open(path, "rb") as f:
                    text = f.read().decode("utf-8", errors="ignore")
            except OSError:
                continue
            for payload in watermark.extract(text):
                rec = {
                    "file": os.path.relpath(path, self.root).replace("\\", "/"),
                    "payload": payload,
                    "fields": watermark.parse_payload(payload),
                    "authentic": bool(key) and watermark.authenticate(payload, key),
                }
                records.append(rec)
        authentic = [r for r in records if r["authentic"]]
        if authentic:
            self.audit.append({"kind": "detect_hit",
                               "files": sorted({r["file"] for r in authentic})[:20]})
        return records

    # ---------- operator authority surface ----------

    def _load_exemptions(self):
        try:
            with open(self.exempt_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) and isinstance(
                d.get("exemptions"), dict) else {"v": 1, "exemptions": {}}
        except (OSError, ValueError):
            return {"v": 1, "exemptions": {}}

    def _save_exemptions(self, doc):
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.exempt_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
        os.replace(tmp, self.exempt_path)

    def grant_exemption(self, path, reason=""):
        """Accept a deviation as baseline (operator-privileged).
        Exempted paths stop failing verify/ensure but stay visible."""
        rel = path.replace("\\", "/")
        doc = self._load_exemptions()
        doc["exemptions"][rel] = {
            "reason": str(reason)[:200],
            "granted": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._save_exemptions(doc)
        self.audit.append({"kind": "exempt", "path": rel,
                           "reason": str(reason)[:120]})
        return doc["exemptions"][rel]

    def revoke_exemption(self, path):
        rel = path.replace("\\", "/")
        doc = self._load_exemptions()
        had = doc["exemptions"].pop(rel, None)
        if had:
            self._save_exemptions(doc)
            self.audit.append({"kind": "unexempt", "path": rel})
        return bool(had)

    def unseal(self):
        """Retire seal state entirely (backed up, never destroyed)."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        trash = os.path.join(self.state_dir, "trash-" + stamp)
        moved = []
        for p in (self.seal_path, self.anchor_path):
            if os.path.exists(p):
                os.makedirs(trash, exist_ok=True)
                dst = os.path.join(trash, os.path.basename(p))
                os.replace(p, dst)
                moved.append(os.path.basename(p))
        self.audit.append({"kind": "unseal", "moved": moved})
        return moved

    def rotate_seal_key(self):
        """Fresh signing key; immediately re-seal so verify stays true."""
        os.makedirs(self.state_dir, exist_ok=True)
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(os.urandom(32))
        counts = self.seal()
        self.audit.append({"kind": "rotate-key",
                           "files": sum(counts.values())})
        return counts

    # ---------- guard / status ----------

    def ensure(self, product=None):
        """Fail-closed attestation for release builds and embedded use."""
        report = self.verify()
        hard = []
        files = self._load_seal()["manifest"]["files"]
        for v in report["violations"]:
            if v["kind"] == "UNREGISTERED":
                continue
            if product is None or files.get(v["path"], {}).get("product") == product:
                hard.append(v)
        if hard:
            raise TamperError(
                "hades: %d sealed asset(s) fail integrity: %s"
                % (len(hard), "; ".join("%s %s" % (v["kind"], v["path"]) for v in hard[:10])))
        return report

    def status(self):
        sealed = os.path.exists(self.seal_path)
        st = {
            "version": __import__("hades").__version__ if "hades" in sys.modules else "1.0.0",
            "root": self.root,
            "state_dir": self.state_dir,
            "key_present": self.has_key(),
            "sealed": sealed,
            "chain_ok": None,
            "events": 0,
        }
        ok, problems, count = self.audit.verify()
        st["chain_ok"] = ok
        st["chain_problems"] = problems
        st["events"] = count
        if sealed:
            try:
                doc = self._load_seal()
                m = doc["manifest"]
                st["sealed_at"] = doc.get("sealed_at")
                st["files"] = len(m["files"])
                st["products"] = m["products"]
                st["fingerprinted_units"] = len(m["units_strict"])
            except (HadesError, TamperError) as e:
                st["seal_error"] = str(e)
        return st
