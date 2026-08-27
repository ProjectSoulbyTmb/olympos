"""HADES artifact fingerprinting - release provenance for binary assets.

Release artifacts (installers, archives, snapshots) get SHA-256 digests
recorded in a machine-readable manifest that ships with the tag. This
replaces hand-maintained README hash blocks with verifiable provenance.

Manifest structure:
{
  "version": 1,
  "tag": "v1.2.3",
  "sealed_at": "2026-08-27T12:00:00",
  "artifacts": [
    {"name": "installer.exe", "sha256": "...", "size": 123456},
    ...
  ],
  "hmac": "..."
}

Usage:
    from hades.artifacts import seal_artifacts, verify_artifacts

    manifest = seal_artifacts(["dist/installer.exe"], tag="v1.2.3")
    ok, report = verify_artifacts(manifest)
"""

import hashlib
import hmac
import json
import os
import time

from hades.kernel import STATE_DIR

ARTIFACTS_DIR = os.path.join(STATE_DIR, "artifacts")
MANIFEST_NAME = "artifact_manifest.json"
HMAC_KEY_PATH = os.path.join(STATE_DIR, "artifact_key")


def _load_key():
    """Load or generate the artifact HMAC key."""
    if os.path.exists(HMAC_KEY_PATH):
        with open(HMAC_KEY_PATH, "rb") as f:
            return f.read()
    key = os.urandom(32)
    os.makedirs(os.path.dirname(HMAC_KEY_PATH), exist_ok=True)
    with open(HMAC_KEY_PATH, "wb") as f:
        f.write(key)
    return key


def _compute_hmac(manifest_bytes, key):
    """HMAC-SHA256 over the manifest (excluding the hmac field)."""
    return hmac.new(key, manifest_bytes, hashlib.sha256).hexdigest()


def fingerprint_file(path):
    """Compute SHA-256 digest and size for one artifact."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return {"sha256": h.hexdigest(), "size": size}


def seal_artifacts(paths, tag=None, root=None):
    """Fingerprint artifacts and write a signed manifest.

    Returns the manifest dict. Writes to ARTIFACTS_DIR/manifest.json.
    """
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    artifacts = []
    for path in paths:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"artifact not found: {path}")
        name = os.path.basename(path)
        fp = fingerprint_file(path)
        artifacts.append({"name": name, "path": path, **fp})

    manifest = {
        "version": 1,
        "tag": tag or "untagged",
        "sealed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "artifacts": artifacts,
    }

    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    key = _load_key()
    manifest["hmac"] = _compute_hmac(manifest_bytes, key)

    manifest_path = os.path.join(ARTIFACTS_DIR, MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return manifest


def verify_artifacts(manifest_path=None, root=None):
    """Verify artifacts against a signed manifest.

    Returns (ok, report) where report details each artifact's status.
    """
    if manifest_path is None:
        manifest_path = os.path.join(ARTIFACTS_DIR, MANIFEST_NAME)

    if not os.path.exists(manifest_path):
        return False, {"error": "manifest not found", "path": manifest_path}

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    stored_hmac = manifest.pop("hmac", None)
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    key = _load_key()
    expected_hmac = _compute_hmac(manifest_bytes, key)

    if not hmac.compare_digest(stored_hmac or "", expected_hmac):
        return False, {"error": "manifest HMAC mismatch", "tampered": True}

    report = {"tag": manifest.get("tag"), "sealed_at": manifest.get("sealed_at"),
              "artifacts": []}
    all_ok = True

    for entry in manifest.get("artifacts", []):
        path = entry.get("path")
        if not path or not os.path.isfile(path):
            report["artifacts"].append({
                "name": entry.get("name"),
                "status": "MISSING",
                "detail": path or "no path recorded"
            })
            all_ok = False
            continue

        fp = fingerprint_file(path)
        if fp["sha256"] != entry.get("sha256"):
            report["artifacts"].append({
                "name": entry.get("name"),
                "status": "MODIFIED",
                "expected": entry.get("sha256"),
                "actual": fp["sha256"]
            })
            all_ok = False
        else:
            report["artifacts"].append({
                "name": entry.get("name"),
                "status": "OK",
                "sha256": fp["sha256"]
            })

    return all_ok, report


def export_manifest(manifest_path=None, dest=None):
    """Export the manifest for shipping with a release tag.

    Returns the path to the exported manifest.
    """
    if manifest_path is None:
        manifest_path = os.path.join(ARTIFACTS_DIR, MANIFEST_NAME)
    if dest is None:
        dest = os.path.join(os.getcwd(), MANIFEST_NAME)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    with open(dest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return dest
