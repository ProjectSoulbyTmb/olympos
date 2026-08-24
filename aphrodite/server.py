#!/usr/bin/env python3
"""APHRODITE — standalone offline studio media viewer (photos + videos).

Design contract:
  * LOCAL ONLY      — binds 127.0.0.1 by default; no egress, no telemetry.
  * LIBRARY READ-ONLY — GET/HEAD serve content; writes exist ONLY on the
                      app-state routes (/api/fav|rate|tag|pos|bulk) and
                      mutate solely APHRODITE's own JSON under
                      LOCALAPPDATA, never the media library itself.
  * ONE ROOT        — every resolved path must live under --root (realpath
                      check, traversal and drive-letter tricks rejected).
  * STDLIB ONLY     — Python 3.10+, zero third-party dependencies.
                      (Thumbnails bind Windows GDI+ via ctypes — still stdlib.)
  * JSON CONTRACT   — every JSON response carries an ``error`` field
                      (null on success), matching the fleet wire style.
  * CONTENT-BLIND   — serves every media file under the root; no
                      content-level filtering of any kind.

Ports: 43904 chosen as the free fleet slot (ptah=43903, daedalus=43905);
registry row pending operator approval (see aphrodite/README.md).
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

APP = "APHRODITE"
VERSION = "0.5.0"
DEFAULT_PORT = 43904
DEFAULT_HOST = "127.0.0.1"
ALL_CAP_DEFAULT = 20000
CHUNK = 64 * 1024
DUPE_WINDOW = 64 * 1024
MAX_BULK = 500

IMAGE_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp",
              ".bmp", ".svg", ".avif"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".ogv"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga",
              ".opus", ".wav", ".wma", ".aiff"}

# ---- VLC-concept engine: universal playback via bundled ffmpeg ---------
# Browser-safe codecs play natively (full range/seek support); anything
# else is transcoded on the fly to H.264/AAC fragmented MP4.

SAFE_VCODECS = {"h264", "vp8", "vp9", "av1"}
SAFE_ACODECS = {"aac", "mp3", "opus", "vorbis"}
SAFE_CONTAINERS = {".mp4", ".m4v", ".mov", ".webm"}


def _bin_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", str(APP_DIR))) / "bin"


def _tool(name: str) -> Path | None:
    p = _bin_dir() / name
    return p if p.is_file() else None


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
    ffprobe = _tool("ffprobe.exe")
    data: dict = {}
    if ffprobe:
        try:
            out = subprocess.run(
                [str(ffprobe), "-v", "quiet", "-print_format", "json",
                 "-show_streams", str(fp)],
                capture_output=True, text=True, timeout=20)
            data = json.loads(out.stdout or "{}")
        except Exception:
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


def needs_transcode(fp: Path, probe: dict) -> bool:
    ext = fp.suffix.lower()
    v, a = probe.get("video"), probe.get("audio")
    if ext == ".webm":
        return not (v in {"vp8", "vp9", "av1"} and
                    (a in SAFE_ACODECS or a is None))
    if ext not in SAFE_CONTAINERS:
        return True                      # mkv/avi/ogv etc.
    return not (v in SAFE_VCODECS and
                (a in SAFE_ACODECS or a is None))


_SRT_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def srt_to_vtt(text: str) -> str:
    text = text.replace("\ufeff", "")
    body = _SRT_TS.sub(lambda m: f"{m.group(1)}:{m.group(2)}:"
                                 f"{m.group(3)}.{m.group(4)}", text)
    lines = [ln for ln in body.splitlines()
             if not re.fullmatch(r"\d+", ln.strip())]
    return "WEBVTT\n\n" + "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# v0.5 normal formats — every finding reports the standard form it maps
# to, and /api/file?norm=1 serves that form (GDI+ re-encode for images,
# ffmpeg remux/transcode for video). Already-standard files pass through
# byte-identical; nothing here ever writes into the media root.
# ----------------------------------------------------------------------
STD_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif"}
NORM_IMAGE_EXTS = {".bmp", ".tif", ".tiff", ".webp", ".avif",
                   ".jfif", ".heic", ".heif"}


def std_delivers(fp: Path, kind: str, probe: dict | None = None) -> bool:
    """True when the file as-is already views everywhere unchanged."""
    ext = fp.suffix.lower()
    if kind == "image":
        return ext in STD_IMAGE_EXTS or ext == ".svg"
    if ext == ".webm":
        v = (probe or {}).get("video")
        a = (probe or {}).get("audio")
        return v in {"vp8", "vp9", "av1"} and \
            (a in SAFE_ACODECS or a is None)
    if ext == ".mp4":
        v = (probe or {}).get("video")
        a = (probe or {}).get("audio")
        return v in SAFE_VCODECS and (a in SAFE_ACODECS or a is None)
    return False                                  # mkv/mov/m4v/avi/ogv


def norm_plan(fp: Path) -> dict | None:
    """What normalization a file needs: {'mode': copy|gdi|remux|transcode,
    'ext': target extension}. None when already standard as-is."""
    kind = MediaLibrary.kind_of(fp)
    if kind is None:
        return None
    ext = fp.suffix.lower()
    if kind == "image":
        if ext in STD_IMAGE_EXTS or ext == ".svg":
            return None
        if ext == ".jfif":
            return {"mode": "copy", "ext": ".jpg"}
        if ext in NORM_IMAGE_EXTS:
            return {"mode": "gdi", "ext": None}   # jpg, or png when alpha
        return None
    probe = probe_media(fp)
    if not needs_transcode(fp, probe):
        return None
    v, a = probe.get("video"), probe.get("audio")
    streams_safe = v in SAFE_VCODECS and (a in SAFE_ACODECS or a is None)
    if _tool("ffmpeg.exe") is None:
        return None                    # no tooling -> honest original bytes
    return {"mode": "remux" if streams_safe else "transcode",
            "ext": ".mp4"}


def norm_artifact(lib: "MediaLibrary", rel: str, plan: dict,
                  fp: Path | None = None) -> Path:
    """Deterministic cache path under LOCALAPPDATA; embeds a source
    fingerprint so an edited file can never hit a stale artifact."""
    if fp is None:
        fp = lib.resolve(rel)
    try:
        st = fp.stat()
        basis = f"{rel}|{st.st_mtime_ns}|{st.st_size}|{plan['mode']}"
    except OSError:
        basis = f"{rel}|gone|{plan['mode']}"
    tag = hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:16]
    ext = plan["ext"] or ".jpg"
    return lib.norm_dir / f"{Path(rel).stem}.{tag}{ext}"


def run_norm(lib: "MediaLibrary", rel: str) -> Path | None:
    """Build (or fetch from cache) the normalized variant of one media
    file. Returns the artifact path, the original path when nothing
    needed/possible, or None on hard failure."""
    try:
        fp = lib.checked(rel)
    except (Forbidden, NotFound):
        raise
    plan = norm_plan(fp)
    if plan is None:
        return fp
    art = norm_artifact(lib, rel, plan, fp)
    if art.is_file() and art.stat().st_size > 0:
        return art
    art.parent.mkdir(parents=True, exist_ok=True)
    tmp = art.parent / f"{art.name}.part"
    try:
        if plan["mode"] == "copy":
            shutil.copyfile(fp, tmp)
            os.replace(tmp, art)
        elif plan["mode"] == "gdi":
            got = THUMBS.convert_image(fp, tmp)
            if got is None:
                return fp                 # undecodable -> original bytes
            os.replace(tmp, art)
        else:                             # remux / transcode via ffmpeg
            ffmpeg = _tool("ffmpeg.exe")
            cmd = [str(ffmpeg), "-y", "-i", str(fp)]
            if plan["mode"] == "remux":
                cmd += ["-c", "copy"]
            else:
                cmd += ["-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k"]
            # keep .mp4 on the temp name so ffmpeg infers the muxer
            tmp_mp4 = art.parent / f"{art.stem}.part.mp4"
            cmd += ["-movflags", "+faststart", str(tmp_mp4)]
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=1800)
            if res.returncode != 0:
                tail = (res.stderr or "").strip().splitlines()[-1:] or ["?"]
                raise RuntimeError(
                    f"ffmpeg rc={res.returncode}: {tail[0][:200]}")
            os.replace(tmp_mp4, art)
        return art
    except (subprocess.TimeoutExpired, RuntimeError, OSError):
        for p in (tmp, art.parent / f"{art.stem}.part.mp4"):
            try:
                p.unlink()
            except OSError:
                pass
        return fp                           # degrade to original bytes

EXTRA_MIME = {
    ".mkv": "video/x-matroska", ".mov": "video/quicktime",
    ".m4v": "video/mp4", ".avi": "video/x-msvideo", ".ogv": "video/ogg",
    ".avif": "image/avif", ".webp": "image/webp", ".jfif": "image/jpeg",
    ".svg": "image/svg+xml",
}
for _ext, _mime in EXTRA_MIME.items():
    mimetypes.add_type(_mime, _ext)

APP_DIR = Path(__file__).resolve().parent
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
ABS_PATH_RE = re.compile(r"^([A-Za-z]:|\\\\|//)")


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
    return Path(base) / "APHRODITE" / sub


def _int_param(q: dict, name: str):
    """Parse an int query param; None when absent/unparsable."""
    try:
        return int(q.get(name, [""])[0])
    except (TypeError, ValueError):
        return None


def _float_param(q: dict, name: str):
    """Parse a float query param; None when absent/unparsable."""
    try:
        return float(q.get(name, [""])[0])
    except (TypeError, ValueError):
        return None


TAG_RE = re.compile(r"^[\w][\w \-/&+.']{0,47}$", re.UNICODE)


def _clean_tag(raw: str) -> str:
    """Validate a tag name: 1-48 word-ish chars, no control characters."""
    t = (raw or "").strip()
    if not TAG_RE.match(t):
        raise BadRequest("invalid tag name (1-48 chars, no control chars)")
    return t


# ======================================================================
# Minimal pure-python EXIF reader (JPEG APP1/TIFF) — display tags only.
# ======================================================================
_EXIF_IFD0 = {0x010F: "make", 0x0110: "model", 0x0112: "orientation",
              0x0131: "software", 0x0132: "modified", 0x8769: "__sub__"}
_EXIF_SUB = {0x829A: "exposure", 0x829D: "fnumber", 0x8827: "iso",
             0x9003: "taken", 0x920A: "focal", 0xA002: "px_w", 0xA003: "px_h"}
_FMT_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


def _exif_value(typ: int, raw: bytes, little: bool):
    endian = "little" if little else "big"
    if typ == 2:                                   # ASCII
        return raw.split(b"\x00")[0].decode("ascii", "replace").strip()
    if typ == 3:                                   # SHORT
        return int.from_bytes(raw[:2], endian)
    if typ == 4:                                   # LONG
        return int.from_bytes(raw[:4], endian)
    if typ == 9:                                   # SLONG
        return int.from_bytes(raw[:4], endian, signed=True)
    if typ in (5, 10):                             # RATIONAL / SRATIONAL
        num = int.from_bytes(raw[:4], endian, signed=(typ == 10))
        den = int.from_bytes(raw[4:8], endian, signed=(typ == 10))
        return (num, den)
    if typ == 1:                                   # BYTE
        return raw[0]
    return raw                                     # UNDEFINED etc.


def jpeg_exif(path: Path) -> dict:
    """Best-effort EXIF extraction; returns {} on anything unusual."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(262144)
        if head[:2] != b"\xff\xd8":
            return {}
        i, exif = 2, None
        while i + 4 <= len(head):
            if head[i] != 0xFF:
                break
            marker = head[i + 1]
            if marker == 0xDA:                     # start of scan
                break
            seg_len = int.from_bytes(head[i + 2:i + 4], "big")
            if seg_len < 2 or i + 2 + seg_len > len(head):
                break
            if marker == 0xE1 and head[i + 4:i + 10] == b"Exif\x00\x00":
                exif = head[i + 10:i + 2 + seg_len]
                break
            i += 2 + seg_len
        if not exif or len(exif) < 8:
            return {}
        if exif[:2] == b"II":
            little = True
        elif exif[:2] == b"MM":
            little = False
        else:
            return {}
        endian = "little" if little else "big"
        if int.from_bytes(exif[2:4], endian) != 42:
            return {}

        def u16(off):
            return int.from_bytes(exif[off:off + 2], endian)

        def u32(off):
            return int.from_bytes(exif[off:off + 4], endian)

        def scan_ifd(off, table, out):
            if off + 2 > len(exif):
                return
            for k in range(u16(off)):
                ent = off + 2 + k * 12
                if ent + 12 > len(exif):
                    break
                tag, typ, cnt = u16(ent), u16(ent + 2), u32(ent + 4)
                target = table.get(tag)
                if target is None or typ not in _FMT_SIZE:
                    continue
                size = _FMT_SIZE[typ] * cnt
                vo = ent + 8 if size <= 4 else u32(ent + 8)
                if vo + size > len(exif):
                    continue
                out[target] = _exif_value(typ, exif[vo:vo + size], little)

        res: dict = {}
        scan_ifd(u32(4), _EXIF_IFD0, res)
        sub = res.pop("__sub__", None)
        if isinstance(sub, int):
            scan_ifd(sub, _EXIF_SUB, res)

        def rat(key, fmt):
            v = res.get(key)
            if isinstance(v, tuple) and v[1]:
                res[key] = fmt.format(v[0] / v[1])

        rat("fnumber", "{:.1f}")
        rat("focal", "{:.1f} mm")
        exp = res.get("exposure")
        if isinstance(exp, tuple) and exp[1]:
            secs = exp[0] / exp[1]
            res["exposure"] = (f"1/{round(exp[1]/exp[0])} s"
                               if 0 < secs < 1 else f"{secs:g} s")
        for k in ("iso", "px_w", "px_h", "orientation"):
            if k in res and not isinstance(res[k], int):
                res.pop(k)
        return {k: v for k, v in res.items()
                if isinstance(v, (int, str)) and v != ""}
    except OSError:
        return {}


def media_meta(fp: Path) -> dict:
    try:
        if fp.suffix.lower() in (".jpg", ".jpeg", ".jfif"):
            return jpeg_exif(fp)
    except OSError:
        pass
    return {}


# ======================================================================
# App state — the ONLY writable surface; single JSON in LOCALAPPDATA.
# Holds favorites, ratings (0..5), tags and video watch-positions for
# exactly one library root (keyed by root-path hash). Never touches a
# byte of the media tree itself.
# ======================================================================
class AppState:
    def __init__(self, lib: "MediaLibrary"):
        self.lib = lib
        self.lock = threading.Lock()

    @property
    def path(self) -> Path:
        return _appdata_dir("state") / f"state-{self.lib.key}.json"

    # ------------------------------------------------------------ io
    def _migrate_legacy(self) -> dict:
        """Import pre-0.4 favorites-<key>.json once; never deletes it."""
        legacy = _appdata_dir("state") / f"favorites-{self.lib.key}.json"
        if not legacy.is_file():
            return {}
        try:
            d = json.loads(legacy.read_text(encoding="utf-8"))
            favs = d.get("favorites") if isinstance(d, dict) else None
            if isinstance(favs, list):
                return {"favorites": [r for r in favs if isinstance(r, str)]}
        except (OSError, ValueError):
            pass
        return {}

    def _load(self) -> dict:
        out = {"favorites": [], "ratings": {}, "tags": {}, "positions": {},
                "boards": [], "smart": []}
        raw: dict = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, ValueError):
            raw = self._migrate_legacy()
        favs = raw.get("favorites")
        if isinstance(favs, list):
            out["favorites"] = [r for r in favs if isinstance(r, str)]
        for key in ("ratings", "tags", "positions", "boards", "smart"):
            v = raw.get(key)
            if isinstance(v, (dict, list)):
                out[key] = v
        return out

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------ validation
    def _norm_rel(self, rel: str,
                  kinds: tuple = ("image", "video")) -> str:
        """Validate + normalize one media path; raises Forbidden/NotFound."""
        fp = self.lib.checked(rel, kinds=kinds)
        return os.path.relpath(str(fp), str(self.lib.root)).replace("\\", "/")

    def _live(self, rel: str, kinds: tuple = ("image", "video")) -> bool:
        """True if the stored relative path still resolves to visible media."""
        try:
            fp = self.lib.resolve(rel)
        except (Forbidden, NotFound):
            return False
        if not fp.is_file():
            return False
        kind = self.lib.kind_of(fp)
        return kind is not None and (kinds is None or kind in kinds)

    # --------------------------------------------------------- reading
    def snapshot(self) -> dict:
        """Live, pruned view used by GET /api/state."""
        with self.lock:
            d = self._load()
            st = {"favorites": [], "ratings": {}, "tags": {}, "positions": {}}
            for rel in d["favorites"]:
                item = self._fav_item(rel)
                if item:
                    st["favorites"].append(item)
            for rel, v in d["ratings"].items():
                if isinstance(v, int) and 1 <= v <= 5 \
                        and self._live(rel):
                    st["ratings"][rel] = v
            for rel, names in d["tags"].items():
                if isinstance(names, list) and names and self._live(rel):
                    clean = [n for n in names if isinstance(n, str)]
                    if clean:
                        st["tags"][rel] = clean
            for rel, pos in d["positions"].items():
                if isinstance(pos, (int, float)) and pos >= 0 \
                        and self._live(rel, kinds=("video",)):
                    st["positions"][rel] = round(float(pos), 1)
            return st

    def _fav_item(self, rel: str):
        try:
            fp = self.lib.resolve(rel)
        except (Forbidden, NotFound):
            return None
        kind = self.lib.kind_of(fp)
        if not fp.is_file() or kind is None or not self.lib.visible(fp.name):
            return None
        try:
            s = fp.stat()
        except OSError:
            return None
        return {"path": rel.replace("\\", "/"), "kind": kind,
                "size": s.st_size, "mtime": int(s.st_mtime)}

    # -------------------------------------------------------- mutating
    def fav_add(self, rel: str) -> dict:
        norm = self._norm_rel(rel)
        with self.lock:
            d = self._load()
            if norm not in d["favorites"]:
                d["favorites"].append(norm)
                self._save(d)
            return {"added": norm, "count": len(d["favorites"])}

    def fav_remove(self, rel: str) -> dict:
        norm = self._norm_rel(rel)
        with self.lock:
            d = self._load()
            n = len(d["favorites"])
            d["favorites"] = [x for x in d["favorites"] if x != norm]
            if len(d["favorites"]) != n:
                self._save(d)
            return {"removed": True, "count": len(d["favorites"])}

    def rate(self, rel: str, val: int) -> dict:
        norm = self._norm_rel(rel)
        with self.lock:
            d = self._load()
            if val == 0:
                d["ratings"].pop(norm, None)
            else:
                d["ratings"][norm] = val
            self._save(d)
            return {"rated": norm, "value": val}

    def tag_add(self, rel: str, name: str) -> dict:
        norm = self._norm_rel(rel)
        with self.lock:
            d = self._load()
            lst = d["tags"].setdefault(norm, [])
            if name not in lst:
                lst.append(name)
            self._save(d)
            return {"tagged": norm, "tag": name, "tags": list(lst)}

    def tag_remove(self, rel: str, name: str) -> dict:
        norm = self._norm_rel(rel)
        with self.lock:
            d = self._load()
            lst = [t for t in d["tags"].get(norm, []) if t != name]
            if lst:
                d["tags"][norm] = lst
            else:
                d["tags"].pop(norm, None)
            self._save(d)
            return {"untagged": norm, "tag": name}

    def pos_set(self, rel: str, sec: float) -> dict:
        norm = self._norm_rel(rel, kinds=("video",))
        with self.lock:
            d = self._load()
            d["positions"][norm] = round(sec, 1)
            self._save(d)
            return {"position": norm, "seconds": round(sec, 1)}

    def pos_clear(self, rel: str) -> dict:
        norm = self._norm_rel(rel, kinds=("video",))
        with self.lock:
            d = self._load()
            d["positions"].pop(norm, None)
            self._save(d)
            return {"cleared": norm}

    def bulk(self, op: str, rels: list, value=None) -> dict:
        """All-or-nothing batch: every path validates before any write."""
        norm = [self._norm_rel(r) for r in rels]
        with self.lock:
            d = self._load()
            if op == "fav":
                known = set(d["favorites"])
                d["favorites"] += [r for r in norm if r not in known]
            elif op == "unfav":
                drop = set(norm)
                d["favorites"] = [x for x in d["favorites"]
                                  if x not in drop]
            elif op == "rate":
                for r in norm:
                    if value:
                        d["ratings"][r] = value
                    else:
                        d["ratings"].pop(r, None)
            elif op == "tag":
                for r in norm:
                    lst = d["tags"].setdefault(r, [])
                    if value not in lst:
                        lst.append(value)
            elif op == "untag":
                for r in norm:
                    lst = [t for t in d["tags"].get(r, []) if t != value]
                    if lst:
                        d["tags"][r] = lst
                    else:
                        d["tags"].pop(r, None)
            self._save(d)
            return {"op": op, "changed": len(norm)}

    # ------------------------------------------------ boards + smart albums
    # (v0.5 muse layer - same store, same lock, same confinement)
    def _board(self, d, bid):
        for b in d["boards"]:
            if isinstance(b, dict) and b.get("id") == bid:
                return b
        raise NotFound("no such board")

    def boards_snapshot(self):
        with self.lock:
            return {"boards": [{"id": b.get("id"), "name": b.get("name"),
                                "count": len(b.get("items", []))}
                               for b in self._load()["boards"]]}

    def board_create(self, name):
        import secrets as _s
        name = str(name or "").strip()[:60]
        if not name:
            raise BadRequest("board name required")
        with self.lock:
            d = self._load()
            bid = _s.token_hex(4)
            d["boards"].append({"id": bid, "name": name, "items": [],
                                "created": int(time.time())})
            self._save(d)
        return self.board_get(bid)

    def board_delete(self, bid):
        with self.lock:
            d = self._load()
            self._board(d, bid)
            d["boards"] = [b for b in d["boards"]
                           if b.get("id") != bid]
            self._save(d)
        return {"deleted": bid}

    def board_add(self, bid, rel):
        norm = self._norm_rel(rel)
        with self.lock:
            d = self._load()
            b = self._board(d, bid)
            if norm not in b["items"]:
                b["items"].append(norm)
                self._save(d)
        return self.board_get(bid)

    def board_remove(self, bid, rel):
        norm = self._norm_rel(rel)
        with self.lock:
            d = self._load()
            b = self._board(d, bid)
            b["items"] = [x for x in b["items"] if x != norm]
            self._save(d)
        return self.board_get(bid)

    def board_get(self, bid):
        with self.lock:
            d = self._load()
            b = self._board(d, bid)
        items, dead = [], 0
        for rel in b.get("items", []):
            item = self._fav_item(rel)
            if item is None:
                dead += 1
                continue
            items.append(item)
        return {"id": b.get("id"), "name": b.get("name"),
                "created": b.get("created"), "items": items,
                "pruned": dead}

    def board_export_html(self, bid):
        from urllib.parse import quote as _q
        b = self.board_get(bid)
        esc = (lambda s: str(s).replace("&", "&amp;")
               .replace("<", "&lt;").replace(">", "&gt;"))
        rows = "".join(
            '<figure><img loading="lazy" src="/api/thumb?f='
            + _q(i["path"]) + '&amp;s=340"><figcaption>'
            + esc(i["path"]) + "</figcaption></figure>"
            for i in b["items"])
        return ("<!doctype html><meta charset='utf-8'><title>"
                + esc(b["name"]) + " - APHRODITE sheet</title>"
                "<style>body{background:#141414;color:#ddd;"
                "font:14px system-ui}figure{display:inline-block;"
                "margin:10px}img{height:180px;display:block}"
                "figcaption{max-width:210px;font-size:11px;color:#999}"
                "</style><h1>" + esc(b["name"]) + "</h1><p>"
                + str(len(b["items"])) + " items</p>" + rows)

    def smart_save(self, name, kind, min_rating, tag):
        import secrets as _s
        name = str(name or "").strip()[:60]
        if not name:
            raise BadRequest("album name required")
        q = {"kind": kind if kind in ("image", "video") else "",
             "minRating": max(0, min(int(min_rating or 0), 5)),
             "tag": str(tag or "").strip().lower()[:32]}
        with self.lock:
            d = self._load()
            aid = _s.token_hex(4)
            d["smart"].append({"id": aid, "name": name, "query": q,
                               "created": int(time.time())})
            self._save(d)
        return {"id": aid, "name": name, "query": q}

    def smart_delete(self, aid):
        with self.lock:
            d = self._load()
            d["smart"] = [a for a in d["smart"]
                          if a.get("id") != aid]
            self._save(d)
        return {"deleted": aid}

    def smart_list(self):
        with self.lock:
            d = self._load()
            return {"albums": [
                {"id": a.get("id"), "name": a.get("name"),
                 "query": a.get("query", {})}
                for a in d["smart"] if isinstance(a, dict)]}

    def smart_eval(self, aid, cap=5000):
        with self.lock:
            alb = next((a for a in self._load()["smart"]
                        if a.get("id") == aid), None)
        if alb is None:
            raise NotFound("no such album")
        q = alb["query"]
        snap = self.snapshot()
        ratings, tags = snap["ratings"], snap["tags"]
        hits = []
        for it in self.lib.walk_all(cap)["items"]:
            rel = it["path"]
            if q["kind"] and it["kind"] != q["kind"]:
                continue
            if q["minRating"] and \
                    ratings.get(rel, 0) < q["minRating"]:
                continue
            if q["tag"] and q["tag"] not in tags.get(rel, []):
                continue
            hits.append(it)
        return {"id": aid, "name": alb["name"], "query": q,
                "items": hits}

    def tags_index(self):
        with self.lock:
            idx = {}
            for rel, names in self._load()["tags"].items():
                if not self._live(rel):
                    continue
                for t in names if isinstance(names, list) else []:
                    idx.setdefault(t, []).append(rel)
        return {"index": {k: sorted(v)
                          for k, v in sorted(idx.items())}}


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
        self.cache_dir = _appdata_dir("thumbs") / self.key
        self.norm_dir = _appdata_dir("normalized") / self.key
        self.state = AppState(self)

    # ------------------------------------------------------------- paths
    def resolve(self, rel: str) -> Path:
        """Resolve a root-relative path, refusing anything outside root."""
        rel = (rel or "").replace("\\", "/")
        if ABS_PATH_RE.match(rel):
            raise Forbidden("absolute paths not allowed")
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise Forbidden("path traversal rejected")
        real = os.path.realpath(str(self.root.joinpath(*parts)))
        case = _normcase(real)
        if case != self.root_case and not case.startswith(self.root_case + os.sep):
            raise Forbidden("resolved outside root")
        return Path(real)

    def checked(self, rel: str, kinds: tuple | None = None) -> Path:
        """Resolve + full media-file validation."""
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

    def rel_of(self, fp: Path) -> str:
        return os.path.relpath(str(fp), str(self.root)).replace("\\", "/")

    # ---------------------------------------------------------- listings
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
                    kind = self.kind_of(Path(entry.path))
                    if kind is None:
                        continue
                    st = entry.stat()
                    fp = Path(entry.path)
                    files.append({
                        "name": entry.name,
                        "size": st.st_size,
                        "mtime": int(st.st_mtime),
                        "kind": kind,
                        # v0.5 normal-format fields
                        "fmt": fp.suffix.lower().lstrip("."),
                        "std": std_delivers(fp, kind),
                    })
            except OSError:
                continue  # raced/vanished entry — skip quietly
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())
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
                kind = self.kind_of(full)
                if kind is None:
                    continue
                try:
                    st = full.stat()
                except OSError:
                    continue
                items.append({
                    "path": f"{rel_base}/{fname}" if rel_base else fname,
                    "kind": kind,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    # v0.5 normal-format fields
                    "fmt": full.suffix.lower().lstrip("."),
                    "std": std_delivers(full, kind),
                })
            if truncated:
                break
        return {"items": items, "total": len(items), "truncated": truncated}

    def walk_dirs(self) -> dict:
        """Every visible directory under root, recursively, sorted."""
        out = []
        for dirpath, dirnames, _ in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if self.visible(d))
            rel = os.path.relpath(dirpath, self.root).replace("\\", "/")
            out.append("" if rel == "." else rel)
        out.sort()
        return {"dirs": out, "total": len(out)}

    def find_dupes(self, min_size: int, budget_s: float = 8.0,
                   max_groups: int = 100) -> dict:
        """Candidate duplicates = identical byte size. Confirmation =
        sha256 over the first and last DUPE_WINDOW bytes (plus size),
        which avoids reading whole files. Time-budgeted: stops cleanly
        with partial=true rather than blocking forever on big libraries."""
        t0 = time.monotonic()
        by_size: dict[int, list[str]] = {}
        scanned = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if self.visible(d))
            rel_base = os.path.relpath(dirpath, self.root).replace("\\", "/")
            if rel_base == ".":
                rel_base = ""
            for fname in sorted(filenames):
                if not self.visible(fname):
                    continue
                full = Path(dirpath) / fname
                if self.kind_of(full) is None:
                    continue
                try:
                    sz = full.stat().st_size
                except OSError:
                    continue
                scanned += 1
                if sz >= min_size:
                    key = f"{rel_base}/{fname}" if rel_base else fname
                    by_size.setdefault(sz, []).append(key)

        def fingerprint(rel: str) -> str:
            fp = self.resolve(rel)
            h = hashlib.sha256()
            with open(fp, "rb") as fh:
                h.update(fh.read(DUPE_WINDOW))
                fh.seek(max(0, fp.stat().st_size - DUPE_WINDOW))
                h.update(fh.read(DUPE_WINDOW))
            return h.hexdigest()

        cand = sorted(
            ((sz * (len(paths) - 1), sz, paths)
             for sz, paths in by_size.items() if len(paths) > 1),
            reverse=True)
        groups, partial = [], False
        for _, sz, paths in cand:
            if time.monotonic() - t0 > budget_s or len(groups) >= max_groups:
                partial = True
                break
            buckets: dict[str, list[str]] = {}
            for r in paths:
                try:
                    buckets.setdefault(fingerprint(r), []).append(r)
                except OSError:
                    continue          # raced/vanished mid-scan — skip quietly
            for members in buckets.values():
                if len(members) > 1:
                    groups.append({"size": sz, "paths": sorted(members)})
        groups.sort(key=lambda g: (-g["size"] * (len(g["paths"]) - 1),
                                   g["paths"]))
        return {"groups": groups, "scanned": scanned, "partial": partial,
                "elapsed_ms": int((time.monotonic() - t0) * 1000)}


# ======================================================================
# GDI+ thumbnailer (Windows, in-process via ctypes; stdlib only)
# ======================================================================
_JPEG_CLSID = ctypes.create_string_buffer(
    b"\x01\xf4\x7c\x55\x04\x1a\xd3\x11\x9a\x73\x00\x00\xf8\x1e\xf3\x2e")
_PNG_CLSID = (ctypes.c_ubyte * 16)(
    0x06, 0xF4, 0x7C, 0x55, 0x04, 0x1A, 0xD3, 0x11,
    0x9A, 0x73, 0x00, 0x00, 0xF8, 0x1E, 0xF3, 0x2E)
_GUID_QUALITY = (ctypes.c_ubyte * 16)(
    0xB5, 0xE4, 0x5B, 0x1D, 0x4A, 0xFA, 0x2D, 0x45,
    0x9C, 0xDD, 0x5D, 0xB3, 0x51, 0x05, 0xE7, 0xEB)
_ROTFLIP_FOR_ORIENTATION = {2: 4, 3: 2, 4: 6, 5: 5, 6: 1, 7: 7, 8: 3}


class GdiThumbner:
    """Generates cached JPEG thumbnails; degrades to serving originals."""

    def __init__(self):
        self.ok = False
        self.lock = threading.Lock()
        self.dll = None
        if sys.platform == "win32":
            try:
                self._bind()
            except Exception:  # noqa: BLE001 — feature is best-effort
                self.ok = False

    def _bind(self):
        import ctypes
        from ctypes import wintypes
        g = ctypes.windll.gdiplus

        class StartupInput(ctypes.Structure):
            _fields_ = [("GdiplusVersion", ctypes.c_uint),
                        ("DebugEventCallback", ctypes.c_void_p),
                        ("SuppressBackgroundThread", ctypes.c_int),
                        ("ExternalSuppression", ctypes.c_int)]

        class PropertyItem(ctypes.Structure):
            _fields_ = [("id", ctypes.c_uint), ("length", ctypes.c_uint),
                        ("type", ctypes.c_int16), ("value", ctypes.c_void_p)]

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
        g.GdipGetImagePixelFormat.argtypes = (ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_int))

        class EncoderParam(ctypes.Structure):
            _fields_ = [("guid", ctypes.c_ubyte * 16),
                        ("numberOfValues", ctypes.c_ulong),
                        ("type", ctypes.c_ulong),
                        ("value", ctypes.c_void_p)]

        class EncoderParams(ctypes.Structure):
            _fields_ = [("count", ctypes.c_uint),
                        ("parameter", EncoderParam * 1)]

        self.dll = g
        self._propitem = PropertyItem
        self._wintypes = wintypes
        self._encparams = EncoderParams
        self.ok = True

    def _orientation(self, img) -> int:
        import ctypes
        sz = ctypes.c_uint()
        if self.dll.GdipGetPropertyItemSize(img, 0x0112, ctypes.byref(sz)) != 0:
            return 0
        if sz.value < ctypes.sizeof(self._propitem) + 2:
            return 0
        buf = ctypes.create_string_buffer(sz.value)
        if self.dll.GdipGetPropertyItem(img, 0x0112, sz.value, buf) != 0:
            return 0
        pi = self._propitem.from_buffer(buf)
        if not pi.value or pi.length < 2:
            return 0
        import ctypes as c
        return int.from_bytes(c.string_at(pi.value, 2), "little")

    def _has_alpha(self, img) -> bool:
        import ctypes
        pf = ctypes.c_int()
        if self.dll.GdipGetImagePixelFormat(img, ctypes.byref(pf)) != 0:
            return False
        return bool(pf.value & 0x000C0000)   # PixelFormatAlpha | PAlpha

    def convert_image(self, src: Path, dst: Path) -> str | None:
        """Full-size decode of any WIC-supported image -> JPEG (or PNG
        with alpha), EXIF orientation baked in. Returns 'jpg' | 'png'
        | None when the source cannot be decoded/saved. dst may carry a
        temp suffix — the encoder CLSID decides the format, not the name."""
        import ctypes
        if not self.ok:
            return None
        with self.lock:                                # serialize GDI+ work
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
                clsid = _PNG_CLSID if png else _JPEG_CLSID
                params = None
                if not png:
                    quality = ctypes.c_ulong(90)
                    params = self._encparams(count=1)
                    params.parameter[0].guid = _GUID_QUALITY
                    params.parameter[0].numberOfValues = 1
                    params.parameter[0].type = 4       # long
                    params.parameter[0].value = ctypes.cast(
                        ctypes.byref(quality), ctypes.c_void_p)
                if self.dll.GdipSaveImageToFile(
                        img, str(dst), ctypes.byref(clsid),
                        ctypes.byref(params) if params else None) == 0:
                    return "png" if png else "jpg"
                return None
            finally:
                self.dll.GdipDisposeImage(img)

    def generate(self, src: Path, dst: Path, box: int) -> bool:
        """True if dst written as a valid JPEG thumbnail."""
        import ctypes
        if not self.ok:
            return False
        with self.lock:                                # serialize generation
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
                        or self.dll.GdipGetImageHeight(img, ctypes.byref(h)) != 0 \
                        or not w.value or not h.value:
                    return False
                scale = min(box / w.value if w.value > box else 1.0,
                            box / h.value if h.value > box else 1.0)
                tw = max(1, round(w.value * scale))
                th = max(1, round(h.value * scale))
                thumb = ctypes.c_void_p()
                if self.dll.GdipGetImageThumbnail(
                        img, tw, th, ctypes.byref(thumb), None, None) != 0 \
                        or not thumb.value:
                    return False
                try:
                    return self.dll.GdipSaveImageToFile(
                        thumb, str(dst), ctypes.byref(_JPEG_CLSID), None) == 0
                finally:
                    self.dll.GdipDisposeImage(thumb)
            finally:
                self.dll.GdipDisposeImage(img)


THUMBS = GdiThumbner()


# ======================================================================
# HTTP layer
# ======================================================================
class AphroditeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{APP}/{VERSION}"
    library: MediaLibrary = None          # bound in main()
    app_dir: Path = APP_DIR

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):  # noqa: N802
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("[%s] %s\n" % (APP.lower(), fmt % args))

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
        self.send_json(status, {"ok": False, "error": message, "data": None}, head)

    # ------------------------------------------------------------- routing
    def do_GET(self) -> None:  # noqa: N802
        self._route(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._route(head=True)

    def _deny_write_method(self) -> None:
        self.fail(405, "method not allowed — the library is read-only")

    do_PUT = _deny_write_method
    do_PATCH = _deny_write_method

    # App-state write surface — these exact routes, nothing else.
    WRITE_POST = ("/api/fav", "/api/rate", "/api/tag", "/api/pos", "/api/bulk", "/api/boards", "/api/smart")
    WRITE_DELETE = ("/api/fav", "/api/tag", "/api/pos", "/api/boards", "/api/smart")

    def do_POST(self) -> None:  # noqa: N802 — app-state writes only
        self._write_route(self.WRITE_POST)

    def do_DELETE(self) -> None:  # noqa: N802 — app-state writes only
        self._write_route(self.WRITE_DELETE)

    def _write_route(self, allowed: tuple) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route not in allowed:
            self.fail(405, "method not allowed — the library is read-only")
            return
        try:
            q = parse_qs(parsed.query)
            st = self.library.state
            rel = q.get("f", [""])[0]
            if route == "/api/fav":
                if self.command == "POST":
                    self.ok(st.fav_add(rel))
                else:
                    self.ok(st.fav_remove(rel))
            elif route == "/api/rate":
                v = _int_param(q, "v")
                if v is None or not 0 <= v <= 5:
                    raise BadRequest("v must be an integer 0..5")
                self.ok(st.rate(rel, v))
            elif route == "/api/tag":
                name = _clean_tag(q.get("t", [""])[0])
                if self.command == "POST":
                    self.ok(st.tag_add(rel, name))
                else:
                    self.ok(st.tag_remove(rel, name))
            elif route == "/api/pos":
                if self.command == "POST":
                    sec = _float_param(q, "sec")
                    if sec is None or not 0 <= sec <= 360000:
                        raise BadRequest("sec must be a number 0..360000")
                    self.ok(st.pos_set(rel, sec))
                else:
                    self.ok(st.pos_clear(rel))
            elif route == "/api/boards":
                act = (q.get("action", [""])[0] or "").lower()
                bid = q.get("b", [""])[0]
                if self.command == "POST":
                    if act == "create":
                        self.ok(st.board_create(q.get("name", [""])[0]))
                    elif act == "add":
                        self.ok(st.board_add(bid, rel))
                    elif act == "remove":
                        self.ok(st.board_remove(bid, rel))
                    else:
                        raise BadRequest("unknown board action")
                else:
                    if not bid:
                        raise BadRequest("delete needs b=")
                    self.ok(st.board_delete(bid))
            elif route == "/api/smart":
                if self.command == "POST":
                    raw_tag = q.get("t", [""])[0]
                    self.ok(st.smart_save(
                        q.get("name", [""])[0],
                        q.get("kind", [""])[0],
                        _int_param(q, "minrating") or 0,
                        _clean_tag(raw_tag) if raw_tag else ""))
                else:
                    aid = q.get("a", [""])[0]
                    if not aid:
                        raise BadRequest("delete needs a=")
                    self.ok(st.smart_delete(aid))
            else:                                          # /api/bulk
                op = (q.get("op", [""])[0] or "").lower()
                rels = q.get("f", [])
                if op not in ("fav", "unfav", "rate", "tag", "untag"):
                    raise BadRequest("unknown bulk op")
                if not rels or len(rels) > MAX_BULK:
                    raise BadRequest(f"bulk needs 1..{MAX_BULK} f= params")
                value = None
                if op == "rate":
                    value = _int_param(q, "v")
                    if value is None or not 0 <= value <= 5:
                        raise BadRequest("bulk rate needs v 0..5")
                elif op in ("tag", "untag"):
                    value = _clean_tag(q.get("t", [""])[0])
                self.ok(st.bulk(op, rels, value))
        except Forbidden as exc:
            self.fail(403, str(exc))
        except NotFound as exc:
            self.fail(404, str(exc))
        except BadRequest as exc:
            self.fail(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.fail(500, f"{type(exc).__name__}: {exc}")

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
                self.ok({"app": APP, "version": VERSION,
                         "root_name": self.library.name,
                         "root": str(self.library.root)}, head)
            elif path == "/api/tree":
                self.ok(self.library.tree(q.get("dir", [""])[0]), head)
            elif path == "/api/all":
                try:
                    cap = max(1, min(int(q.get("cap", [ALL_CAP_DEFAULT])[0]),
                                     100000))
                except ValueError:
                    cap = ALL_CAP_DEFAULT
                self.ok(self.library.walk_all(cap), head)
            elif path == "/api/file":
                if q.get("norm", [""])[0] == "1":
                    # v0.5: serve the standard viewing form of the file
                    rel = q.get("f", [""])[0]
                    view = run_norm(self.library, rel)
                    if view is None:
                        raise NotFound("no such file")
                    ctype = mimetypes.guess_type(view.name)[0] or \
                        "application/octet-stream"
                    self._stream_path(view, ctype, head, ranged=True,
                                      cache="private, max-age=3600")
                else:
                    self._serve_media(q.get("f", [""])[0],
                                      kinds=("image", "video"), head=head)
            elif path == "/api/thumb":
                try:
                    box = max(64, min(int(q.get("s", ["340"])[0]), 1024))
                except ValueError:
                    box = 340
                self._serve_thumb(q.get("f", [""])[0], box, head)
            elif path == "/api/meta":
                fp = self.library.checked(q.get("f", [""])[0],
                                          kinds=("image",))
                self.ok(media_meta(fp), head)
            elif path == "/api/fav":
                self.ok({"items": self.library.state.snapshot()["favorites"]},
                        head)
            elif path == "/api/state":
                self.ok(self.library.state.snapshot(), head)
            elif path == "/api/dirs":
                self.ok(self.library.walk_dirs(), head)
            elif path == "/api/boards":
                bid = q.get("b", [""])[0]
                st_ = self.library.state
                self.ok(st_.board_get(bid) if bid
                        else st_.boards_snapshot(), head)
            elif path == "/api/board/export":
                html = self.library.state.board_export_html(
                    q.get("b", [""])[0])
                body_h = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type",
                                 "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body_h)))
                self.end_headers()
                if not head:
                    self.wfile.write(body_h)
            elif path == "/api/smart":
                aid = q.get("a", [""])[0]
                st_ = self.library.state
                self.ok(st_.smart_eval(aid) if aid
                        else st_.smart_list(), head)
            elif path == "/api/tags-index":
                self.ok(self.library.state.tags_index(), head)
            elif path == "/api/dupes":
                try:
                    min_size = max(1, min(
                        int(q.get("minsize", ["65536"])[0]), 1 << 31))
                except ValueError:
                    min_size = 65536
                self.ok(self.library.find_dupes(min_size), head)
            else:
                self.fail(404, "not found", head)
        except Forbidden as exc:
            self.fail(403, str(exc), head)
        except NotFound as exc:
            self.fail(404, str(exc), head)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client navigated away mid-stream
        except Exception as exc:  # noqa: BLE001 — last-resort contract guard
            self.fail(500, f"{type(exc).__name__}: {exc}", head)

    # ------------------------------------------------------------ handlers
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

    def _stream_path(self, fp: Path, ctype: str, head: bool,
                     ranged: bool, cache: str) -> None:
        """Shared byte-streamer with optional single-range support."""
        size = fp.stat().st_size
        start, end, status = 0, max(size - 1, 0), 200
        range_header = self.headers.get("Range")
        if ranged and range_header and size > 0:
            m = RANGE_RE.match(range_header.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1) == "":                   # suffix: last N bytes
                    n = int(m.group(2))
                    if n <= 0:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    start = max(0, size - n)
                else:
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                    if start >= size or end < start:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                end = min(end, size - 1)
                status = 206

        length = size if status == 200 else (end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes" if ranged else "none")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Cache-Control", cache)
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if head or length == 0:
            return
        with open(fp, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _serve_media(self, rel: str, kinds: tuple, head: bool) -> None:
        fp = self.library.checked(rel, kinds=kinds)
        ctype = (mimetypes.guess_type(fp.name)[0]
                 or ("video/mp4" if self.library.kind_of(fp) == "video"
                     else "application/octet-stream"))
        self._stream_path(fp, ctype, head, ranged=True,
                          cache="private, max-age=3600")

    def _serve_thumb(self, rel: str, box: int, head: bool) -> None:
        lib = self.library
        fp = lib.checked(rel, kinds=("image",))
        served = fp
        try:
            key = hashlib.sha1(
                f"{fp}|{fp.stat().st_mtime_ns}|{box}".encode()).hexdigest()[:24]
            dst = lib.cache_dir / key[:2] / f"{key[2:]}.jpg"
            if not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(".part")
                if THUMBS.generate(fp, tmp, box):
                    os.replace(tmp, dst)
                elif tmp.exists():
                    tmp.unlink()
            if dst.is_file() and dst.stat().st_size > 0:
                served = dst
        except OSError:
            served = fp                               # cache trouble → original
        self._stream_path(served, "image/jpeg", head, ranged=False,
                          cache="private, max-age=604800")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="aphrodite",
        description=f"{APP} — standalone offline studio media viewer")
    ap.add_argument("--root", default=None,
                    help="media root folder (default: current directory)")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"bind host (default {DEFAULT_HOST}; keep loopback)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port (default {DEFAULT_PORT}, 0 = ephemeral)")
    ap.add_argument("--show-hidden", action="store_true",
                    help="include dot-hidden entries")
    ap.add_argument("--open", action="store_true",
                    help="launch the browser once bound")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-request logging")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root_arg = args.root or os.getcwd()
    try:
        lib = MediaLibrary(Path(root_arg), show_hidden=args.show_hidden)
    except OSError as exc:
        print(f"[{APP.lower()}] cannot open root {root_arg!r}: {exc}",
              file=sys.stderr)
        return 2

    handler = type("BoundHandler", (AphroditeHandler,),
                   {"library": lib, "app_dir": APP_DIR})
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    httpd.quiet = args.quiet
    url = f"http://{args.host}:{httpd.server_address[1]}/"

    print(f"{APP} v{VERSION}")
    print(f"  root : {lib.root}")
    print(f"  url  : {url}")
    print(f"  thumbs: {'GDI+' if THUMBS.ok else 'unavailable (serving originals)'}"
          f" -> {lib.cache_dir}")
    print("  local · offline · library read-only — Ctrl+C to stop", flush=True)
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
