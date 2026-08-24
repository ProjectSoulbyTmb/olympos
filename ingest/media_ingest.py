"""media_ingest - multi-source adult media harvester for APHRODITE libraries.

Adapters: dbnaked.com (categories/models/channels, pictures+tube),
pornpics.com (query search, photos), babesource.com (search, photos),
imagefap.com (search, photos), plus v1.1 generic pullers:
  --scan-web URL     enhanced web scan - bounded BFS crawl of ANY site
                     harvesting direct media links into a weblink source
  --from-file LIST   pull from a text list of media/page URLs

v1.1 auto-conversion: everything pulled is converted automatically to
JPEG (images, white-flattened via GDI+, EXIF orientation baked) or MP4
(videos; animated GIFs become MP4 so motion survives). On by default
(--no-auto-convert opts out); --normalize-library converts an existing
tree in place and remaps catalogs.

Design constraints (house rules):
- stdlib only, offline-safe parsers (verify suite runs with zero network)
- polite crawling: per-host delays, retry+backoff, Referer pinning
- resumable: existing non-empty files are skipped; catalogs merged
- bounded: every source has caps; nothing auto-expands beyond config

Usage:
  python tools/media_ingest.py --discover            # resolve sources -> catalogs
  python tools/media_ingest.py --download            # download pending files
  python tools/media_ingest.py --download --only goth
  python tools/media_ingest.py --launch              # detached background run
  python tools/media_ingest.py --clone-source dbnaked-riley-reid-tube --as dbnaked-other-model-tube --set-path "/models/general/O/Other-Model"
  python tools/media_ingest.py --audit-videos        # Riley: integrity+dupes
  python ingest/media_ingest.py --scan-web "https://site.tld/galleries/page/1" --scan-depth 2
  python ingest/media_ingest.py --from-file urls.txt --download
  python ingest/media_ingest.py --normalize-library  # convert whole tree now

Filters:
  --hd-only           tube scenes without HD markers are skipped
  --no-female-filter  disable best-effort tag blacklist (default enabled)
"""
import argparse
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP = "media_ingest"
VERSION = "1.1"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

REFERERS = {
    "i.dbnaked.com": "https://dbnaked.com/",
    "i-cdn.dbnaked.com": "https://dbnaked.com/",
    "flv.dbnaked.com": "https://dbnaked.com/",
    "dbnaked.com": None,
    "www.pornpics.com": "https://www.pornpics.com/",
    "cdni.pornpics.com": "https://www.pornpics.com/",
    "imagefap.com": "https://www.imagefap.com/",
    "cdnc.imagefap.com": "https://www.imagefap.com/",
    "babesource.com": "https://babesource.com/",
    "media.babesource.com": "https://babesource.com/",
    "www.eporner.com": "https://www.eporner.com/",
    "ej.eporner.com": "https://www.eporner.com/",
}

HOST_DELAYS = {
    "dbnaked.com": 1.1,
    "i.dbnaked.com": 0.45,
    "i-cdn.dbnaked.com": 0.45,
    "flv.dbnaked.com": 0.8,
    "www.pornpics.com": 1.6,
    "cdni.pornpics.com": 0.5,
    "imagefap.com": 1.4,
    "cdnc.imagefap.com": 0.5,
    "babesource.com": 1.2,
    "media.babesource.com": 0.6,
    "www.eporner.com": 1.5,
    "ej.eporner.com": 0.6,
}

FEMALE_BLACKLIST = re.compile(
    r"shemale|tranny|ladyboy|transsexual|\bgay\b|\bts\b|"
    r"crossdress|sissy|(?:^|[-_\s/])male(?:[-_\s/]|$)", re.I)

MEDIA_EXT = re.compile(r"\.(jpe?g|png|gif|webp|mp4|m3u8|webm)$", re.I)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sanitize(name, maxlen=80):
    name = re.sub(r"[^\w.\- ]+", "_", name).strip(" ._")
    return name[:maxlen] or "item"


class Fetcher:
    def __init__(self, delay_scale=1.0):
        self.delay_scale = delay_scale
        self._last = {}

    def _throttle(self, host):
        base = HOST_DELAYS.get(host, 1.0) * self.delay_scale
        wait = base + random.uniform(0, base * 0.35)
        now = time.monotonic()
        elapsed = now - self._last.get(host, 0.0)
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last[host] = time.monotonic()

    def headers(self, url, extra=None):
        host = urllib.parse.urlsplit(url).netloc
        h = {"User-Agent": UA}
        ref = REFERERS.get(host)
        if ref:
            h["Referer"] = ref
        if extra:
            h.update(extra)
        return h

    def get(self, url, binary=False, extra=None, retries=3):
        last_err = None
        for attempt in range(retries):
            host = urllib.parse.urlsplit(url).netloc
            self._throttle(host)
            try:
                req = urllib.request.Request(url, headers=self.headers(url, extra))
                with urllib.request.urlopen(req, timeout=40) as r:
                    data = r.read()
                return data if binary else data.decode("utf-8", "replace")
            except Exception as e:
                last_err = e
                backoff = 2 ** attempt * 2
                log(f"  retry {attempt + 1}/{retries} {type(e).__name__}"
                    f" {str(e)[:60]} sleep {backoff}s :: {url[:90]}")
                time.sleep(backoff)
        raise RuntimeError(f"fetch failed after {retries}: {url} ({last_err})")

    def head_size(self, url):
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers=self.headers(url))
            with urllib.request.urlopen(req, timeout=20) as r:
                return int(r.headers.get("Content-Length") or 0)
        except Exception:
            return 0


def abs_url(base, href):
    return urllib.parse.urljoin(base, href.split("&amp;")[0])


def passes_female_filter(text):
    return not FEMALE_BLACKLIST.search(text or "")


# ======================================================================
# v1.1 auto-conversion — every pulled artifact lands as JPEG (images)
# or MP4 (video; animated GIFs included so motion survives). Runs
# automatically during --download and as a standalone --normalize-library
# pass over existing trees. Originals are removed only after a verified
# successful conversion; on any failure the original bytes stay put.
# ======================================================================
FFMPEG_PATH = os.environ.get("MEDIAPULL_FFMPEG")   # optional override
_FFMPEG_CACHE = {"path": False}


def find_ffmpeg():
    """Locate ffmpeg: --ffmpeg flag/env, aphrodite vendor drops, PATH."""
    if _FFMPEG_CACHE["path"]:
        return _FFMPEG_CACHE["path"] or None
    import shutil
    cand = []
    if FFMPEG_PATH:
        cand.append(Path(FFMPEG_PATH))
    here = Path(__file__).resolve().parent
    cand += [here.parent / "aphrodite" / "bin",
             Path("D:/aphrodite/bin"), Path("D:/THOTH/aphrodite/bin")]
    for c in cand:
        if c.is_file():
            _FFMPEG_CACHE["path"] = str(c)
            return str(c)
        exe = c / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if exe.is_file():
            _FFMPEG_CACHE["path"] = str(exe)
            return str(exe)
    which = shutil.which("ffmpeg")
    _FFMPEG_CACHE["path"] = which or ""
    return which


JPEG_SKIP_EXTS = {".jpg", ".jpeg"}
IMAGE_CONV_EXTS = {".png", ".webp", ".bmp", ".tif", ".tiff", ".avif",
                   ".heic", ".heif", ".jfif"}
MP4_SKIP_EXTS = {".mp4", ".m4v"}          # m4v IS an mp4 container
VIDEO_CONV_EXTS = {".mkv", ".mov", ".avi", ".webm", ".ogv", ".flv",
                   ".wmv", ".ts"}


def conversion_route(path):
    """'skip' (already standard) | 'jpeg' | 'video' | 'gif-video'
    | None (not media we touch)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in JPEG_SKIP_EXTS or ext in MP4_SKIP_EXTS:
        return "skip"
    if ext == ".gif":
        return "gif-video"
    if ext in IMAGE_CONV_EXTS:
        return "jpeg"
    if ext in VIDEO_CONV_EXTS:
        return "video"
    return None


class JpegNormalizer:
    """GDI+ (stdlib ctypes) decode-any -> flattened JPEG q90.
    Transparency is composited onto white; EXIF orientation baked."""

    PIXELFORMAT_ARGB = 2498570
    UNIT_PIXEL = 2

    def __init__(self):
        self.ok = False
        self.lock = threading.Lock()
        self.dll = None
        if os.name != "nt":
            return
        try:
            self._bind()
        except Exception:                       # noqa: BLE001 best-effort
            self.ok = False

    def _bind(self):
        import ctypes
        g = ctypes.windll.gdiplus

        class StartupInput(ctypes.Structure):
            _fields_ = [("GdiplusVersion", ctypes.c_uint),
                        ("DebugEventCallback", ctypes.c_void_p),
                        ("SuppressBackgroundThread", ctypes.c_int),
                        ("ExternalSuppression", ctypes.c_int)]

        class PropertyItem(ctypes.Structure):
            _fields_ = [("id", ctypes.c_uint), ("length", ctypes.c_uint),
                        ("type", ctypes.c_int16),
                        ("value", ctypes.c_void_p)]

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
        g.GdipCreateBitmapFromFile.argtypes = (
            ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))
        g.GdipGetImageWidth.argtypes = (ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_uint))
        g.GdipGetImageHeight.argtypes = (ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_uint))
        g.GdipGetPropertyItemSize.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint))
        g.GdipGetPropertyItem.argtypes = (ctypes.c_void_p, ctypes.c_uint,
                                          ctypes.c_uint, ctypes.c_void_p)
        g.GdipImageRotateFlip.argtypes = (ctypes.c_void_p, ctypes.c_int)
        g.GdipCreateBitmapFromScan0.argtypes = (
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        g.GdipGetImageGraphicsContext.argtypes = (
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        g.GdipGraphicsClear.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        g.GdipDrawImageRectRectI.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p)
        g.GdipDeleteGraphics.argtypes = (ctypes.c_void_p,)
        g.GdipSaveImageToFile.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p,
                                          ctypes.c_void_p, ctypes.c_void_p)
        g.GdipDisposeImage.argtypes = (ctypes.c_void_p,)
        self.dll = g
        self._propitem = PropertyItem
        self._encparams = EncoderParams
        self._clsid_jpeg = (ctypes.c_ubyte * 16)(
            0x01, 0xF4, 0x7C, 0x55, 0x04, 0x1A, 0xD3, 0x11,
            0x9A, 0x73, 0x00, 0x00, 0xF8, 0x1E, 0xF3, 0x2E)
        self._guid_quality = (ctypes.c_ubyte * 16)(
            0xB5, 0xE4, 0x5B, 0x1D, 0x4A, 0xFA, 0x2D, 0x45,
            0x9C, 0xDD, 0x5D, 0xB3, 0x51, 0x05, 0xE7, 0xEB)
        self._rotflip = {2: 4, 3: 2, 4: 6, 5: 5, 6: 1, 7: 7, 8: 3}
        self.ok = True

    def _orientation(self, img):
        import ctypes
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

    def to_jpeg(self, src: str, dst: str) -> bool:
        """Decode src (any WIC format) -> dst JPEG, white-flattened."""
        import ctypes
        if not self.ok:
            return False
        with self.lock:
            img = ctypes.c_void_p()
            if self.dll.GdipCreateBitmapFromFile(str(src),
                                                 ctypes.byref(img)) != 0 \
                    or not img.value:
                return False
            try:
                rf = self._rotflip.get(self._orientation(img))
                if rf is not None:
                    self.dll.GdipImageRotateFlip(img, rf)
                w, h = ctypes.c_uint(), ctypes.c_uint()
                if self.dll.GdipGetImageWidth(img, ctypes.byref(w)) != 0 \
                        or self.dll.GdipGetImageHeight(
                            img, ctypes.byref(h)) != 0 \
                        or not w.value or not h.value:
                    return False
                flat = ctypes.c_void_p()
                if self.dll.GdipCreateBitmapFromScan0(
                        w.value, h.value, 0, self.PIXELFORMAT_ARGB,
                        None, ctypes.byref(flat)) != 0 or not flat.value:
                    return False
                gfx = ctypes.c_void_p()
                if self.dll.GdipGetImageGraphicsContext(
                        flat, ctypes.byref(gfx)) != 0 or not gfx.value:
                    self.dll.GdipDisposeImage(flat)
                    return False
                self.dll.GdipGraphicsClear(gfx, 0xFFFFFFFF)   # white base
                self.dll.GdipDrawImageRectRectI(
                    gfx, img, 0, 0, w.value, h.value,
                    0, 0, w.value, h.value,
                    self.UNIT_PIXEL, None, None, None)
                self.dll.GdipDeleteGraphics(gfx)
                quality = ctypes.c_ulong(90)
                params = self._encparams(count=1)
                params.parameter[0].guid = self._guid_quality
                params.parameter[0].numberOfValues = 1
                params.parameter[0].type = 4                  # long
                params.parameter[0].value = ctypes.cast(
                    ctypes.byref(quality), ctypes.c_void_p)
                ok = self.dll.GdipSaveImageToFile(
                    flat, str(dst), ctypes.byref(self._clsid_jpeg),
                    ctypes.byref(params)) == 0
                self.dll.GdipDisposeImage(flat)
                return ok
            finally:
                self.dll.GdipDisposeImage(img)


JPEG_NORM = JpegNormalizer()


def convert_video(path, ffmpeg=None):
    """Transcode/remux any container to H.264 MP4 (+faststart).
    Returns final path or None on failure (original untouched)."""
    ff = ffmpeg or find_ffmpeg()
    if not ff:
        return None
    import subprocess
    root, _ = os.path.splitext(path)
    final = root + ".mp4"
    tmp = root + ".conv.mp4"          # .mp4 tail so ffmpeg infers muxer
    for mode in ("remux", "transcode"):
        cmd = [ff, "-y", "-i", path]
        if mode == "remux":
            cmd += ["-c", "copy"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-movflags", "+faststart", tmp]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=3600)
        except Exception:                     # noqa: BLE001
            return None
        if res.returncode == 0 and os.path.exists(tmp) \
                and os.path.getsize(tmp) > 0:
            break
        try:
            os.unlink(tmp)
        except OSError:
            pass
    else:
        return None
    os.replace(tmp, final)
    return final


def normalize_file(path, ffmpeg=None):
    """Convert one artifact to its standard form (.jpg/.mp4).
    Returns the final path (same input when already standard);
    never deletes the original unless conversion succeeded."""
    route = conversion_route(path)
    if route is None or route == "skip":
        return path
    root, ext = os.path.splitext(path)
    try:
        if route == "jpeg":
            final = root + ".jpg"
            tmp = root + ".norm.jpg"
            if JPEG_NORM.to_jpeg(path, tmp) \
                    and os.path.getsize(tmp) > 0:
                if os.path.exists(final):
                    os.unlink(final)
                os.replace(tmp, final)
                os.unlink(path)
                return final
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return path
        # video routes
        if route == "gif-video":
            ff = ffmpeg or find_ffmpeg()
            if not ff:
                return path                 # no tooling -> keep original
            final = root + ".mp4"
            tmp = root + ".conv.mp4"
            import subprocess
            res = subprocess.run(
                [ff, "-y", "-i", path, "-movflags", "+faststart",
                 "-pix_fmt", "yuv420p", tmp],
                capture_output=True, timeout=3600)
            if res.returncode == 0 and os.path.exists(tmp) \
                    and os.path.getsize(tmp) > 0:
                os.replace(tmp, final)
                os.unlink(path)
                return final
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return path
        got = convert_video(path, ffmpeg=ffmpeg)
        if got and got != path:
            os.unlink(path)
            return got
        return path
    except OSError:
        return path


# ======================================================================
# v1.1 enhanced web scan — generic crawler for ANY site: BFS over page
# links (depth/host/pattern bounded), harvesting direct media URLs from
# img/src/data-src/srcset/href/content attributes. Discovered media is
# registered as pre-materialized catalog entries, so the normal
# --download pipeline (with auto-JPEG/MP4 conversion) picks them up.
# ======================================================================
PAGE_HREF_RE = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\'#]+)', re.I)
# longest-first alternation so "srcset" isn't eaten by "src"
ATTR_VALUE_RE = re.compile(
    r'(?:srcset|data-src|data-original|poster|content|href|src)'
    r'\s*=\s*(["\'])(.*?)\1', re.I)
MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp",
              ".mp4", ".webm", ".m3u8")


def extract_media_urls(html, base_url):
    """All direct media URLs referenced by a page (abs-resolved, unique).
    Attribute values are taken whole so srcset lists survive, then each
    whitespace/comma-separated token is checked against MEDIA_EXTS."""
    out = set()
    for m in ATTR_VALUE_RE.finditer(html or ""):
        for part in re.split(r"[,\s]+", m.group(2) or ""):
            part = part.strip()
            if part and part.lower().endswith(MEDIA_EXTS):
                out.add(abs_url(base_url, part))
    return sorted(out)


def extract_page_links(html, base_url):
    out = []
    for m in PAGE_HREF_RE.finditer(html or ""):
        out.append(abs_url(base_url, m.group(1)))
    return sorted(set(out))


class WebScanner:
    """Polite bounded BFS crawler over arbitrary sites."""

    def __init__(self, fetcher, depth=2, max_pages=40, same_host=True,
                 pattern=None, female_filter=True):
        self.f = fetcher
        self.depth = max(0, depth)
        self.max_pages = max_pages
        self.same_host = same_host
        self.pattern = re.compile(pattern) if pattern else None
        self.female = female_filter

    def _want_page(self, url, seed_host):
        host = urllib.parse.urlsplit(url).netloc
        if self.same_host and host != seed_host:
            return False
        if self.pattern and not self.pattern.search(url):
            return False
        return True

    def scan(self, seeds):
        seen_pages, media, frontier = set(), set(), [(u, 0) for u in seeds]
        errors = []
        seed_host = urllib.parse.urlsplit(seeds[0]).netloc
        while frontier and len(seen_pages) < self.max_pages:
            url, d = frontier.pop(0)
            if url in seen_pages or d > self.depth:
                continue
            if not self._want_page(url, seed_host):
                continue
            seen_pages.add(url)
            try:
                html = self.f.get(url)
            except Exception as ex:          # noqa: BLE001 — keep crawling
                errors.append(f"{type(ex).__name__}: {str(ex)[:80]}")
                continue
            found = extract_media_urls(html, url)
            if self.same_host:
                found = [u for u in found if
                         urllib.parse.urlsplit(u).netloc == seed_host]
            media.update(found)
            if d < self.depth:
                for link in extract_page_links(html, url):
                    if link not in seen_pages \
                            and self._want_page(link, seed_host):
                        frontier.append((link, d + 1))
        kept = [u for u in sorted(media)
                if self.female_pass(u)]
        dropped = len(media) - len(kept)
        return {"pages_seen": len(seen_pages),
                "media_found": len(media),
                "media_kept": len(kept),
                "filtered": dropped,
                "errors": errors[:10],
                "urls": kept}

    def female_pass(self, url):
        return not self.female or passes_female_filter(url)


def kind_of_url(url):
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith((".mp4", ".webm", ".m3u8")):
        return "tube"
    return "pictures"


def build_weblink_entries(urls):
    """Pre-materialized catalog entries: --download consumes them
    without needing a site-specific materializer."""
    entries = []
    for u in urls:
        fname = urllib.parse.urlsplit(u).path.rsplit("/", 1)[-1] or u
        stem = os.path.splitext(fname)[0] or fname
        entries.append({"url": u, "slug": sanitize(stem),
                        "kind": kind_of_url(u),
                        "state": "direct",
                        "files": [{"url": u, "file": None, "bytes": 0,
                                   "done": False}],
                        "meta": {"title": stem}})
    return entries


class DbNaked:
    HOST = "https://dbnaked.com"
    KIND_PREFIX = {"pictures": "pictures", "tube": "tube"}

    def __init__(self, f):
        self.f = f

    def discover_categories(self, realms=("general", "bdsm"),
                            media=("pictures", "tube"), pattern=None):
        pat = re.compile(pattern, re.I) if pattern else None
        found = {}
        for realm in realms:
            for med in media:
                url = f"{self.HOST}/{realm}/categories?media={med}"
                try:
                    html = self.f.get(url)
                except RuntimeError as e:
                    log(f"  discover fail {realm}/{med}: {e}")
                    continue
                cats = sorted(set(re.findall(
                    rf'href="(/categories/{med}/{realm}/[^"]+)"', html)))
                for c in cats:
                    if med == "tube" and c.startswith("/categories/pictures/"):
                        continue
                    if med == "pictures" and c.startswith("/categories/tube/"):
                        continue
                    if pat is None or pat.search(c):
                        found[c] = f"{self.HOST}{c}"
        return found

    def walk_listing(self, url, item_regex, max_pages=40):
        seen_pages = set()
        queue = [url]
        items = []
        while queue and len(seen_pages) < max_pages:
            page_url = queue.pop(0)
            norm = re.sub(r"/\d+(/?)$", "", page_url.split("?")[0])
            if norm in seen_pages:
                continue
            seen_pages.add(norm)
            try:
                html = self.f.get(page_url)
            except RuntimeError as e:
                log(f"  listing fail {page_url[:80]}: {e}")
                continue
            for m in re.finditer(item_regex, html):
                link = m.group(1)
                if passes_female_filter(link):
                    items.append(abs_url(page_url, link))
            links = re.findall(r'href="([^"]+)"', html)
            base_sort = page_url.rstrip("/").rsplit("/", 1)[-1]
            for l in links:
                al = abs_url(page_url, l)
                if not al.startswith(self.HOST):
                    continue
                path = urllib.parse.urlsplit(al).path
                if re.search(rf'/(?:{base_sort})/\d+$', path) or \
                   re.search(r"/(?:latest|most-popular|top-rated|most-viewed)/\d+$",
                             path):
                    if al not in queue and passes_female_filter(al):
                        queue.append(al)
        return sorted(set(items))

    def category_items(self, cat_path, kind):
        rx = (rf'href="(/{self.KIND_PREFIX[kind]}/content/[^"#]+?\d_[^"#]+)"')
        return self.walk_listing(f"{self.HOST}{cat_path}", rx)

    def model_items(self, model_path, kind, max_pages=25):
        rx = (rf'href="(/(?:pictures|tube)/content/[^"#]+?\d_[^"#]+)"')
        base = f"{self.HOST}{model_path}/{kind}/latest"
        return self.walk_listing(base, rx, max_pages=max_pages)

    def channel_items(self, domain, realm="bdsm", kind="pictures"):
        url = (f"{self.HOST}/{realm}/channels/{domain}"
               f"?media={kind}&sort=latest")
        rx = rf'href="(/(?:pictures|tube)/content/[^"#]+?\d_[^"#]+)"'
        return [u for u in self.walk_listing(url, rx)
                if f"/{kind}/content/" in u]

    def parse_gallery(self, url):
        html = self.f.get(url)
        title_m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*@.*$", "", title_m.group(1)).strip()
                 if title_m else sanitize(url.rsplit("/", 1)[-1]))
        og = re.search(r'property="og:image"\s+content="([^"]+)"', html)
        scene_id_m = re.search(r"/(\d+)_", url)
        imgs = []
        if og:
            sample = og.group(1)
            m = re.match(r"(?:(?:https?:))?//([^/]+)/(.+)/(\d+)\.(jpg|webp|png)",
                         sample)
            if m:
                host, dirpath, n, ext = m.groups()
                thumb_host = host.replace("i-cdn.", "i.", 1)
                ids = sorted({int(x) for x in re.findall(
                    rf"//{re.escape(thumb_host)}"
                    rf"/scene/\d+/[a-z0-9]+/(\d+)\.jpg", html)})
                if not ids:
                    ids = list(range(1, 16))
                imgs = [f"https://{host}/{dirpath}/{i}.{ext}" for i in ids]
        if not imgs:
            thumbs = re.findall(
                r'<img[^>]+src="//(i\.dbnaked\.com)/scene/(\d+)/t\d+x\d+/(\d+)\.jpg"',
                html)
            if thumbs:
                host, sid = thumbs[0][0], thumbs[0][1]
                nums = sorted({int(t[2]) for t in thumbs})
                sm = re.match(
                    r".*/content/([a-z]+)/sites/([^/]+)/(.+)", url)
                if sm:
                    cat, site, slug = sm.groups()
                    cdn = host.replace("i.", "i-cdn.", 1)
                    imgs = [f"https://{cdn}/{cat}/{site}/{slug}/{i}.jpg"
                            for i in nums]
        meta = {"title": title, "scene_id": scene_id_m.group(1)
                if scene_id_m else None}
        return imgs, meta

    def parse_scene(self, url):
        html = self.f.get(url)
        title_m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*[-@].*db[Nn]aked.*$", "", title_m.group(1)).strip()
                 if title_m else sanitize(url.rsplit("/", 1)[-1]))
        norm = html.replace("\\/", "/").replace("\\u0026", "&")
        vids = re.findall(r'"((?:https?:)?//flv\d*\.dbnaked\.com[^"]+\.mp4[^"]*)"',
                          norm)
        hd = bool(re.search(r"\bHD\b|1080p?", html)) or \
            bool(re.search(r"\b720p?\b", html))
        dur = re.search(r'"duration"\s*:\s*(\d+)', html)
        meta = {"title": title, "hd": hd,
                "duration_s": int(dur.group(1)) if dur else None}
        return sorted(set(vids)), meta


class PornPics:
    HOST = "https://www.pornpics.com"

    def __init__(self, f):
        self.f = f

    def query_galleries(self, q, cap=40):
        html = self.f.get(f"{self.HOST}/?q={urllib.parse.quote(q)}")
        gals = list(dict.fromkeys(re.findall(
            r'href="(https://www\.pornpics\.com/galleries/[^"]+)"', html)))
        return gals[:cap]

    def parse_gallery(self, url):
        html = self.f.get(url)
        t = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*\|.*$", "", t.group(1)).strip()
                 if t else sanitize(url.strip("/").rsplit("/", 1)[-1]))
        rel = re.findall(r"class=['\"]rel-link['\"]\s+href=['\"]([^'\"]+)"
                         r"['\"]", html)
        if not rel:
            rel = re.findall(
                r"href=['\"](https://cdni\.pornpics\.com/[^'\"]+"
                r"\.(?:jpg|png))['\"]", html)
        imgs = [abs_url(url, u) for u in dict.fromkeys(rel)]
        return imgs, {"title": title}


class ImageFap:
    HOST = "https://www.imagefap.com"

    def __init__(self, f):
        self.f = f

    def search_galleries(self, search, pages=5, perpage=10):
        gals = []
        for p in range(pages):
            url = (f"{self.HOST}/gallery.php?type=1&userid=&gen=0&search="
                   f"{urllib.parse.quote(search)}&page={p}&perpage={perpage}")
            try:
                html = self.f.get(url)
            except RuntimeError:
                break
            found = re.findall(r'href="(/gallery\.php\?gid=\d+)"', html)
            new = [f"{self.HOST}{g}" for g in dict.fromkeys(found)
                   if f"{self.HOST}{g}" not in gals]
            gals.extend(new)
            if not new:
                break
        return gals

    def parse_gallery(self, url):
        html = self.f.get(url)
        t = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (re.sub(r"\s*(?:Porn Pics|@.*)*$", "", t.group(1)).strip()
                 if t else sanitize(url))
        photo_links = list(dict.fromkeys(
            re.findall(r'href="(/photo/\d+/[^"]*)"', html)))
        fulls = []
        if photo_links:
            p1 = self.f.get(self.HOST + photo_links[0].split("?")[0])
            norm = p1.replace("\\/", "/")
            fulls = list(dict.fromkeys(re.findall(
                r'"(https://cdnc\.imagefap\.com/images/full/[^"]+)"', norm)))
            if len(fulls) < len(photo_links):
                seen_ids = {re.search(r"/(\d+)\.jpg", u).group(1)
                            for u in fulls}
                for pl in photo_links[1:]:
                    pid = re.search(r"/photo/(\d+)/", pl).group(1)
                    if pid in seen_ids:
                        continue
                    if len(fulls) >= len(photo_links):
                        break
                    try:
                        pp = self.f.get(self.HOST +
                                        pl.split("?")[0]).replace("\\/", "/")
                    except RuntimeError:
                        continue
                    more = re.findall(
                        r'"(https://cdnc\.imagefap\.com/images/full/[^"]+)"',
                        pp)
                    for u in more:
                        mid = re.search(r"/(\d+)\.jpg", u).group(1)
                        if mid not in seen_ids:
                            seen_ids.add(mid)
                            fulls.append(u)
        return fulls, {"title": title}


class BabeSource:
    HOST = "https://babesource.com"

    def __init__(self, f):
        self.f = f

    def search_galleries(self, term, cap=120):
        html = self.f.get(f"{self.HOST}/?s={urllib.parse.quote(term)}")
        gals = list(dict.fromkeys(re.findall(
            r'href="(https://babesource\.com/galleries/[^"]+)"', html)))
        return gals[:cap]

    def parse_gallery(self, url):
        html = self.f.get(url)
        t = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (t.group(1).strip() if t else
                 sanitize(url.strip("/").rsplit("/", 1)[-1]))
        imgs = list(dict.fromkeys(re.findall(
            r'"((?:https?://)?(?:media\.)?babesource\.com/media/galleries/'
            r'[^"]+\.(?:jpg|webp|png))"', html)))
        imgs = [("https:" if u.startswith("//") else "") + u for u in imgs]
        return imgs, {"title": title}


SEED_SOURCES = [
    {"name": "bdsm-gothic", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Gothic", "kind": "pictures"},
    {"name": "dbnaked-tattoo-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Tattoo", "kind": "pictures"},
    {"name": "dbnaked-tattoo-alt-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Tattoo", "kind": "pictures"},
    {"name": "dbnaked-alt-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Alternative", "kind": "pictures"},
    {"name": "dbnaked-punk-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Punk", "kind": "pictures"},
    {"name": "dbnaked-feet-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Foot_Fetish", "kind": "pictures"},
    {"name": "dbnaked-footjob-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/general/Footjob", "kind": "pictures"},
    {"name": "dbnaked-feet-bdsm-pics", "adapter": "dbnaked_category",
     "path": "/categories/pictures/bdsm/Foot_Fetish", "kind": "pictures"},
    {"name": "dbnaked-feet-tube", "adapter": "dbnaked_category",
     "path": "/categories/tube/general/Foot_Fetish", "kind": "tube"},
    {"name": "dbnaked-footjob-tube", "adapter": "dbnaked_category",
     "path": "/categories/tube/general/Footjob", "kind": "tube"},
    {"name": "dbnaked-tattoo-tube", "adapter": "dbnaked_category",
     "path": "/categories/tube/general/Tattoo", "kind": "tube"},
    {"name": "dbnaked-riley-reid-pics", "adapter": "dbnaked_model",
     "path": "/models/general/R/riley-reid", "kind": "pictures"},
    {"name": "dbnaked-riley-reid-tube", "adapter": "dbnaked_model",
     "path": "/models/general/R/riley-reid", "kind": "tube"},
    {"name": "dbnaked-piper-perri-pics", "adapter": "dbnaked_model",
     "path": "/models/general/P/Piper-Perri", "kind": "pictures"},
    {"name": "dbnaked-piper-perri-tube", "adapter": "dbnaked_model",
     "path": "/models/general/P/Piper-Perri", "kind": "tube"},
    {"name": "dbnaked-joanna-angel-pics", "adapter": "dbnaked_model",
     "path": "/models/general/J/Joanna-Angel", "kind": "pictures"},
    {"name": "dbnaked-joanna-angel-tube", "adapter": "dbnaked_model",
     "path": "/models/general/J/Joanna-Angel", "kind": "tube"},
    {"name": "dbnaked-kleio-valentien-pics", "adapter": "dbnaked_model",
     "path": "/models/general/K/Kleio-Valentien", "kind": "pictures"},
    {"name": "dbnaked-kleio-valentien-tube", "adapter": "dbnaked_model",
     "path": "/models/general/K/Kleio-Valentien", "kind": "tube"},
    {"name": "dbnaked-charlotte-sartre-pics", "adapter": "dbnaked_model",
     "path": "/models/general/C/Charlotte-Sartre", "kind": "pictures"},
    {"name": "dbnaked-charlotte-sartre-tube", "adapter": "dbnaked_model",
     "path": "/models/general/C/Charlotte-Sartre", "kind": "tube"},
    {"name": "dbnaked-rocky-emerson-pics", "adapter": "dbnaked_model",
     "path": "/models/general/R/Rocky-Emerson", "kind": "pictures"},
    {"name": "dbnaked-rocky-emerson-tube", "adapter": "dbnaked_model",
     "path": "/models/general/R/Rocky-Emerson", "kind": "tube"},
    {"name": "dbnaked-draven-star-pics", "adapter": "dbnaked_model",
     "path": "/models/general/D/Draven-Star", "kind": "pictures"},
    {"name": "dbnaked-draven-star-tube", "adapter": "dbnaked_model",
     "path": "/models/general/D/Draven-Star", "kind": "tube"},
    {"name": "dbnaked-leigh-raven-pics", "adapter": "dbnaked_model",
     "path": "/models/general/L/Leigh-Raven", "kind": "pictures"},
    {"name": "dbnaked-leigh-raven-tube", "adapter": "dbnaked_model",
     "path": "/models/general/L/Leigh-Raven", "kind": "tube"},
    {"name": "burningangel-pics", "adapter": "dbnaked_channel",
     "domain": "burningangel.com", "realm": "bdsm", "kind": "pictures"},
    {"name": "burningangel-tube", "adapter": "dbnaked_channel",
     "domain": "burningangel.com", "realm": "bdsm", "kind": "tube"},
    {"name": "pornpics-goth", "adapter": "pornpics_query", "queries":
        ["goth", "gothic", "alt girl", "emo"]},
    {"name": "pornpics-tattoo", "adapter": "pornpics_query",
     "queries": ["tattooed", "tattoo", "pierced", "inked"]},
    {"name": "pornpics-feet", "adapter": "pornpics_query",
     "queries": ["feet", "foot fetish", "foot worship", "barefoot"]},
    {"name": "imagefap-goth-feet", "adapter": "imagefap_search",
     "search": "goth feet", "pages": 8},
    {"name": "imagefap-goth-tattoo", "adapter": "imagefap_search",
     "search": "goth tattoo", "pages": 8},
    {"name": "imagefap-tattooed-feet", "adapter": "imagefap_search",
     "search": "tattooed feet", "pages": 8},
    {"name": "imagefap-gothic", "adapter": "imagefap_search",
     "search": "gothic", "pages": 8},
    {"name": "imagefap-emo-feet", "adapter": "imagefap_search",
     "search": "emo feet", "pages": 8},
    {"name": "babesource-goth", "adapter": "babesource_search",
     "queries": ["goth", "gothic", "emo"]},
    {"name": "babesource-tattoo", "adapter": "babesource_search",
     "queries": ["tattoo", "tattooed", "pierced", "inked"]},
    {"name": "babesource-feet", "adapter": "babesource_search",
     "queries": ["feet", "foot fetish", "barefoot"]},
]

AESTHETIC_PATTERN = (r"foot|feet|tattoo|goth|punk|/alt$|alt/|ink|"
                     r"pierc|emo|latex|leather|domina|femdom")
DYNAMIC_CAP = 16


def discover_dynamic_sources(fetcher, known_paths):
    dn = DbNaked(fetcher)
    found = dn.discover_categories(realms=("general", "bdsm"),
                                   media=("pictures", "tube"),
                                   pattern=AESTHETIC_PATTERN)
    specs = []
    for path in sorted(found):
        if path in known_paths:
            continue
        if not passes_female_filter(path):
            log(f"dynamic source rejected (female-filter): {path}")
            continue
        kind = "tube" if "/tube/" in path else "pictures"
        slug = (path.replace("/categories/", "")
                .strip("/").replace("/", "-").lower())
        slug = re.sub(r"[^a-z0-9\-]+", "-", slug)
        specs.append({"name": f"auto-{slug}", "adapter": "dbnaked_category",
                      "path": path, "kind": kind, "dynamic": True})
        if len(specs) >= DYNAMIC_CAP:
            break
    return specs


def enumerate_source(src, fetcher, female_filter=True):
    ad = DbNaked(fetcher)
    pp = PornPics(fetcher)
    bs = BabeSource(fetcher)
    entries = []
    a = src["adapter"]
    try:
        if a == "dbnaked_category":
            items = ad.category_items(src["path"], src["kind"])
        elif a == "dbnaked_model":
            items = ad.model_items(src["path"], src["kind"])
        elif a == "dbnaked_channel":
            items = ad.channel_items(src["domain"], src.get("realm", "bdsm"),
                                     src["kind"])
        elif a == "pornpics_query":
            items = []
            for q in src["queries"]:
                items += pp.query_galleries(q)
            items = sorted(set(items))
        elif a == "imagefap_search":
            items = ImageFap(fetcher).search_galleries(
                src["search"], pages=src.get("pages", 5))
        elif a == "babesource_search":
            items = []
            for q in src["queries"]:
                items += bs.search_galleries(q)
            items = sorted(set(items))
        else:
            raise ValueError(a)
    except RuntimeError as e:
        log(f"  ENUM FAIL {src['name']}: {e}")
        return entries
    for item_url in items:
        slug = sanitize(item_url.rstrip("/").rsplit("/", 1)[-1])
        entry = {"url": item_url, "slug": slug,
                 "kind": src.get("kind", "pictures")}
        if female_filter and not passes_female_filter(item_url):
            entry["skipped"] = "female-filter"
        entries.append(entry)
    log(f"  {src['name']}: {len(entries)} items "
        f"({sum(1 for e in entries if e.get('skipped'))} filtered)")
    return entries


def materialize_entry(entry, fetcher, hd_only=True):
    kind = entry["kind"]
    url = entry["url"]
    if "dbnaked.com" in url:
        ad = DbNaked(fetcher)
        if kind == "tube" or "/tube/content/" in url:
            files, meta = ad.parse_scene(url)
            if hd_only and not meta.get("hd"):
                return [], meta, "not-hd"
        else:
            files, meta = ad.parse_gallery(url)
    elif "pornpics.com" in url:
        files, meta = PornPics(fetcher).parse_gallery(url)
    elif "imagefap.com" in url:
        files, meta = ImageFap(fetcher).parse_gallery(url)
    elif "babesource.com" in url:
        files, meta = BabeSource(fetcher).parse_gallery(url)
    else:
        return [], {}, "unknown-host"
    return files, meta, None


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def cmd_discover(args):
    fetcher = Fetcher(delay_scale=args.speed)
    master = load_json(args.catalog, {"v": VERSION, "sources": {}})
    if not args.no_discover_extra:
        known_paths = {s.get("path") for s in SEED_SOURCES if s.get("path")}
        for info in master["sources"].values():
            spath = load_json(os.path.join(info["dir"], "_source.json"),
                              None)
            if spath and spath["spec"].get("path"):
                known_paths.add(spath["spec"]["path"])
        extra = discover_dynamic_sources(fetcher, known_paths)
        for spec in extra:
            log(f"dynamic source discovered: {spec['name']} -> "
                f"{spec['path']}")
        sources = list(SEED_SOURCES) + extra
    else:
        sources = list(SEED_SOURCES)
    for src in sources:
        if args.only and args.only.lower() not in src["name"].lower():
            continue
        log(f"source {src['name']} [{src['adapter']}]")
        sdir = os.path.join(args.out, src["name"])
        os.makedirs(sdir, exist_ok=True)
        spath = os.path.join(sdir, "_source.json")
        scat = load_json(spath, {"name": src["name"], "spec": src,
                                 "items": []})
        known = {e["url"]: e for e in scat["items"]}
        entries = enumerate_source(src, fetcher,
                                   female_filter=not args.no_female_filter)
        for e in entries:
            old = known.get(e["url"])
            if old and old.get("files") is not None:
                e["files"] = old["files"]
                e["meta"] = old.get("meta")
                e["state"] = old.get("state")
                e["folder"] = old.get("folder")
            known[e["url"]] = e
        scat["items"] = list(known.values())
        scat["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_json(spath, scat)
        master["sources"][src["name"]] = {
            "dir": sdir, "items": len(scat["items"]),
            "materialized": sum(1 for e in scat["items"]
                                if e.get("files")),
            "updated_at": scat["updated_at"]}
        save_json(args.catalog, master)
    log(f"master catalog: {args.catalog}")
    total_items = sum(v["items"] for v in master["sources"].values())
    total_mat = sum(v["materialized"] for v in master["sources"].values())
    log(f"totals: {len(master['sources'])} sources, {total_items} items,"
        f" {total_mat} materialized")


def maybe_convert(fe, stats, ffmpeg=None):
    """Auto-convert one downloaded file to .jpg/.mp4; update the
    catalog entry pointer. Silent no-op for already-standard files."""
    target = fe.get("file")
    if not target or not os.path.exists(target):
        return
    route = conversion_route(target)
    if route is None or route == "skip":
        return
    final = normalize_file(target, ffmpeg=ffmpeg)
    if final != target:
        fe["file"] = final
        stats["converted"] += 1
    else:
        stats["unconverted"] += 1


def cmd_download(args):
    fetcher = Fetcher(delay_scale=args.speed)
    master = load_json(args.catalog, {"v": VERSION, "sources": {}})
    dl_root = args.out
    ffmpeg = find_ffmpeg()
    stats = {"files": 0, "bytes": 0, "skip": 0, "fail": 0,
             "filtered": 0, "converted": 0, "unconverted": 0}
    for name, info in sorted(master["sources"].items()):
        if args.only and args.only.lower() not in name.lower():
            continue
        spath = os.path.join(info["dir"], "_source.json")
        scat = load_json(spath, None)
        if not scat:
            continue
        log(f"== {name} ==")
        for e in scat["items"]:
            if e.get("skipped"):
                stats["filtered"] += 1
                continue
            if e.get("files") is None:
                files, meta, why = materialize_entry(
                    e, fetcher, hd_only=args.hd_only)
                if why == "not-hd":
                    e["state"] = "not-hd"
                    continue
                if why or not files:
                    e["state"] = why or "no-files"
                    continue
                e["files"] = [{"url": u, "file": None, "bytes": 0,
                               "done": False} for u in files]
                e["meta"] = meta
            if not e.get("folder"):
                e["folder"] = sanitize(e.get("meta", {}).get("title")
                                       or e["slug"])
            if args.dry_run:
                for fe in e["files"]:
                    if not fe["done"]:
                        stats["files"] += 1
                        stats["bytes"] += fe["bytes"] or 0
                continue
            folder = os.path.join(info["dir"], e["folder"])
            os.makedirs(folder, exist_ok=True)
            for i, fe in enumerate(e["files"], 1):
                target = fe["file"] or os.path.join(
                    folder, f"{e['slug']}_{i:03d}" +
                    os.path.splitext(urllib.parse.urlsplit(fe["url"]).path)[1])
                # a prior auto-convert may have renamed this artifact
                if args.auto_convert and conversion_route(target) \
                        not in (None, "skip") \
                        and not os.path.exists(target):
                    alt = os.path.splitext(target)[0] + ".jpg"
                    alt2 = os.path.splitext(target)[0] + ".mp4"
                    for cand in (alt, alt2):
                        if os.path.exists(cand):
                            fe["file"] = cand
                            break
                fe["file"] = fe["file"] or target
                target = fe["file"]
                if os.path.exists(target) and os.path.getsize(target) > 0:
                    fe["done"] = True
                    stats["skip"] += 1
                    if args.auto_convert:
                        maybe_convert(fe, stats, ffmpeg=ffmpeg)
                    continue
                try:
                    data = fetcher.get(fe["url"], binary=True)
                    tmp = target + ".part"
                    with open(tmp, "wb") as fh:
                        fh.write(data)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp, target)
                    fe["done"] = True
                    fe["bytes"] = len(data)
                    stats["files"] += 1
                    stats["bytes"] += len(data)
                    if args.auto_convert:
                        maybe_convert(fe, stats, ffmpeg=ffmpeg)
                except Exception as ex:
                    stats["fail"] += 1
                    log(f"  DL FAIL {fe['url'][:80]}: {ex}")
            save_json(spath, scat)
        save_json(spath, scat)
    log(f"download summary: +{stats['files']} files "
        f"({stats['bytes'] / 1e6:.1f} MB), {stats['skip']} resumed-skips,"
        f" {stats['fail']} failures, {stats['filtered']} filtered,"
        f" {stats['converted']} converted"
        + (f", {stats['unconverted']} unconverted"
           if stats["unconverted"] else ""))


def register_weblink_source(master, catalog_path, out_dir, name,
                            urls, spec_extra=None):
    """Create/refresh a weblink source in the master catalog so
    --download picks the URLs up through the normal pipeline."""
    sdir = os.path.join(out_dir, name)
    os.makedirs(sdir, exist_ok=True)
    spath = os.path.join(sdir, "_source.json")
    scat = load_json(spath, None) or {
        "name": name, "spec": {"name": name, "adapter": "weblink"},
        "items": []}
    known = {e["url"] for e in scat["items"]}
    entries = build_weblink_entries(u for u in urls if u not in known)
    scat["items"].extend(entries)
    if spec_extra:
        scat["spec"].update(spec_extra)
    scat["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(spath, scat)
    master["sources"][name] = {
        "dir": sdir, "items": len(scat["items"]),
        "materialized": sum(1 for e in scat["items"] if e.get("files")),
        "updated_at": scat["updated_at"]}
    save_json(catalog_path, master)
    return len(entries)


def cmd_scan_web(args):
    """Enhanced web scan: BFS-crawl from seed URL(s), harvest direct
    media links, register them as a weblink source."""
    fetcher = Fetcher(delay_scale=args.speed)
    scanner = WebScanner(fetcher, depth=args.scan_depth,
                         max_pages=args.scan_max_pages,
                         same_host=not args.scan_any_host,
                         pattern=args.scan_pattern,
                         female_filter=not args.no_female_filter)
    seeds = [u.strip() for u in args.scan_web.split(",") if u.strip()]
    log(f"web scan: {len(seeds)} seed(s), depth={args.scan_depth}, "
        f"max_pages={args.scan_max_pages}")
    report = scanner.scan(seeds)
    host = sanitize(urllib.parse.urlsplit(seeds[0]).netloc
                    or "scan").replace(".", "-")
    name = args.scan_name or f"webscan-{host}-{args.scan_depth}d"
    if report["media_kept"]:
        master = load_json(args.catalog, {"v": VERSION, "sources": {}})
        added = register_weblink_source(master, args.catalog, args.out,
                                        name, report["urls"])
        log(f"weblink source '{name}': +{added} media urls")
    else:
        log("web scan found no usable media")
    report.update({"source": name, "seeds": seeds})
    rpath = args.scan_report or os.path.join(
        os.path.dirname(args.catalog), "webscan-report.json")
    save_json(rpath, report)
    log(f"report: {rpath}")


def cmd_from_list(args):
    """Pull from a text file: one URL per line (# comments allowed).
    Direct media URLs become direct downloads; gallery-page URLs on
    known hosts can be materialized by re-running with their adapter."""
    urls = []
    with open(args.from_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not passes_female_filter(line) \
                    and not args.no_female_filter:
                log(f"list url filtered (female-filter): {line[:70]}")
                continue
            urls.append(line)
    base = os.path.splitext(os.path.basename(args.from_file))[0]
    name = args.scan_name or f"list-{sanitize(base).lower()}"
    media = [u for u in urls if MEDIA_EXT.search(urllib.parse.urlsplit(u).path)]
    pages = [u for u in urls if u not in media]
    master = load_json(args.catalog, {"v": VERSION, "sources": {}})
    added = 0
    if media:
        added += register_weblink_source(master, args.catalog, args.out,
                                         name, media)
    for page_url in pages:                     # known-host galleries
        host_hit = next((h for h in ("dbnaked.com", "pornpics.com",
                                     "imagefap.com", "babesource.com")
                         if h in page_url), None)
        if host_hit and args.auto_scan_pages:
            sub = cmd_scan_web_args(page_url, args, name_hint=f"{name}-pg")
            added += sub
        else:
            log(f"page url skipped (no generic adapter): "
                f"{page_url[:70]}")
    log(f"from-list '{name}': +{added} direct media urls "
        f"({len(pages)} page urls seen)")


def cmd_scan_web_args(url, args, name_hint=None):
    """Shared single-seed scan used by --from-file page fallback."""
    fetcher = Fetcher(delay_scale=args.speed)
    scanner = WebScanner(fetcher, depth=max(1, args.scan_depth),
                         max_pages=args.scan_max_pages,
                         same_host=not args.scan_any_host,
                         pattern=args.scan_pattern,
                         female_filter=not args.no_female_filter)
    report = scanner.scan([url])
    name = name_hint or f"webscan-scan"
    if report["media_kept"]:
        master = load_json(args.catalog, {"v": VERSION, "sources": {}})
        added = register_weblink_source(master, args.catalog, args.out,
                                        name, report["urls"])
        return added
    return 0


def cmd_normalize_library(args):
    """One-shot conversion pass over an existing downloaded tree:
    every image becomes .jpg, every video becomes .mp4; catalogs are
    remapped so resume state keeps pointing at real files."""
    root = args.out
    converted, kept, failed = [], [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            if fn.startswith("_") or fn.endswith(".part") \
                    or fn.endswith(".json"):
                continue
            route = conversion_route(p)
            if route is None or route == "skip":
                continue
            final = normalize_file(p, ffmpeg=find_ffmpeg())
            if final != p:
                converted.append((p, final))
            elif conversion_route(p) not in (None,) \
                    and os.path.exists(p) \
                    and os.path.splitext(p)[1].lower() != ".mp4" \
                    and os.path.splitext(p)[1].lower() not in JPEG_SKIP_EXTS:
                failed.append(p)
        # keep walking; nothing pruned
    remapped = 0
    cat = load_json(args.catalog, None)
    if cat:
        mapping = {o: n for o, n in converted}
        for name, info in cat.get("sources", {}).items():
            spath = os.path.join(info["dir"], "_source.json")
            scat = load_json(spath, None)
            if not scat:
                continue
            dirty = False
            for e in scat["items"]:
                for fe in e.get("files") or []:
                    old = fe.get("file")
                    if old in mapping:
                        fe["file"] = mapping[old]
                        dirty = True
                        remapped += 1
            if dirty:
                save_json(spath, scat)
    log(f"normalize-library: {len(converted)} converted, "
        f"{len(failed)} left as-is, {remapped} catalog refs remapped")
    for o, n in converted[:10]:
        log(f"  {os.path.basename(o)} -> {os.path.basename(n)}")
    if failed:
        log(f"  unconverted examples: "
            + ", ".join(os.path.basename(f) for f in failed[:5]))


def cmd_launch(args):
    py = sys.executable
    script = os.path.abspath(__file__)
    logdir = os.path.dirname(args.catalog)
    logf = os.path.join(logdir, "ingest.log")
    cmd = [py, "-u", script,
           "--discover", "--download",
           "--out", args.out, "--catalog", args.catalog]
    if not args.hd_only:
        cmd.append("--include-non-hd")
    if args.only:
        cmd += ["--only", args.only]
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    import subprocess
    logh = open(logf, "ab", buffering=0)
    try:
        logh.write(f"\n=== run started {datetime.now().isoformat()} ===\n"
                   .encode())
        subprocess.Popen(cmd, stdout=logh, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL,
                         creationflags=0x00000008 | 0x00000200,
                         close_fds=False, env=env, cwd=logdir)
    finally:
        logh.close()
    bat = os.path.join(logdir, "run_ingest.bat")
    with open(bat, "w", encoding="utf-8") as fh:
        fh.write("@echo off\r\nrem manual re-run entry point\r\n"
                 f'"{py}" -u "{script}" --discover --download '
                 f'--out "{args.out}" --catalog "{args.catalog}" '
                 f'{"--hd-only " if args.hd_only else "--include-non-hd "}'
                 f'{("--only " + args.only + " ") if args.only else ""}'
                 f'>> "{logf}" 2>&1\r\n')
    log(f"detached pid launched\nlog: {logf}\nmanual rerun: {bat}")


def cmd_clone(args):
    master = load_json(args.catalog, {"v": VERSION, "sources": {}})
    src_name = args.clone_source
    info = master["sources"].get(src_name)
    sdir = None
    if info and os.path.isdir(info["dir"]):
        sdir = info["dir"]
    else:
        guess = os.path.join(args.out, src_name)
        if os.path.isdir(guess):
            sdir = guess
    scat = load_json(os.path.join(sdir or "", "_source.json"), None) \
        if sdir else None
    if not scat:
        log(f"clone fail: no catalog/source for '{src_name}'")
        return 1
    spec = json.loads(json.dumps(scat["spec"]))
    spec["name"] = args.as_name
    if args.set_path:
        spec["path"] = args.set_path
    ndir = os.path.join(args.out, args.as_name)
    os.makedirs(ndir, exist_ok=True)
    save_json(os.path.join(ndir, "_source.json"),
              {"name": args.as_name, "spec": spec, "items": []})
    master["sources"][args.as_name] = {
        "dir": ndir, "items": 0, "materialized": 0,
        "updated_at": datetime.now(timezone.utc).isoformat()}
    save_json(args.catalog, master)
    log(f"cloned {src_name} -> {args.as_name} "
        f"[{spec['adapter']}] path={spec.get('path')}")
    log(f"populate it with: --discover --only {args.as_name}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog=APP)
    p.add_argument("--out", default=r"D:\new")
    p.add_argument("--catalog",
                   default=os.path.join(r"D:\new", "_ingest_catalog.json"))
    p.add_argument("--discover", action="store_true")
    p.add_argument("--download", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--launch", action="store_true")
    p.add_argument("--audit-videos", action="store_true",
                   help="run Riley's offline video audit on --out")
    p.add_argument("--hd-only", action="store_true", default=True)
    p.add_argument("--include-non-hd", dest="hd_only",
                   action="store_false")
    p.add_argument("--no-female-filter", action="store_true")
    p.add_argument("--no-discover-extra", action="store_true")
    p.add_argument("--clone-source", default=None,
                   help="clone an existing source's config by name")
    p.add_argument("--as", dest="as_name", default=None,
                   help="name for the cloned source")
    p.add_argument("--set-path", default=None,
                   help="override the cloned source's path (e.g. a model page)")
    p.add_argument("--only", default=None)
    p.add_argument("--speed", type=float, default=1.0)
    # ---- v1.1 pulling / scanning --------------------------------------
    p.add_argument("--scan-web", default=None, metavar="URL[,URL...]",
                   help="enhanced web scan: BFS-crawl seed page(s), "
                        "harvest direct media links into a weblink source")
    p.add_argument("--from-file", default=None, metavar="LISTFILE",
                   help="pull from a text list of media/page URLs")
    p.add_argument("--scan-depth", type=int, default=2)
    p.add_argument("--scan-max-pages", type=int, default=40)
    p.add_argument("--scan-any-host", action="store_true",
                   help="allow the crawl to leave the seed host")
    p.add_argument("--scan-pattern", default=None,
                   help="regex a page URL must match to be crawled")
    p.add_argument("--scan-name", default=None,
                   help="source name for scan/list results")
    p.add_argument("--scan-report", default=None,
                   help="where to write webscan-report.json")
    p.add_argument("--no-auto-scan-pages", dest="auto_scan_pages",
                   action="store_false",
                   help="--from-file: don't mini-scan known-host pages")
    # ---- v1.1 auto-conversion -----------------------------------------
    p.add_argument("--auto-convert", dest="auto_convert",
                   action="store_true", default=True,
                   help="convert every pulled file to .jpg/.mp4 "
                        "(default: on)")
    p.add_argument("--no-auto-convert", dest="auto_convert",
                   action="store_false")
    p.add_argument("--normalize-library", action="store_true",
                   help="one-shot conversion pass over --out tree; "
                        "catalogs are remapped")
    p.add_argument("--ffmpeg", default=None,
                   help="path to ffmpeg binary or its folder")
    args = p.parse_args(argv)
    global FFMPEG_PATH
    if args.ffmpeg:
        FFMPEG_PATH = args.ffmpeg
        _FFMPEG_CACHE["path"] = False
    os.makedirs(args.out, exist_ok=True)
    ran = False
    if args.clone_source:
        sys.exit(cmd_clone(args))
    if args.scan_web:
        cmd_scan_web(args)
        ran = True
    if args.from_file:
        cmd_from_list(args)
        ran = True
    if args.discover:
        cmd_discover(args)
        ran = True
    if args.download:
        cmd_download(args)
        ran = True
    if args.normalize_library:
        cmd_normalize_library(args)
        ran = True
    if args.launch:
        cmd_launch(args)
        ran = True
    if args.audit_videos:
        import video_audit
        sys.exit(video_audit.main(["--root", args.out]))
    if not ran:
        p.print_help()


if __name__ == "__main__":
    main()

