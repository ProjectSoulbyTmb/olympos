"""Verify suite for APHRODITE standalone media viewer.

Boots aphrodite/server.py against a throwaway fixture library and asserts
the guarantees that matter: one-root containment, read-only methods,
range streaming, JSON error contract, and listing correctness.
Stdlib only. Exits non-zero on any failure.
"""

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "aphrodite", "server.py")

RESULTS = []

JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg==")
MP4_STUB = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 96


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name))
        print(f"  PASS  {name:<44} {detail}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name))
        print(f"  FAIL  {name:<44} {type(exc).__name__}: {exc}")


# --------------------------------------------------------------- plumbing
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_fixture(tmp: str) -> str:
    lib = os.path.join(tmp, "lib")
    for sub in ("photos", "videos", os.path.join("nested", "deep")):
        os.makedirs(os.path.join(lib, sub))
    def w(rel, data):
        p = os.path.join(lib, rel)
        with open(p, "wb") as fh:
            fh.write(data)
    w(os.path.join("photos", "a.jpg"), JPEG_1PX)
    w(os.path.join("videos", "b.mp4"), MP4_STUB)
    w(os.path.join("nested", "c.png"), PNG_1PX)
    w(os.path.join("nested", "notes.txt"), b"not media")   # non-media file
    w(".hidden.jpg", JPEG_1PX)                              # hidden file
    with open(os.path.join(tmp, "secret.txt"), "wb") as fh:
        fh.write(b"outside root")                           # traversal target
    return lib


class Session:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="aphrodite-verify-")
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
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def jget(self, path, **kw):
        """GET and enforce the wire contract shape {ok,error,data}."""
        st, hdrs, body = self.raw("GET", path, **kw)
        j = json.loads(body.decode("utf-8"))
        assert set(j) >= {"ok", "error", "data"}, f"contract missing fields: {j}"
        assert j["ok"] is (j["error"] is None), f"ok/error mismatch: {j}"
        return st, j

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        # scrub APHRODITE app-state created during this run (cache + favorites)
        key = hashlib.sha1(os.path.normcase(
            os.path.normpath(self.root)).encode()).hexdigest()[:12]
        base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        shutil.rmtree(base / "APHRODITE" / "thumbs" / key, ignore_errors=True)
        try:
            (base / "APHRODITE" / "state" /
             f"favorites-{key}.json").unlink()
        except OSError:
            pass
        try:
            (base / "APHRODITE" / "state" /
             f"state-{key}.json").unlink()
        except OSError:
            pass


S = None  # session under test


# ------------------------------------------------------------------ tests
def t_index_served():
    st, h, body = S.raw("GET", "/")
    assert st == 200, st
    assert b"APHRODITE" in body
    return "text/html served"


def t_info_contract():
    st, j = S.jget("/api/info")
    assert st == 200 and j["error"] is None
    d = j["data"]
    assert d["app"] == "APHRODITE" and d["root_name"] == "lib"
    return f"root={d['root_name']}"


def t_tree_lists_and_hides():
    st, j = S.jget("/api/tree?dir=")
    assert st == 200
    dirs = {d["name"] for d in j["data"]["dirs"]}
    files = [f["name"] for f in j["data"]["files"]]
    assert dirs == {"photos", "nested", "videos"}, dirs
    assert files == [], files          # .hidden.jpg must NOT be listed
    return "hidden excluded"


def t_tree_subfolder_kinds():
    st, j = S.jget("/api/tree?dir=nested")
    files = {f["name"]: f["kind"] for f in j["data"]["files"]}
    assert files.get("c.png") == "image", files
    assert "notes.txt" not in files, files     # non-media filtered
    return "kind=image, txt filtered"


def t_file_bytes_exact():
    st, h, body = S.raw("GET", "/api/file?f=photos/a.jpg")
    assert st == 200, st
    assert body == JPEG_1PX, "byte mismatch"
    assert h.get("Content-Type") == "image/jpeg", h.get("Content-Type")
    return f"{len(body)} bytes exact"


def t_range_206_partial():
    n = len(JPEG_1PX)
    st, h, body = S.raw("GET", "/api/file?f=photos/a.jpg",
                        headers={"Range": "bytes=0-9"})
    assert st == 206, st
    assert body == JPEG_1PX[:10]
    assert h.get("Content-Range") == f"bytes 0-9/{n}", h.get("Content-Range")
    return "bytes=0-9 honored"


def t_range_suffix():
    n = len(JPEG_1PX)
    st, h, body = S.raw("GET", "/api/file?f=photos/a.jpg",
                        headers={"Range": f"bytes=-6"})
    assert st == 206 and body == JPEG_1PX[-6:]
    assert h.get("Content-Range") == f"bytes {n-6}-{n-1}/{n}"
    return "suffix range honored"


def t_range_unsatiable_416():
    st, _, body = S.raw("GET", "/api/file?f=photos/a.jpg",
                        headers={"Range": "bytes=999999-"})
    assert st == 416, st
    return "416 on out-of-bounds range"


def t_traversal_plain():
    st, j = S.jget("/api/file?f=../secret.txt")
    assert st == 403 and "error" in j, (st, j)
    return j["error"]


def t_traversal_percent_encoded():
    st, j = S.jget("/api/file?f=%2e%2e%2fsecret.txt")
    assert st == 403, st
    return "encoded .. rejected"


def t_absolute_path_rejected():
    st, j = S.jget("/api/file?f=C:/Windows/win.ini")
    assert st == 403, st
    return "drive-letter rejected"


def t_hidden_direct_access_denied():
    st, j = S.jget("/api/file?f=.hidden.jpg")
    assert st == 403, st
    return j["error"]


def t_nonmedia_rejected():
    st, j = S.jget("/api/file?f=nested/notes.txt")
    assert st == 403, st
    return j["error"]


def t_post_method_405():
    st, _, body = S.raw("POST", "/api/info", body=b"{}",
                        headers={"Content-Type": "application/json"})
    j = json.loads(body.decode())
    assert st == 405 and j["error"], (st, j)
    return "read-only enforced"


def t_unknown_api_404_json():
    st, j = S.jget("/api/nope")
    assert st == 404 and j["error"] == "not found", (st, j)
    return "structured 404"


def t_all_recursive():
    st, j = S.jget("/api/all")
    d = j["data"]
    paths = {i["path"] for i in d["items"]}
    assert paths == {"photos/a.jpg", "videos/b.mp4", "nested/c.png"}, paths
    assert d["total"] == 3 and d["truncated"] is False
    return "3 media, none hidden"


def t_head_request_no_body():
    st, h, body = S.raw("HEAD", "/api/file?f=videos/b.mp4")
    assert st == 200 and body == b"", (st, len(body))
    assert int(h.get("Content-Length")) == len(MP4_STUB)
    return "HEAD bodyless, length correct"


def t_deep_subdir_served():
    st, _, _ = S.raw("GET", "/api/tree?dir=nested/deep")
    assert st == 200, st
    return "nested traversal ok"


# ---- P2: thumbnails / meta / favorites -----------------------------------
def t_thumb_served_jpeg():
    st, h, body = S.raw("GET", "/api/thumb?f=photos/a.jpg&s=128")
    assert st == 200, st
    assert h.get("Content-Type") == "image/jpeg", h.get("Content-Type")
    assert body[:2] == b"\xff\xd8", "payload not a JPEG"
    mode = "gdi-thumb" if len(body) != len(JPEG_1PX) else "fallback-original"
    return mode


def t_thumb_traversal_403():
    st, j = S.jget("/api/thumb?f=../secret.txt")
    assert st == 403, st
    return "thumb endpoint confined"


def t_thumb_hidden_403():
    st, j = S.jget("/api/thumb?f=.hidden.jpg")
    assert st == 403, st
    return "hidden denied for thumbs"


def t_meta_png_empty_ok():
    st, j = S.jget("/api/meta?f=nested/c.png")
    assert st == 200 and isinstance(j["data"], dict), (st, j)
    return "png -> {} (no exif), contract intact"


def t_meta_jpeg_parses():
    st, j = S.jget("/api/meta?f=photos/a.jpg")
    assert st == 200 and isinstance(j["data"], dict), (st, j)
    return "stub jpeg parsed gracefully"


def t_fav_roundtrip():
    st, j = S.jget("/api/fav")
    assert j["data"]["items"] == [], "favorites not empty at start"
    add = urllib.request.Request(
        S.base + "/api/fav?f=photos%2Fa.jpg", data=b"", method="POST")
    with urllib.request.urlopen(add, timeout=8) as r:
        aj = json.loads(r.read().decode())
    assert aj["ok"] is True and aj["error"] is None, aj
    st, j = S.jget("/api/fav")
    items = j["data"]["items"]
    assert [i["path"] for i in items] == ["photos/a.jpg"], items
    assert items[0]["kind"] == "image" and items[0]["size"] == len(JPEG_1PX)
    dele = urllib.request.Request(S.base + "/api/fav?f=photos%2Fa.jpg",
                                  data=b"", method="DELETE")
    with urllib.request.urlopen(dele, timeout=8) as r:
        dj = json.loads(r.read().decode())
    assert dj["ok"] is True and dj["data"]["removed"] is True, dj
    st, j = S.jget("/api/fav")
    assert j["data"]["items"] == [], "favorite not removed"
    return "add/list/remove clean"


def t_fav_add_traversal_403():
    st, _, body = S.raw("POST", "/api/fav?f=..%2fsecret.txt", body=b"",
                        headers={"Content-Type": "application/json"})
    assert st == 403, (st, body[:80])
    return "favorites confined too"


def t_post_other_endpoints_still_405():
    st, _, body = S.raw("POST", "/api/tree", body=b"",
                        headers={"Content-Type": "application/json"})
    j = json.loads(body.decode())
    assert st == 405 and j["error"], (st, j)
    return "write surface stays closed"


# ------------------------------------------------------------ muse layer
def _post(path):
    st, _, body = S.raw("POST", path, body=b"",
                        headers={"Content-Type": "application/json"})
    j = json.loads(body.decode("utf-8"))
    assert st == 200 and j["ok"] is True, (st, j)
    return j["data"]


def _delete(path):
    st, _, body = S.raw("DELETE", path, body=b"")
    j = json.loads(body.decode("utf-8"))
    assert st == 200 and j["ok"] is True, (st, j)
    return j["data"]


def t_rate_roundtrip():
    def post(v):
        return _post(f"/api/rate?f=photos%2Fa.jpg&v={v}")
    assert post(4)["value"] == 4
    st, j = S.jget("/api/state")
    assert j["data"]["ratings"].get("photos/a.jpg") == 4
    post(0)
    st, j = S.jget("/api/state")
    assert "photos/a.jpg" not in j["data"]["ratings"], "not cleared"
    return "set/reflect/clear clean"


def t_rate_rejects_out_of_range():
    st, _, body = S.raw("POST", "/api/rate?f=photos%2Fa.jpg&v=9", body=b"")
    assert st == 400, (st, body[:80])
    return "v=9 -> 400"


def t_rate_traversal_403():
    st, _, body = S.raw("POST", "/api/rate?f=..%2fsecret.txt&v=3", body=b"")
    assert st == 403, (st, body[:80])
    return "ratings confined too"


def t_tags_roundtrip_and_index():
    _post("/api/tag?f=photos%2Fa.jpg&t=muse")
    st, j = S.jget("/api/tags-index")
    assert j["data"]["index"].get("muse") == ["photos/a.jpg"]
    _delete("/api/tag?f=photos%2Fa.jpg&t=muse")
    st, j = S.jget("/api/tags-index")
    assert "muse" not in j["data"]["index"]
    return "tag add/index/remove clean"


def t_board_lifecycle():
    import urllib.parse as up
    d = _post("/api/boards?action=create&name=Muse")
    bid = d["id"]
    _post(f"/api/boards?action=add&b={bid}&f={up.quote('photos/a.jpg')}")
    st, j = S.jget(f"/api/boards?b={bid}")
    assert [i["path"] for i in j["data"]["items"]] == ["photos/a.jpg"]
    _post(f"/api/boards?action=remove&b={bid}&f={up.quote('photos/a.jpg')}")
    st, j = S.jget(f"/api/boards?b={bid}")
    assert j["data"]["items"] == [] and j["data"]["pruned"] == 0
    _delete(f"/api/boards?action=delete&b={bid}")
    st, j = S.jget(f"/api/boards?b={bid}")
    assert st == 404 and j["ok"] is False
    return "create/add/list/remove/delete clean"


def t_board_item_traversal_403():
    bid = _post("/api/boards?action=create&name=T")["id"]
    st, _, body = S.raw(
        "POST", f"/api/boards?action=add&b={bid}&f=..%2fsecret.txt",
        body=b"")
    assert st == 403, (st, body[:80])
    _delete(f"/api/boards?action=delete&b={bid}")
    return "board items confined too"


def t_board_export_html():
    import urllib.parse as up
    b = _post("/api/boards?action=create&name=Sheet")
    _post(f"/api/boards?action=add&b={b['id']}&f={up.quote('photos/a.jpg')}")
    st, hdrs, body = S.raw("GET", f"/api/board/export?b={b['id']}")
    text = body.decode("utf-8", errors="replace")
    assert st == 200 and "text/html" in hdrs.get("Content-Type", "")
    assert "Sheet" in text and "/api/thumb?f=" in text
    _delete(f"/api/boards?action=delete&b={b['id']}")
    return "contact sheet renders"


def t_smart_save_eval_delete():
    _post("/api/rate?f=photos%2Fa.jpg&v=5")
    a = _post("/api/smart?action=save&name=Fives&minrating=5")
    st, j = S.jget(f"/api/smart?a={a['id']}")
    assert "photos/a.jpg" in [i["path"] for i in j["data"]["items"]]
    _delete(f"/api/smart?a={a['id']}")
    st, j = S.jget(f"/api/smart?a={a['id']}")
    assert st == 404
    _post("/api/rate?f=photos%2Fa.jpg&v=0")
    return "save/eval/delete clean"


def t_smart_unknown_album_404():
    st, _, body = S.raw("GET", "/api/smart?a=zzzz")
    j = json.loads(body.decode())
    assert st == 404 and j["ok"] is False
    return "unknown album structured 404"


def t_new_write_methods_stay_closed():
    st, _, _ = S.raw("PUT", "/api/rate?v=1")
    assert st == 405
    st, _, body = S.raw("GET", "/api/boards/items")
    j = json.loads(body.decode())
    assert set(j) >= {"ok", "error", "data"}
    return "method policy intact on new surface"


def main() -> int:
    global S
    print(f"\nAPHRODITE verify ({SERVER})")
    S = Session()
    try:
        check("index served", t_index_served)
        check("info contract ok/error/data", t_info_contract)
        check("tree lists + hides hidden", t_tree_lists_and_hides)
        check("tree kinds + non-media filter", t_tree_subfolder_kinds)
        check("file bytes exact", t_file_bytes_exact)
        check("range 206 partial", t_range_206_partial)
        check("range suffix -6", t_range_suffix)
        check("range unsatiable -> 416", t_range_unsatiable_416)
        check("traversal ../ rejected", t_traversal_plain)
        check("traversal %2e%2e rejected", t_traversal_percent_encoded)
        check("absolute drive path rejected", t_absolute_path_rejected)
        check("hidden direct access denied", t_hidden_direct_access_denied)
        check("non-media file denied", t_nonmedia_rejected)
        check("POST -> 405 read-only", t_post_method_405)
        check("unknown api -> structured 404", t_unknown_api_404_json)
        check("recursive /api/all", t_all_recursive)
        check("HEAD no body", t_head_request_no_body)
        check("deep subdirectory served", t_deep_subdir_served)
        check("thumbnail served as JPEG", t_thumb_served_jpeg)
        check("thumb traversal rejected", t_thumb_traversal_403)
        check("thumb hidden rejected", t_thumb_hidden_403)
        check("meta png -> {} contract", t_meta_png_empty_ok)
        check("meta jpeg parses", t_meta_jpeg_parses)
        check("favorites round-trip", t_fav_roundtrip)
        check("fav add traversal rejected", t_fav_add_traversal_403)
        check("other POSTs stay 405", t_post_other_endpoints_still_405)
        check("rating round-trip", t_rate_roundtrip)
        check("rating v=9 -> 400", t_rate_rejects_out_of_range)
        check("rating traversal rejected", t_rate_traversal_403)
        check("tags round-trip + index", t_tags_roundtrip_and_index)
        check("board lifecycle", t_board_lifecycle)
        check("board items confined", t_board_item_traversal_403)
        check("board contact-sheet export", t_board_export_html)
        check("smart album save/eval/delete", t_smart_save_eval_delete)
        check("unknown album structured 404", t_smart_unknown_album_404)
        check("new surface method policy", t_new_write_methods_stay_closed)
    finally:
        S.close()
    fails = [n for ok, n in RESULTS if not ok]
    print(f"\n  {len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    if fails:
        print("  FAILED:", ", ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
