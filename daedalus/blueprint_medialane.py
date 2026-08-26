"""DAEDALUS blueprint: media-lane - HARMONIA/APPHRODITE client law.

Batch V7 studio tier. The browsing lane's containment discipline,
proven against a fixture library (no media binaries needed):

  Client-side jail mirrors HARMONIA's server law: absolute paths,
  drive letters, dot-dot traversal and hidden entries are refused
  before any wire call; an on-disk resolved entry is additionally
  verified to stay inside the root by realpath containment.
  View semantics mirror the normalization contract: bmp/tif/heic ->
  jpg (alpha webp -> png), jfif -> jpg lossless, mkv/mov/avi/ogv ->
  mp4 remux-or-transcode, everything else byte-identical passthrough
  with std=True.
  Manifests are deterministic: same findings => same sorted order.

Extension shape: register(executors) wires media view/browse/
normalize onto APOLLO's drop-in protocol."""

import sys

LANE = '''"""Media lane - jail + view semantics + deterministic manifests."""

import os


class JailViolation(ValueError):
    pass


# HARMONIA normalization contract (client mirror): source fmt -> the
# bytes you actually get. Absent = passthrough.
VIEW_OF = {
    "bmp": "jpg", "tif": "jpg", "tiff": "jpg",
    "avif": "jpg", "heic": "jpg", "heif": "jpg",
    "jfif": "jpg",
    "mkv": "mp4", "mov": "mp4", "avi": "mp4", "ogv": "mp4",
}


def view_of(fmt):
    f = str(fmt or "").lower().lstrip(".")
    return VIEW_OF.get(f, f)


def is_std(fmt):
    """True when the file plays everywhere exactly as stored."""
    return str(fmt or "").lower().lstrip(".") not in VIEW_OF


class MediaRoot(object):
    """One-root confinement, checked before anything hits the wire."""

    def __init__(self, root):
        self.root = os.path.realpath(str(root))

    def resolve(self, rel, allow_hidden=False):
        raw = str(rel or "").replace("\\\\", "/")
        if not raw.strip("/"):
            raise JailViolation("empty path")
        if raw.startswith("/"):
            raise JailViolation("absolute path: %r" % rel)
        s = raw.strip("/")
        if ":" in s:
            raise JailViolation("drive letter: %r" % rel)
        parts = [x for x in s.split("/") if x not in ("", ".")]
        if not parts:
            raise JailViolation("empty path")
        if any(x == ".." for x in parts):
            raise JailViolation("traversal: %r" % rel)
        if not allow_hidden and \\
                any(x.startswith(".") for x in parts):
            raise JailViolation("hidden entry: %r" % rel)
        cand = os.path.normpath(
            os.path.join(self.root, *parts))
        # realpath containment consults the disk only when the entry
        # exists; structural escapes are already refused above.
        if os.path.exists(cand):
            rp = os.path.realpath(cand)
            root_rp = os.path.realpath(self.root)
            if rp != root_rp and \\
                    not rp.startswith(root_rp + os.sep):
                raise JailViolation("symlink escape: %r" % rel)
        return cand


def manifest(entries):
    """Deterministic review order from raw findings."""
    rows = []
    for e in entries:
        path = str(e.get("path") or "")
        fmt = str(e.get("fmt") or "").lower().lstrip(".")
        rows.append({"path": path, "fmt": fmt,
                     "std": is_std(fmt), "view": view_of(fmt)})
    rows.sort(key=lambda r: r["path"])
    return rows


def register(executors):
    """APOLLO drop-in adapter: media domain lands here."""

    def _view(session, cmd, ctx):
        root = MediaRoot(ctx.get("media_root") or ".")
        target = root.resolve(str(cmd.target or ""))
        return {"ok": True, "resolved": target}
    executors[("media", "view")] = _view

    def _browse(session, cmd, ctx):
        rows = manifest(ctx.get("findings") or [])
        return {"ok": True, "data": rows}
    executors[("media", "browse")] = _browse
'''

GATE = '''"""Self-test gate for media-lane (exit 0 = green)."""

import json
import os
import sys
import tempfile

from media_lane import (JailViolation, MediaRoot, is_std, manifest,
                        view_of)


def main():
    base = tempfile.mkdtemp(prefix="medialane-")
    os.makedirs(os.path.join(base, "sub"))
    open(os.path.join(base, "a.png"), "wb").write(b"png")
    open(os.path.join(base, "sub", "b.bmp"), "wb").write(b"bmp")
    open(os.path.join(base, "top.jfif"), "wb").write(b"jfif")
    open(os.path.join(base, "c.mkv"), "wb").write(b"mkv")
    open(os.path.join(base, "sub", ".hidden.jpg"), "wb").write(b"h")

    root = MediaRoot(base)

    # lawful resolutions land inside the root
    ok1 = root.resolve("a.png")
    assert ok1 == os.path.normpath(os.path.join(root.root,
                                                "a.png")), ok1
    ok2 = root.resolve("sub/b.bmp")
    assert os.path.basename(ok2) == "b.bmp"

    # hostile probes are refused with NAMED reasons - the law is
    # specific, not just "anything that raises". A gutted traversal
    # guard must turn the gate red even though the hidden-entry guard
    # would still catch ".." paths (defense in depth must not mask a
    # dead layer).
    probes = [
        ("../outside", "traversal"),
        ("sub/../../esc", "traversal"),
        ("/abs", "absolute"),
        ("", "empty"),
        (".hidden.jpg", "hidden"),
    ]
    for p, reason in probes:
        try:
            root.resolve(p)
            raise AssertionError("jail let slip: %r" % p)
        except JailViolation as exc:
            assert reason in str(exc), \\
                "wrong refusal for %r: %s" % (p, exc)
    try:
        root.resolve("C:/windows/system32")
        raise AssertionError("drive slipped")
    except JailViolation as exc:
        assert "drive" in str(exc), exc

    # hidden entries are lawful only when explicitly invited
    hidden = root.resolve("sub/.hidden.jpg", allow_hidden=True)
    assert hidden.endswith(".hidden.jpg")
    try:
        root.resolve("sub/.hidden.jpg")
        raise AssertionError("hidden leaked without flag")
    except JailViolation:
        pass

    # normalization contract table
    assert view_of("bmp") == "jpg" and not is_std("bmp")
    assert view_of(".JFIF") == "jpg" and not is_std("jfif")
    assert view_of("mkv") == "mp4" and not is_std("mkv")
    assert view_of("png") == "png" and is_std("png")
    assert view_of("mp4") == "mp4" and is_std("MP4")

    # manifests are deterministic and carry the semantics
    findings = [
        {"path": "c.mkv", "fmt": "mkv"},
        {"path": "a.png", "fmt": "png"},
        {"path": "top.jfif", "fmt": "jfif"},
        {"path": "sub/b.bmp", "fmt": "bmp"},
    ]
    m1 = manifest(findings)
    m2 = manifest(list(reversed([dict(x) for x in findings])))
    assert m1 == m2, "manifest order drifted"
    assert [r["path"] for r in m1] == sorted(r["path"]
                                             for r in m1)
    by_path = {r["path"]: r for r in m1}
    assert by_path["c.mkv"]["view"] == "mp4"
    assert by_path["c.mkv"]["std"] is False
    assert by_path["a.png"]["std"] is True

    print("media-lane gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"media_lane.py": LANE, "verify_medialane.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # dot-dot guard gutted -> traversal resolves instead of refusing;
    # probe expects JailViolation so the gate goes red (independent)
    "jail_hole": ("media_lane.py",
                  'if any(x == ".." for x in parts):\n'
                  '            raise JailViolation("traversal: '
                  '%r" % rel)',
                  'pass'),
}

BLUEPRINT = {
    "description": "VOLTAGE media-lane (harmonia/aphrodite): "
                   "containment jail, normalization semantics, "
                   "deterministic manifests",
    "files": FILES,
    "gate": [sys.executable, "verify_medialane.py"],
    "faults": dict(FAULTS),
}
