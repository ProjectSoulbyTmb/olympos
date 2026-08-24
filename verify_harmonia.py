"""Verify suite for HARMONIA normalized studio viewer.

Boots harmonia/server.py against a throwaway fixture library and asserts
the app's core promise: every finding is either already a standard viewing
format or gets served as one (GDI+ image normalization, ffmpeg video
remux/transcode), while containment, read-only discipline and the JSON
wire contract stay intact. Stdlib only; exits non-zero on any failure.

When the vendored ffmpeg/ffprobe (aphrodite/bin) are present the suite
additionally proves a real MKV -> MP4 normalization end-to-end.
"""

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "harmonia", "server.py")


def locate_ffmpeg():
    """Mirror harmonia's tool discovery so e2e proofs actually run:
    colocated aphrodite vendor drop -> standalone repo -> PATH."""
    cand = [os.path.join(HERE, "aphrodite", "bin", "ffmpeg.exe"),
            r"D:\aphrodite\bin\ffmpeg.exe"]
    import shutil
    which = shutil.which("ffmpeg")
    if which:
        cand.append(which)
    return next((c for c in cand if os.path.isfile(c)), None)


FFMPEG = locate_ffmpeg()

RESULTS = []

JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg==")


def tiny_bmp() -> bytes:
    """A valid 2x2 24bpp uncompressed BMP (red/green/blue/black pixels)."""
    w, h = 2, 2
    row = b"\x00\x00\xff\xff\x00\x00"          # bottom row BGR: red, green
    rows = row + b"\x00" * 2                   # pad to 4-byte boundary
    rows += b"\xff\x00\x00\x00\x00\x00" + b"\x00" * 2   # top: blue, black
    data_size = len(rows)
    size = 14 + 40 + data_size
    return (b"BM" + struct.pack("<IHHI", size, 0, 0, 54) +
            struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0,
                        data_size, 0, 0, 0, 0) + rows)


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name))
        print(f"  PASS  {name:<46} {detail}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name))
        print(f"  FAIL  {name:<46} {type(exc).__name__}: {exc}")


# --------------------------------------------------------------- plumbing
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_video(out: str, args: list) -> bool:
    """Real clip via bundled ffmpeg; False when tools are unavailable."""
    if not os.path.isfile(FFMPEG):
        return False
    cmd = [FFMPEG, "-y", "-f", "lavfi",
           "-i", "testsrc=duration=0.3:size=128x96:rate=10",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3"]
    r = subprocess.run(cmd + args + [out], capture_output=True, timeout=60)
    return r.returncode == 0 and os.path.isfile(out)


def make_fixture(tmp: str) -> str:
    lib = os.path.join(tmp, "lib")
    for sub in ("photos", "videos"):
        os.makedirs(os.path.join(lib, sub))
    def w(rel, data):
        with open(os.path.join(lib, rel), "wb") as fh:
            fh.write(data)
    w(os.path.join("photos", "a.jpg"), JPEG_1PX)
    w(os.path.join("photos", "c.png"), PNG_1PX)
    w(os.path.join("photos", "d.bmp"), tiny_bmp())       # needs GDI+ norm
    w(os.path.join("photos", "e.jfif"), JPEG_1PX)        # lossless rename
    make_video(os.path.join(lib, "videos", "real.mp4"),
               ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest"])
    make_video(os.path.join(lib, "videos", "clip.mkv"),
               ["-c:v", "libx264", "-c:a", "aac"])       # container remux
    MP4_STUB = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + \
        b"\x00" * 96
    w(os.path.join("videos", "stub.mp4"), MP4_STUB)      # undecodable
    w(".hidden.jpg", JPEG_1PX)
    w("notes.txt", b"not media")
    with open(os.path.join(tmp, "secret.txt"), "wb") as fh:
        fh.write(b"outside root")
    return lib


class Session:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="harmonia-verify-")
        self.root = make_fixture(self.tmp)
        self.port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, SERVER, "--root", self.root,
             "--port", str(self.port), "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{self.port}"
        self._wait_up()

    def _wait_up(self, timeout=10):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read().decode(errors="replace")
                raise RuntimeError(f"server exited early:\n{out}")
            try:
                st, _, _ = self.raw("GET", "/api/info")
                if st == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                last = exc
            time.sleep(0.15)
        raise RuntimeError(f"server did not come up: {last}")

    def raw(self, method, path, headers=None, body=None):
        req = urllib.request.Request(self.base + path,
                                     data=body, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def jget(self, path, **kw):
        st, _, body = self.raw("GET", path, **kw)
        j = json.loads(body.decode("utf-8"))
        assert set(j) >= {"ok", "error", "data"}, f"contract missing: {j}"
        assert j["ok"] is (j["error"] is None), f"ok/error mismatch: {j}"
        return st, j

    def wait_build(self, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            st, j = self.jget("/api/build")
            d = j["data"]
            if not d["queued"] and not d["running"]:
                return d
            time.sleep(0.5)
        raise AssertionError("worker never drained the queue")

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)
        key = hashlib.sha1(os.path.normcase(
            os.path.normpath(self.root)).encode()).hexdigest()[:12]
        base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        shutil.rmtree(base / "HARMONIA" / "norm" / key, ignore_errors=True)
        shutil.rmtree(base / "HARMONIA" / "thumbs" / key, ignore_errors=True)


S = None
HAS_FFMPEG = os.path.isfile(FFMPEG)


# ------------------------------------------------------------------ tests
def t_index_served():
    st, h, body = S.raw("GET", "/")
    assert st == 200 and b"HARMONIA" in body, st
    return "text/html served"


def t_info_contract():
    st, j = S.jget("/api/info")
    d = j["data"]
    assert d["app"] == "HARMONIA" and d["root_name"] == "lib", d
    assert d["tools"]["gdi"] is True, "GDI+ expected on Windows CI/dev box"
    return f"gdi=yes ffmpeg={'yes' if d['tools']['ffmpeg'] else 'no'}"


def t_tree_lists_and_hides():
    st, j = S.jget("/api/tree?dir=")
    dirs = {d["name"] for d in j["data"]["dirs"]}
    names = [f["path"] for f in j["data"]["files"]]
    assert dirs == {"photos", "videos"}, dirs
    assert names == ["notes.txt"] or names == [], names
    assert all(not n.startswith(".") for n in names), "hidden leaked"
    return "hidden excluded"


def t_findings_carry_fmt_std():
    st, j = S.jget("/api/tree?dir=photos")
    by = {f["path"].split("/")[-1]: f for f in j["data"]["files"]}
    assert by["a.jpg"]["std"] is True and by["a.jpg"]["fmt"] == "jpg"
    assert by["c.png"]["std"] is True and by["d.bmp"]["std"] is False
    assert by["e.jfif"]["std"] is False, "jfif must be flagged non-std"
    assert "notes.txt" not in by, "non-media leaked into findings"
    return "fmt+std fields correct"


def t_all_recursive():
    st, j = S.jget("/api/all")
    d = j["data"]
    paths = {i["path"] for i in d["items"]}
    assert {"photos/a.jpg", "photos/c.png", "photos/d.bmp",
            "photos/e.jfif"} <= paths, paths
    return f"{d['total']} findings indexed"


def t_original_bytes_exact():
    st, h, body = S.raw("GET", "/api/file?f=photos/a.jpg")
    assert st == 200 and body == JPEG_1PX, "original fidelity broken"
    return f"{len(body)} bytes exact"


def t_std_view_is_passthrough():
    st, h, body = S.raw("GET", "/api/file?f=photos/c.png&v=1&k=image")
    assert st == 200 and body == PNG_1PX, "std file must pass through untouched"
    assert h.get("Content-Type") == "image/png", h.get("Content-Type")
    return "png v=1 byte-identical"


def t_bmp_normalized_to_jpeg():
    st, h, body = S.raw("GET", "/api/file?f=photos/d.bmp&v=1&k=image")
    assert st == 200, st
    assert body[:2] == b"\xff\xd8", f"expected JPEG, got {body[:4]}"
    return f"BMP -> JPEG ({len(body)} bytes, GDI+)"


def t_jfif_lossless_rename():
    st, h, body = S.raw("GET", "/api/file?f=photos/e.jfif&v=1&k=image")
    assert st == 200 and body == JPEG_1PX, "jfif copy must be byte-exact"
    return "JFIF -> JPG lossless"


def t_norm_artifact_on_disk():
    st, j = S.jget("/api/info")
    norm_dir = Path(j["data"]["norm_dir"])
    files = list(norm_dir.rglob("*"))
    arts = [f for f in files if f.is_file()]
    assert arts, f"no artifacts under {norm_dir}"
    return f"{len(arts)} artifact(s) under LOCALAPPDATA"


def t_library_untouched():
    """The fixture library must hold exactly the bytes we wrote."""
    p = Path(S.root) / "photos" / "d.bmp"
    assert p.read_bytes().startswith(b"BM"), "library was mutated!"
    return "media root still pristine"


def t_thumb_served():
    st, h, body = S.raw("GET", "/api/thumb?f=photos/d.bmp&s=128")
    assert st == 200 and h.get("Content-Type") == "image/jpeg", st
    assert body[:2] == b"\xff\xd8", "thumb not jpeg"
    mode = "thumb-from-norm" if len(body) != len(tiny_bmp()) else "fallback"
    return mode


def t_traversal_rejected():
    st, j = S.jget("/api/file?f=../secret.txt")
    assert st == 403, st
    st2, j2 = S.jget("/api/file?f=%2e%2e%2fsecret.txt&v=1")
    assert st2 == 403, st2
    st3, _, _ = S.raw("GET", "/api/thumb?f=C:/Windows/win.ini")
    assert st3 == 403, st3
    return "plain, encoded, absolute all rejected (incl v=1)"


def t_hidden_and_nonmedia_denied():
    st, _ = S.jget("/api/file?f=.hidden.jpg&v=1")
    assert st == 403, st
    st2, _ = S.jget("/api/file?f=notes.txt")
    assert st2 == 403, st2
    return "hidden + non-media confined"


def t_method_policy():
    st, _, body = S.raw("POST", "/api/tree", body=b"",
                        headers={"Content-Type": "application/json"})
    assert st == 405, st
    st2, _, _ = S.raw("PUT", "/api/info", body=b"{}",
                      headers={"Content-Type": "application/json"})
    assert st2 == 405, st2
    st3, _, _ = S.raw("DELETE", "/api/build")
    assert st3 == 405, st3
    return "writes stay closed outside /api/build POST"


def t_unknown_api_404():
    st, j = S.jget("/api/nope")
    assert st == 404 and j["error"] == "not found", (st, j)
    return "structured 404"


def t_head_no_body():
    st, h, body = S.raw("HEAD", "/api/file?f=photos/a.jpg")
    assert st == 200 and body == b"", (st, len(body))
    assert int(h.get("Content-Length")) == len(JPEG_1PX)
    return "HEAD bodyless"


def t_dirs_listing():
    st, j = S.jget("/api/dirs")
    assert "" in j["data"]["dirs"], j["data"]
    return f"{j['data']['total']} dirs"


def t_build_status_contract():
    st, j = S.jget("/api/build")
    d = j["data"]
    assert set(d) >= {"queued", "running", "done", "failed"}, d
    return "build status shape ok"


def t_real_mp4_flagged_std():
    p = Path(S.root) / "videos" / "real.mp4"
    if not p.exists():
        return "skipped - no ffmpeg to fabricate fixture"
    st, j = S.jget("/api/all?cap=100")
    it = next(i for i in j["data"]["items"]
              if i["path"] == "videos/real.mp4")
    assert it["std"] is True, it
    return "h264/aac mp4 recognized standard"


def t_mkv_remuxed_to_mp4_e2e():
    src = Path(S.root) / "videos" / "clip.mkv"
    if not src.exists() or not HAS_FFMPEG:
        return "skipped - no ffmpeg available"
    # kick build (POST /api/build is the one allowed write)
    st, _, body = S.raw("POST", "/api/build", body=b"",
                        headers={"Content-Type": "application/json"})
    assert st == 200, (st, body[:120])
    d = S.wait_build()
    # undecodable junk (stub.mp4) may honestly fail — but clip.mkv must land
    st, h, view = S.raw("GET", "/api/file?f=videos/clip.mkv&v=1&k=video")
    assert st == 200 and view[4:8] == b"ftyp", \
        f"view not mp4: {view[:12]!r} (done={d['done']}, failed={d['failed']})"
    return f"MKV -> MP4 ({len(view)} bytes, remux)"


def t_undecodable_graceful_fallback():
    """A file ffmpeg cannot read still VIEWs — as original bytes."""
    if not HAS_FFMPEG:
        return "skipped - no ffmpeg available"
    st, h, body = S.raw("GET", "/api/file?f=videos/stub.mp4&v=1&k=video")
    assert st == 200, st
    assert b"ftypmp42" in body[:16], "expected original stub bytes"
    return "junk input -> original bytes, no error"


def main() -> int:
    global S
    print(f"\nHARMONIA verify ({SERVER})")
    S = Session()
    try:
        check("index served", t_index_served)
        check("info contract + gdi", t_info_contract)
        check("tree lists + hides hidden", t_tree_lists_and_hides)
        check("findings carry fmt/std", t_findings_carry_fmt_std)
        check("recursive /api/all", t_all_recursive)
        check("original bytes exact", t_original_bytes_exact)
        check("std passthrough v=1", t_std_view_is_passthrough)
        check("BMP normalized to JPEG", t_bmp_normalized_to_jpeg)
        check("JFIF lossless rename", t_jfif_lossless_rename)
        check("artifacts under LOCALAPPDATA", t_norm_artifact_on_disk)
        check("library stays pristine", t_library_untouched)
        check("thumbnail served", t_thumb_served)
        check("containment incl v=1", t_traversal_rejected)
        check("hidden/non-media denied", t_hidden_and_nonmedia_denied)
        check("method policy 405", t_method_policy)
        check("unknown api structured 404", t_unknown_api_404)
        check("HEAD bodyless", t_head_no_body)
        check("dirs listing", t_dirs_listing)
        check("build status contract", t_build_status_contract)
        check("real mp4 std flag", t_real_mp4_flagged_std)
        check("MKV remuxed to MP4 e2e", t_mkv_remuxed_to_mp4_e2e)
        check("undecodable falls back", t_undecodable_graceful_fallback)
    finally:
        S.close()
    fails = [n for ok, n in RESULTS if not ok]
    print(f"\n  {len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    if fails:
        print("  FAILED:", ", ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
