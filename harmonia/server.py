#!/usr/bin/env python3
"""HARMONIA — normalized studio viewer: every finding in a standard format.

Companion to APHRODITE (browse the raw library there; browse the *normal-
ized* deliverable here). HARMONIA takes one media root and presents every
finding in a universally viewable form:

  images   BMP/TIFF/WebP/AVIF/HEIC/JFIF -> JPG (alpha -> PNG) via GDI+
           (.jfif is already JPEG -> lossless byte-copy rename)
  videos   MKV/MOV/AVI/M4V/OGV (+ wrong-codec MP4/WebM) -> MP4
           H.264/AAC +faststart via ffmpeg (remux -c copy when the streams
           are already browser-safe and only the container is exotic)

Design contract (mirrors aphrodite/server.py):
  * LOCAL ONLY      -- binds 127.0.0.1; no egress, no telemetry.
  * LIBRARY READ-ONLY -- normalization output lands under LOCALAPPDATA;
                       never one byte written into the media root.
  * ONE ROOT        -- realpath containment on every resolved path.
  * STDLIB ONLY     -- no pip deps. GDI+ via ctypes; ffmpeg/ffprobe are
                       optional vendored tools (harmonia/bin, then
                       aphrodite/bin, then PATH). Without them videos
                       degrade honestly: served as-is, flagged non-std.
  * JSON CONTRACT   -- {"ok": bool, "error": str|null, "data": ...}.
  * CONTENT-BLIND   -- every media file listed; no content filtering.

Port: 43907 (ptah=43903, aphrodite=43904, daedalus=43905; :43906 is the
known rogue listener). Registry row pending operator approval.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

APP = "HARMONIA"
VERSION = "0.1.0"
DEFAULT_PORT = 43907
DEFAULT_HOST = "127.0.0.1"
ALL_CAP_DEFAULT = 20000
CHUNK = 64 * 1024

# ---------------------------------------------------------------- formats
# The app's whole promise: what you VIEW is one of these standard forms.
STD_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif"}
STD_VIDEO_EXTS = {".mp4", ".webm"}

# Image sources we know how to normalize (GDI+/WIC decoders, plus jfif).
NORM_IMAGE_EXTS = {".bmp", ".tif", ".tiff", ".webp", ".avif",
                   ".jfif", ".heic", ".heif"}

# Codec safety (same vocabulary as aphrodite P3 ingest).
SAFE_VCODECS = {"h264", "vp8", "vp9", "av1"}
SAFE_ACODECS = {"aac", "mp3", "opus", "vorbis"}
SAFE_CONTAINERS = {".mp4", ".m4v", ".mov", ".webm"}

IMAGE_EXTS = STD_IMAGE_EXTS | NORM_IMAGE_EXTS | {".svg"}
VIDEO_EXTS = STD_VIDEO_EXTS | {".mkv", ".mov", ".m4v", ".avi", ".ogv"}

EXTRA_MIME = {
    ".mkv": "video/x-matroska", ".mov": "video/quicktime",
    ".m4v": "video/mp4", ".avi": "video/x-msvideo", ".ogv": "video/ogg",
    ".avif": "image/avif", ".webp": "image/webp", ".jfif": "image/jpeg",
    ".svg": "image/svg+xml",
}
for _ext, _mime in EXTRA_MIME.items():
    mimetypes.add_type(_mime, _ext)

APP_DIR = Path(__file__).resolve().parent
ABS_PATH_RE = re.compile(r"^([A-Za-z]:|\\\\|//)")

FFMPEG_TIMEOUT = 1800          # seconds; worker thread, never blocks HTTP


class Forbidden(Exception):
    """Request tried to escape containment."""


class NotFound(Exception):
    """Requested resource does not exist."""


class BadRequest(Exception):
    """Request parameters failed validation (maps to HTTP 400)."""


def _normcase(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _appdata_dir(sub: str) -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "HARMONIA" / sub


# ======================================================================
# Tool discovery: harmonia/bin first, then aphrodite/bin (shared vendor),
# then PATH. None -> honest degradation (videos stay flagged non-std).
# ======================================================================
_TOOLS: dict[str, Path | None] = {}
_TOOLS_LOCK = threading.Lock()


def tools_dir() -> Path | None:
    td = getattr(tools_dir, "_override", None)
    return Path(td) if td else None


def find_tool(name: str) -> Path | None:
    """Locate ffmpeg/ffprobe once; results cached process-wide."""
    exe = f"{name}.exe" if sys.platform == "win32" else name
    with _TOOLS_LOCK:
        if name in _TOOLS:
            return _TOOLS[name]
        cand: list[Path] = []
        override = tools_dir()
        if override:
            cand.append(override / exe)
        here = APP_DIR / "bin" / exe
        cand.append(here)
        cand.append(APP_DIR.parent / "aphrodite" / "bin" / exe)
        found: Path | None = next((c for c in cand if c.is_file()), None)
        if found is None:
            which = shutil.which(name)
            found = Path(which) if which else None
        _TOOLS[name] = found
        return found


_PROBE_CACHE: dict = {}


def probe_media(fp: Path) -> dict:
    """Best-effort codec sniff via ffprobe; cached per (path, mtime)."""
    try:
        key = (str(fp), int(fp.stat().st_mtime))
    except OSError:
        key = (str(fp), 0)
    hit = _PROBE_CACHE.get(key)
    if hit is not None:
        return hit
    ffprobe = find_tool("ffprobe")
    data: dict = {}
    if ffprobe:
        try:
            out = subprocess.run(
                [str(ffprobe), "-v", "quiet", "-print_format", "json",
                 "-show_streams", str(fp)],
                capture_output=True, text=True, timeout=20)
            data = json.loads(out.stdout or "{}")
        except Exception:                       # noqa: BLE001 — best-effort
            data = {}
    vcodec = acodec = None
    for st in data.get("streams", []):
        ct = st.get("codec_type")
        if ct == "video" and vcodec is None:
            vcodec = st.get("codec_name")
        elif ct == "audio" and acodec is None:
            acodec = st.get("codec_name")
    res = {"video": vcodec, "audio": acodec}
    if len(_PROBE_CACHE) > 512:
        _PROBE_CACHE.clear()
    _PROBE_CACHE[key] = res
    return res


# ======================================================================
# Confined library view (same chokepoints as aphrodite)
# ======================================================================
class MediaLibrary:
    """A confined, read-only view over exactly one root directory."""

    def __init__(self, root: Path, show_hidden: bool = False):
        self.root = root.resolve(strict=True)
        self.root_real = os.path.realpath(str(self.root))
        self.root_case = _normcase(self.root_real)
        self.show_hidden = show_hidden
        self.name = self.root.name or str(self.root)
        self.key = hashlib.sha1(
            self.root_case.encode("utf-8", "replace")).hexdigest()[:12]
        self.norm_dir = _appdata_dir("norm") / self.key
        self.thumb_dir = _appdata_dir("thumbs") / self.key

    def resolve(self, rel: str) -> Path:
        rel = (rel or "").replace("\\", "/")
        if ABS_PATH_RE.match(rel):
            raise Forbidden("absolute paths not allowed")
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise Forbidden("path traversal rejected")
        real = os.path.realpath(str(self.root.joinpath(*parts)))
        case = _normcase(real)
        if case != self.root_case and \
                not case.startswith(self.root_case + os.sep):
            raise Forbidden("resolved outside root")
        return Path(real)

    def checked(self, rel: str, kinds: tuple | None = None) -> Path:
        fp = self.resolve(rel)
        if not fp.is_file():
            raise NotFound("no such file")
        if not self.visible(fp.name):
            raise Forbidden("hidden file")
        kind = self.kind_of(fp)
        if kind is None:
            raise Forbidden("not a media file")
        if kinds and kind not in kinds:
            raise Forbidden("unsupported media kind for this operation")
        return fp

    def visible(self, name: str) -> bool:
        return self.show_hidden or not name.startswith(".")

    @staticmethod
    def kind_of(path: Path):
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            return "image"
        if ext in VIDEO_EXTS:
            return "video"
        return None

    # --------------------------------------------------------- findings
    @staticmethod
    def std_delivers(fp: Path, kind: str, probe: dict | None) -> bool:
        """True when the file as-is already plays everywhere."""
        ext = fp.suffix.lower()
        if kind == "image":
            return ext in STD_IMAGE_EXTS or ext == ".svg"
        if ext == ".webm":
            v, a = (probe or {}).get("video"), (probe or {}).get("audio")
            return v in {"vp8", "vp9", "av1"} and \
                (a in SAFE_ACODECS or a is None)
        if ext == ".mp4":
            v, a = (probe or {}).get("video"), (probe or {}).get("audio")
            return v in SAFE_VCODECS and (a in SAFE_ACODECS or a is None)
        return False                        # mkv/mov/m4v/avi/ogv

    def finding(self, fp: Path, rel: str, st: os.stat_result) -> dict:
        kind = self.kind_of(fp)
        probe = probe_media(fp) if kind == "video" else None
        std = self.std_delivers(fp, kind, probe)
        return {
            "path": rel,
            "kind": kind,
            "fmt": fp.suffix.lower().lstrip("."),
            "std": std,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
        }

    def tree(self, rel_dir: str) -> dict:
        d = self.resolve(rel_dir)
        if not d.is_dir():
            raise NotFound("not a directory")
        dirs, files = [], []
        try:
            entries = list(os.scandir(d))
        except OSError as exc:
            raise NotFound(f"unreadable: {exc}") from exc
        for entry in entries:
            if not self.visible(entry.name):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    dirs.append({"name": entry.name})
                elif entry.is_file(follow_symlinks=False):
                    fp = Path(entry.path)
                    kind = self.kind_of(fp)
                    if kind is None:
                        continue
                    files.append(self.finding(
                        fp,
                        (Path(rel_dir) / entry.name).as_posix()
                        if rel_dir else entry.name,
                        entry.stat()))
            except OSError:
                continue                     # raced/vanished — skip quietly
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["path"].lower())
        return {"dir": rel_dir.replace("\\", "/"),
                "dirs": dirs, "files": files}

    def walk_all(self, cap: int) -> dict:
        items, truncated = [], False
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if self.visible(d))
            rel_base = os.path.relpath(dirpath, self.root).replace("\\", "/")
            if rel_base == ".":
                rel_base = ""
            for fname in sorted(filenames):
                if not self.visible(fname):
                    continue
                if len(items) >= cap:
                    truncated = True
                    break
                full = Path(dirpath) / fname
                if self.kind_of(full) is None:
                    continue
                try:
                    st = full.stat()
                    rel = f"{rel_base}/{fname}" if rel_base else fname
                    items.append(self.finding(full, rel, st))
                except OSError:
                    continue
            if truncated:
                break
        return {"items": items, "total": len(items), "truncated": truncated}

    def walk_dirs(self) -> dict:
        out = []
        for dirpath, dirnames, _ in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if self.visible(d))
            rel = os.path.relpath(dirpath, self.root).replace("\\", "/")
            out.append("" if rel == "." else rel)
        out.sort()
        return {"dirs": out, "total": len(out)}


# ======================================================================
# GDI+ binding (stdlib ctypes): full-size decode -> JPEG/PNG, EXIF
# orientation respected; thumbnails share the same startup token.
# ======================================================================
_CLSID_JPEG = (ctypes.c_ubyte * 16)(
    0x01, 0xF4, 0x7C, 0x55, 0x04, 0x1A, 0xD3, 0x11,
    0x9A, 0x73, 0x00, 0x00, 0xF8, 0x1E, 0xF3, 0x2E)
_CLSID_PNG = (ctypes.c_ubyte * 16)(
    0x06, 0xF4, 0x7C, 0x55, 0x04, 0x1A, 0xD3, 0x11,
    0x9A, 0x73, 0x00, 0x00, 0xF8, 0x1E, 0xF3, 0x2E)
_GUID_QUALITY = (ctypes.c_ubyte * 16)(
    0xB5, 0xE4, 0x5B, 0x1D, 0x4A, 0xFA, 0x2D, 0x45,
    0x9C, 0xDD, 0x5D, 0xB3, 0x51, 0x05, 0xE7, 0xEB)
_ROTFLIP_FOR_ORIENTATION = {2: 4, 3: 2, 4: 6, 5: 5, 6: 1, 7: 7, 8: 3}
_PIXELFORMAT_ALPHA = 0x000C0000              # Alpha | PAlpha


class Gdi:
    """Process-wide GDI+ session; ok=False off-Windows or on failure."""

    def __init__(self):
        self.ok = False
        self.lock = threading.Lock()
        if sys.platform != "win32":
            return
        try:
            self._bind()
        except Exception:                      # noqa: BLE001 — best-effort
            self.ok = False

    def _bind(self):
        g = ctypes.windll.gdiplus

        class StartupInput(ctypes.Structure):
            _fields_ = [("GdiplusVersion", ctypes.c_uint),
                        ("DebugEventCallback", ctypes.c_void_p),
                        ("SuppressBackgroundThread", ctypes.c_int),
                        ("ExternalSuppression", ctypes.c_int)]

        class PropertyItem(ctypes.Structure):
            _fields_ = [("id", ctypes.c_uint), ("length", ctypes.c_uint),
                        ("type", ctypes.c_int16), ("value", ctypes.c_void_p)]

        class EncoderParam(ctypes.Structure):
            _fields_ = [("guid", ctypes.c_ubyte * 16),
                        ("numberOfValues", ctypes.c_ulong),
                        ("type", ctypes.c_ulong),
                        ("value", ctypes.c_void_p)]

        class EncoderParams(ctypes.Structure):
            _fields_ = [("count", ctypes.c_uint),
                        ("parameter", EncoderParam * 1)]

        token = ctypes.c_size_t()
        si = StartupInput(1, None, 0, 0)
        g.GdiplusStartup.argtypes = (ctypes.POINTER(ctypes.c_size_t),
                                     ctypes.POINTER(StartupInput),
                                     ctypes.c_void_p)
        g.GdiplusStartup.restype = ctypes.c_int
        if g.GdiplusStartup(ctypes.byref(token), ctypes.byref(si), None) != 0:
            return
        g.GdipCreateBitmapFromFile.argtypes = (ctypes.c_wchar_p,
                                               ctypes.POINTER(ctypes.c_void_p))
        g.GdipGetImageWidth.argtypes = (ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_uint))
        g.GdipGetImageHeight.argtypes = (ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_uint))
        g.GdipGetImagePixelFormat.argtypes = (ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_int))
        g.GdipGetImageThumbnail.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p)
        g.GdipSaveImageToFile.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p,
                                          ctypes.c_void_p, ctypes.c_void_p)
        g.GdipDisposeImage.argtypes = (ctypes.c_void_p,)
        g.GdipImageRotateFlip.argtypes = (ctypes.c_void_p, ctypes.c_int)
        g.GdipGetPropertyItemSize.argtypes = (ctypes.c_void_p, ctypes.c_uint,
                                              ctypes.POINTER(ctypes.c_uint))
        g.GdipGetPropertyItem.argtypes = (ctypes.c_void_p, ctypes.c_uint,
                                          ctypes.c_uint, ctypes.c_void_p)
        self.dll = g
        self._propitem = PropertyItem
        self._encparams = EncoderParams
        self.ok = True

    # ------------------------------------------------------------ props
    def _orientation(self, img) -> int:
        sz = ctypes.c_uint()
        if self.dll.GdipGetPropertyItemSize(img, 0x0112,
                                            ctypes.byref(sz)) != 0:
            return 0
        if sz.value < ctypes.sizeof(self._propitem) + 2:
            return 0
        buf = ctypes.create_string_buffer(sz.value)
        if self.dll.GdipGetPropertyItem(img, 0x0112, sz.value, buf) != 0:
            return 0
        pi = self._propitem.from_buffer(buf)
        if not pi.value or pi.length < 2:
            return 0
        return int.from_bytes(ctypes.string_at(pi.value, 2), "little")

    def _has_alpha(self, img) -> bool:
        pf = ctypes.c_int()
        if self.dll.GdipGetImagePixelFormat(img, ctypes.byref(pf)) != 0:
            return False
        return bool(pf.value & _PIXELFORMAT_ALPHA)

    # ----------------------------------------------------------- encode
    def convert_image(self, src: Path, dst: Path) -> str | None:
        """Decode any WIC-supported image; save JPG (or PNG w/ alpha).
        Returns 'jpg' | 'png' | None."""
        if not self.ok:
            return None
        with self.lock:
            img = ctypes.c_void_p()
            if self.dll.GdipCreateBitmapFromFile(str(src),
                                                 ctypes.byref(img)) != 0 \
                    or not img.value:
                return None
            try:
                orient = self._orientation(img)
                rf = _ROTFLIP_FOR_ORIENTATION.get(orient)
                if rf is not None:
                    self.dll.GdipImageRotateFlip(img, rf)
                png = self._has_alpha(img)
                clsid = _CLSID_PNG if png else _CLSID_JPEG
                params = None
                if not png:
                    quality = ctypes.c_ulong(90)
                    params = self._encparams(count=1)
                    params.parameter[0].guid = _GUID_QUALITY
                    params.parameter[0].numberOfValues = 1
                    params.parameter[0].type = 4            # EncoderParameterValueTypeLong
                    params.parameter[0].value = ctypes.cast(
                        ctypes.byref(quality), ctypes.c_void_p)
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.parent / (dst.name + ".part")
                ok = self.dll.GdipSaveImageToFile(
                    img, str(tmp), ctypes.byref(clsid),
                    ctypes.byref(params) if params else None) == 0
                if ok:
                    os.replace(tmp, dst)
                    return "png" if png else "jpg"
                try:
                    tmp.unlink()
                except OSError:
                    pass
                return None
            finally:
                self.dll.GdipDisposeImage(img)

    def thumbnail(self, src: Path, dst: Path, box: int) -> bool:
        """Cached-size JPEG thumb; True on success."""
        if not self.ok:
            return False
        with self.lock:
            img = ctypes.c_void_p()
            if self.dll.GdipCreateBitmapFromFile(str(src),
                                                 ctypes.byref(img)) != 0 \
                    or not img.value:
                return False
            try:
                orient = self._orientation(img)
                rf = _ROTFLIP_FOR_ORIENTATION.get(orient)
                if rf is not None:
                    self.dll.GdipImageRotateFlip(img, rf)
                w, h = ctypes.c_uint(), ctypes.c_uint()
                if self.dll.GdipGetImageWidth(img, ctypes.byref(w)) != 0 \
                        or self.dll.GdipGetImageHeight(
                            img, ctypes.byref(h)) != 0 \
                        or not w.value or not h.value:
                    return False
                scale = min(box / w.value if w.value > box else 1.0,
                            box / h.value if h.value > box else 1.0)
                thumb = ctypes.c_void_p()
                if self.dll.GdipGetImageThumbnail(
                        img, max(1, round(w.value * scale)),
                        max(1, round(h.value * scale)),
                        ctypes.byref(thumb), None, None) != 0 \
                        or not thumb.value:
                    return False
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dst.with_suffix(".part")
                    ok = self.dll.GdipSaveImageToFile(
                        thumb, str(tmp), ctypes.byref(_CLSID_JPEG),
                        None) == 0
                    if ok:
                        os.replace(tmp, dst)
                    elif tmp.exists():
                        tmp.unlink()
                    return ok
                finally:
                    self.dll.GdipDisposeImage(thumb)
            finally:
                self.dll.GdipDisposeImage(img)


GDI = Gdi()


# ======================================================================
# Normalization engine — the heart of HARMONIA.
# Output layout mirrors the library: norm-<rootkey>/<rel>.<viewext>
# Filenames embed a short hash of (rel, mtime_ns, size, target) so a
# changed source can never be masked by a stale artifact.
# ======================================================================
class NormEngine:
    def __init__(self, lib: MediaLibrary):
        self.lib = lib
        self.lock = threading.Lock()
        self.q: "queue.Queue[str]" = queue.Queue()
        self.state = {"idle": 0, "running": 0, "done": 0, "failed": 0}
        self.failed: list[dict] = []
        self.current: str | None = None
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    # ------------------------------------------------------------ plan
    def plan(self, fp: Path) -> dict | None:
        """What normalization does this file need?
        {"mode": copy|gdi|remux|transcode, "ext": ".jpg"|..., 
         "note": human line}  — None when nothing to do (std as-is)."""
        kind = self.lib.kind_of(fp)
        ext = fp.suffix.lower()
        if kind == "image":
            if ext in STD_IMAGE_EXTS:
                return None
            if ext == ".jfif":
                return {"mode": "copy", "ext": ".jpg",
                        "note": "JFIF \u2192 JPG (lossless rename)"}
            if ext in NORM_IMAGE_EXTS:
                return {"mode": "gdi", "ext": None,
                        "note": f"{ext.lstrip('.').upper()} \u2192 JPG/PNG (GDI+)"}
            return None                          # svg: vector, browsers ok
        if kind == "video":
            probe = probe_media(fp)
            if self.lib.std_delivers(fp, "video", probe):
                return None
            v, a = probe.get("video"), probe.get("audio")
            streams_safe = v in SAFE_VCODECS and \
                (a in SAFE_ACODECS or a is None)
            if streams_safe:
                return {"mode": "remux", "ext": ".mp4",
                        "note": f"{ext.lstrip('.').upper()} \u2192 MP4 "
                                f"(remux, {v}/{a} kept)"}
            if find_tool("ffmpeg") is None:
                return None                       # cannot; stays flagged
            return {"mode": "transcode", "ext": ".mp4",
                    "note": f"{ext.lstrip('.').upper()} \u2192 MP4 "
                            f"(H.264/AAC, was {v or '?'}/{a or '?'})"}
        return None

    def _artifact(self, rel: str, plan: dict) -> Path:
        fp = self.lib.resolve(rel)
        st = fp.stat()
        basis = f"{rel}|{st.st_mtime_ns}|{st.st_size}|{plan['mode']}"
        tag = hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:16]
        stem = Path(rel).stem or "item"
        return self.lib.norm_dir / f"{stem}.{tag}{plan['ext']}"

    # ------------------------------------------------------ sync paths
    def ensure(self, rel: str) -> tuple[Path, dict] | None:
        """Synchronous small jobs (images). Returns (artifact, plan) or
        None when the file is std as-is. Falls back to None-ish error
        paths by raising; callers decide the graceful fallback."""
        fp = self.lib.checked(rel, kinds=("image",))
        plan = self.plan(fp)
        if plan is None:
            return None
        art = self._artifact(rel, plan)
        if art.is_file() and art.stat().st_size > 0:
            return art, plan
        if plan["mode"] == "copy":
            art.parent.mkdir(parents=True, exist_ok=True)
            tmp = art.with_suffix(".part")
            shutil.copyfile(fp, tmp)
            os.replace(tmp, art)
            return art, plan
        got = GDI.convert_image(fp, art)
        if got is None:
            raise BadRequest(f"GDI+ could not decode {fp.suffix}")
        return art, plan

    def view_path(self, rel: str, kind: tuple) -> Path:
        """The bytes a viewer should receive: normalized artifact when
        one exists/can be built cheaply; never an error — worst case the
        original bytes go out and the UI badge says so."""
        try:
            fp = self.lib.checked(rel, kinds=kind)
        except (Forbidden, NotFound):
            raise
        plan = self.plan(fp)
        if plan is None:
            return fp
        art = self._artifact(rel, plan)
        if art.is_file() and art.stat().st_size > 0:
            return art
        if fp.suffix.lower() in IMAGE_EXTS and \
                plan["mode"] in ("copy", "gdi"):
            try:
                got = self.ensure(rel)
                if got:
                    return got[0]
            except (BadRequest, OSError):
                pass                        # undecodable → original bytes
        return fp                                 # video: wait for worker

    # ---------------------------------------------------- async worker
    def enqueue_all(self, rels: list[str]) -> int:
        """Queue every finding that still needs work; returns the count."""
        n = 0
        for rel in rels:
            try:
                fp = self.lib.checked(rel)
            except (Forbidden, NotFound):
                continue
            plan = self.plan(fp)
            if plan is None:
                continue
            if plan["mode"] in ("copy", "gdi") and \
                    self._artifact(rel, plan).is_file():
                continue                    # already materialized
            self.q.put(rel)
            n += 1
        return n

    def status(self) -> dict:
        with self.lock:
            return {"queued": self.q.qsize(), "running": self.current,
                    "done": self.state["done"], "failed": self.state["failed"],
                    "failures": list(self.failed[-20:])}

    def _mark(self, key: str, delta: int = 1) -> None:
        with self.lock:
            self.state[key] = self.state.get(key, 0) + delta

    def _loop(self) -> None:
        while True:
            rel = self.q.get()
            if rel is None:
                continue
            with self.lock:
                self.current = rel
            try:
                fp = self.lib.resolve(rel)
                plan = self.plan(fp)
                if plan is None:
                    self._mark("done")
                    continue
                art = self._artifact(rel, plan)
                if art.is_file() and art.stat().st_size > 0:
                    self._mark("done")
                    continue
                art.parent.mkdir(parents=True, exist_ok=True)
                if plan["mode"] in ("remux", "transcode"):
                    self._run_ffmpeg(fp, art, plan["mode"])
                    self._mark("done")
                elif plan["mode"] == "copy":
                    tmp = art.with_suffix(".part")
                    shutil.copyfile(fp, tmp)
                    os.replace(tmp, art)
                    self._mark("done")
                else:
                    if GDI.convert_image(fp, art) is None:
                        raise RuntimeError("GDI+ decode failed")
                    self._mark("done")
            except Exception as exc:           # noqa: BLE001 — keep worker alive
                self._mark("failed")
                with self.lock:
                    self.failed.append({"path": rel,
                                        "error": f"{type(exc).__name__}: "
                                                 f"{exc}"})
            finally:
                with self.lock:
                    self.current = None

    def _run_ffmpeg(self, src: Path, dst: Path, mode: str) -> None:
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg unavailable")
        cmd = [str(ffmpeg), "-y", "-i", str(src)]
        if mode == "remux":
            cmd += ["-c", "copy"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
        # keep the media extension on the temp name so ffmpeg can infer
        # the muxer (a bare ".part" suffix breaks -movflags faststart)
        tmp = dst.parent / f"{dst.stem}.part{dst.suffix}"
        cmd += ["-movflags", "+faststart", str(tmp)]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=FFMPEG_TIMEOUT)
        if res.returncode != 0:
            tail = (res.stderr or "").strip().splitlines()[-1:] or ["?"]
            raise RuntimeError(f"ffmpeg rc={res.returncode}: {tail[0][:200]}")
        os.replace(tmp, dst)


ENGINE: NormEngine | None = None


# ======================================================================
# HTTP layer
# ======================================================================
class HarmoniaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{APP}/{VERSION}"
    library: MediaLibrary = None          # bound in main()
    app_dir: Path = APP_DIR

    def log_message(self, fmt, *args):  # noqa: N802
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("[%s] %s\n" % (APP.lower(), fmt % args))

    # ---------------------------------------------------------- plumbing
    def send_json(self, status: int, payload: dict, head: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def ok(self, data, head: bool = False) -> None:
        self.send_json(200, {"ok": True, "error": None, "data": data}, head)

    def fail(self, status: int, message: str, head: bool = False) -> None:
        self.send_json(status, {"ok": False, "error": message, "data": None},
                       head)

    def do_GET(self) -> None:  # noqa: N802
        self._route(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._route(head=True)

    def _deny_write(self) -> None:
        self.fail(405, "method not allowed — the library is read-only")

    do_PUT = _deny_write
    do_PATCH = _deny_write
    do_DELETE = _deny_write

    def do_POST(self) -> None:  # noqa: N802 — app-state write surface
        if unquote(urlparse(self.path).path) == "/api/build":
            # Kick a full-library normalization pass (LOCALAPPDATA only).
            rels = [i["path"] for i in
                    self.library.walk_all(ALL_CAP_DEFAULT)["items"]]
            n = ENGINE.enqueue_all(rels)
            self.ok({"enqueued": n, **ENGINE.status()})
        else:
            self._deny_write()

    # ----------------------------------------------------------- routing
    def _route(self, head: bool) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        q = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._serve_index(head)
            elif path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif path == "/api/info":
                self.ok({
                    "app": APP, "version": VERSION,
                    "root_name": self.library.name,
                    "root": str(self.library.root),
                    "norm_dir": str(self.library.norm_dir),
                    "tools": {"ffmpeg": bool(find_tool("ffmpeg")),
                              "ffprobe": bool(find_tool("ffprobe")),
                              "gdi": GDI.ok},
                }, head)
            elif path == "/api/tree":
                self.ok(self.library.tree(q.get("dir", [""])[0]), head)
            elif path == "/api/all":
                try:
                    cap = max(1, min(int(q.get("cap", [ALL_CAP_DEFAULT])[0]),
                                     100000))
                except ValueError:
                    cap = ALL_CAP_DEFAULT
                self.ok(self.library.walk_all(cap), head)
            elif path == "/api/dirs":
                self.ok(self.library.walk_dirs(), head)
            elif path == "/api/file":
                kind = ("image",) if q.get("k", [""])[0] == "image" else \
                       ("video",) if q.get("k", [""])[0] == "video" else \
                       ("image", "video")
                want_norm = q.get("v", [""])[0] == "1"
                rel = q.get("f", [""])[0]
                fp = ENGINE.view_path(rel, kind) if want_norm else \
                    self.library.checked(rel, kinds=kind)
                ctype = mimetypes.guess_type(fp.name)[0] or \
                    "application/octet-stream"
                self._stream(fp, ctype, head)
            elif path == "/api/thumb":
                try:
                    box = max(64, min(int(q.get("s", ["340"])[0]), 1024))
                except ValueError:
                    box = 340
                self._serve_thumb(q.get("f", [""])[0], box, head)
            elif path == "/api/build":
                self.ok(ENGINE.status(), head)
            else:
                self.fail(404, "not found", head)
        except Forbidden as exc:
            self.fail(403, str(exc), head)
        except NotFound as exc:
            self.fail(404, str(exc), head)
        except BadRequest as exc:
            self.fail(400, str(exc), head)
        except (BrokenPipeError, ConnectionResetError):
            pass                              # client went away mid-stream
        except Exception as exc:  # noqa: BLE001 — last-resort contract guard
            self.fail(500, f"{type(exc).__name__}: {exc}", head)

    # ---------------------------------------------------------- handlers
    def _serve_index(self, head: bool) -> None:
        page = self.app_dir / "index.html"
        if not page.is_file():
            self.fail(500, "index.html missing beside server.py", head)
            return
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _stream(self, fp: Path, ctype: str, head: bool) -> None:
        size = fp.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "none")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        if head or size == 0:
            return
        with open(fp, "rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _serve_thumb(self, rel: str, box: int, head: bool) -> None:
        lib = self.library
        fp = lib.checked(rel, kinds=("image",))
        served = fp
        try:
            view = ENGINE.view_path(rel, ("image",))
            key = hashlib.sha1(
                f"{view}|{view.stat().st_mtime_ns}|{box}".encode()
            ).hexdigest()[:24]
            dst = lib.thumb_dir / key[:2] / f"{key[2:]}.jpg"
            if not dst.is_file():
                if GDI.thumbnail(view, dst, box):
                    served = dst
                else:
                    served = view          # undecodable → original/view bytes
            else:
                served = dst
        except (BadRequest, OSError):
            served = fp
        self._stream(served, "image/jpeg", head)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="harmonia",
        description=f"{APP} — normalized studio viewer (standard formats)")
    ap.add_argument("--root", default=None,
                    help="media root folder (default: current directory)")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"bind host (default {DEFAULT_HOST}; keep loopback)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port (default {DEFAULT_PORT}, 0 = ephemeral)")
    ap.add_argument("--show-hidden", action="store_true",
                    help="include dot-hidden entries")
    ap.add_argument("--tools-dir", default=None,
                    help="folder holding ffmpeg/ffprobe "
                         "(default: harmonia\\bin, aphrodite\\bin, PATH)")
    ap.add_argument("--open", action="store_true",
                    help="launch the browser once bound")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-request logging")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.tools_dir:
        setattr(tools_dir, "_override", args.tools_dir)
        _TOOLS.clear()
    root_arg = args.root or os.getcwd()
    try:
        lib = MediaLibrary(Path(root_arg), show_hidden=args.show_hidden)
    except OSError as exc:
        print(f"[{APP.lower()}] cannot open root {root_arg!r}: {exc}",
              file=sys.stderr)
        return 2

    global ENGINE
    ENGINE = NormEngine(lib)
    handler = type("BoundHarmonia", (HarmoniaHandler,),
                   {"library": lib, "app_dir": APP_DIR})
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    httpd.quiet = args.quiet
    url = f"http://{args.host}:{httpd.server_address[1]}/"

    ff = find_tool("ffmpeg")
    print(f"{APP} v{VERSION}")
    print(f"  root : {lib.root}")
    print(f"  url  : {url}")
    print(f"  norm : {lib.norm_dir}")
    print(f"  tools: ffmpeg={'bundled' if ff else 'MISSING'} "
          f"gdi={'yes' if GDI.ok else 'no'}")
    print("  local · offline · library read-only · Ctrl+C to stop",
          flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[{APP.lower()}] stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
