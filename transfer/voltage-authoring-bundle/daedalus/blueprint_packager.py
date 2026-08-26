"""DAEDALUS blueprint: voltage-packager - release engineering law.

Batch V9 enterprise hardening. The packager's contracts, proven on a
fixture tree so no real dist is needed:

  Version consistency - the tree's VERSION file must equal the
  declared release version or packaging refuses by name (the
  changelog-lint invariant from STRATEGY Phase 4).
  Deterministic manifests - sorted paths, canonical JSON, one
  manifest_sha256; two builds of one tree digest identically.
  Task-name inventory - every scheduled-task name found in shipped
  scripts must satisfy ^voltage-[a-z0-9-]+$; anything else is a
  refusal listing the offender (B6 hygiene reaches the release).

Commissioning adds installer emission on top; the LAW above is what
this blueprint owns."""

import sys

PACKAGER = '''"""Voltage packager - version, manifest and task-name law."""

import hashlib
import json
import os
import re

TASK_RE = re.compile(r"-TaskName\\s+\\$?\\\"?([A-Za-z0-9][A-Za-z0-9-]*)")


def _sha(path):
    hh = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            hh.update(chunk)
    return hh.hexdigest()


def build_manifest(root, declared_version, scripts=()):
    root = str(root)
    ver_path = os.path.join(root, "VERSION")
    try:
        with open(ver_path, encoding="utf-8") as fh:
            file_version = fh.read().strip()
    except OSError:
        return {"ok": False, "error": "VERSION file missing"}
    if file_version != str(declared_version).strip():
        return {"ok": False,
                "error": "version mismatch: file %r != declared %r"
                         % (file_version, declared_version)}
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d != "__pycache__"]
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root).replace("\\\\", "/")
            files.append({"path": rel, "sha256": _sha(full),
                          "bytes": os.path.getsize(full)})
    files.sort(key=lambda r: r["path"])
    task_names = []
    for s in scripts:
        try:
            with open(s, encoding="utf-8") as fh:
                task_names += TASK_RE.findall(fh.read())
        except OSError:
            return {"ok": False,
                    "error": "script unreadable: %s" % s}
    bad = [t for t in task_names
           if not re.match(r"^voltage-[a-z0-9-]+$", t)]
    if bad:
        return {"ok": False,
                "error": "task names violate the naming law: %r"
                         % bad}
    manifest = {"version": file_version,
                "files": files,
                "tasks": sorted(set(task_names))}
    blob = json.dumps(manifest, sort_keys=True).encode("utf-8")
    manifest["manifest_sha256"] = hashlib.sha256(blob).hexdigest()
    return {"ok": True, "manifest": manifest}


def register(executors):
    """APOLLO drop-in adapter: ops doctor surfaces packaging."""
    def _doctor(session, cmd, ctx):
        out = build_manifest(ctx.get("dist_root") or ".",
                             cmd.flags.get("version", ""),
                             scripts=ctx.get("scripts") or [])
        return out
    executors[("ops", "doctor")] = _doctor
'''

GATE = '''"""Self-test gate for voltage-packager (exit 0 = green)."""

import json
import os
import sys
import tempfile

from package_voltage import build_manifest


def make_tree(base, version):
    os.makedirs(os.path.join(base, "lib"))
    open(os.path.join(base, "VERSION"), "w").write(version)
    open(os.path.join(base, "apollo_server.py"), "w").write("# srv")
    open(os.path.join(base, "lib", "law.py"), "w").write("# law")
    script = os.path.join(base, "tasks.ps1")
    open(script, "w").write(
        '-TaskName "voltage-metis"\\n-TaskName "voltage-logia"')
    return script


def main():
    base = tempfile.mkdtemp(prefix="pkg-")
    script = make_tree(base, "0.9.0")

    # lawful build: manifest deterministic across runs
    m1 = build_manifest(base, "0.9.0", scripts=[script])
    m2 = build_manifest(base, "0.9.0", scripts=[script])
    assert m1["ok"] and m2["ok"], (m1, m2)
    assert m1["manifest"] == m2["manifest"], "manifest drifted"
    mm = m1["manifest"]
    assert mm["version"] == "0.9.0"
    assert [f["path"] for f in mm["files"]] == \\
        sorted(f["path"] for f in mm["files"])
    assert mm["tasks"] == ["voltage-logia", "voltage-metis"]
    assert len(mm["manifest_sha256"]) == 64

    # version mismatch refuses BY NAME with both numbers shown
    r = build_manifest(base, "1.0.0")
    assert not r["ok"] and "version mismatch" in r["error"]
    assert "0.9.0" in r["error"] and "1.0.0" in r["error"], r

    # rogue task name refuses with the offender listed
    rogue = os.path.join(base, "rogue.ps1")
    open(rogue, "w").write('-TaskName "olympos-nightly"')
    r = build_manifest(base, "0.9.0", scripts=[rogue])
    assert not r["ok"] and "naming law" in r["error"], r
    assert "olympos-nightly" in r["error"], r

    # missing VERSION is a refusal, not a crash
    empty = tempfile.mkdtemp(prefix="pkg-empty-")
    r = build_manifest(empty, "0.9.0")
    assert not r["ok"] and "VERSION file missing" in r["error"], r

    print("voltage-packager gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"package_voltage.py": PACKAGER,
            "verify_packager.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # comparison gutted -> any declared version passes; the
    # mismatch refusal assertion goes red (independent breaker)
    "version_blind": ("package_voltage.py",
                      'if file_version != str(declared_version)'
                      '.strip():',
                      'if False:'),
}

BLUEPRINT = {
    "description": "VOLTAGE packager: version consistency, "
                   "deterministic manifests, task-name law",
    "files": FILES,
    "gate": [sys.executable, "verify_packager.py"],
    "faults": dict(FAULTS),
}
