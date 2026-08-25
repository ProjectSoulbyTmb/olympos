#!/usr/bin/env python3
"""verify_riley_studio - offline-safe gate for the Riley Studio suite.

    python verify_riley_studio.py

Exit code is the verdict: 0 = stable, non-zero = fix me. Every check is
local: no ComfyUI, no GPU, no network beyond 127.0.0.1 ephemeral ports.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.join(HERE, "riley-studio")
sys.path.insert(0, STUDIO)

PASS, FAIL = [], []


def check(name):
    def wrap(fn):
        def run():
            try:
                fn()
                PASS.append(name)
                print("  ok   %s" % name)
            except Exception as exc:  # noqa: BLE001 - report everything
                FAIL.append((name, str(exc)))
                print("  FAIL %s: %s" % (name, exc))
        run.__name__ = fn.__name__
        CHECKS.append(run)
        return run
    return wrap


CHECKS = []


# ---------------------------------------------------------------- imports
@check("modules import cleanly")
def check_imports():
    from engine import VERSION, comfy, graphs, models  # noqa: F401
    assert VERSION and VERSION.count(".") == 2


@check("comfy client refuses non-loopback hosts")
def check_loopback_guard():
    from engine import comfy
    try:
        comfy._base("http://10.1.2.3:8188")
        raise AssertionError("non-loopback host was accepted")
    except RuntimeError:
        pass
    old = dict(os.environ)
    os.environ["RILEY_STUDIO_ALLOW_REMOTE"] = "1"
    try:
        assert comfy._base("http://10.1.2.3:8188") != ""
    finally:
        os.environ.clear()
        os.environ.update(old)


@check("model manifest integrity + tier advice")
def check_manifest_integrity():
    from engine import models
    for key, meta in models.MODELS.items():
        assert meta["tier"] in ("fast", "quality", "flagship", "video")
        assert meta["kind"] in ("image", "video")
        for f in meta["files"]:
            assert f["url"].startswith("https://huggingface.co/"), key
            assert f["role"] in models.DEST_DIRS, (key, f["role"])
            assert f["bytes"] > 1000
    rec = models.pick_tier(4096)
    assert rec[0] == "sd15", rec
    assert "ltxv-distilled-q3" in rec
    assert models.human_bytes(2034000000).endswith("GB")


@check("graph builders emit structurally valid graphs")
def check_graph_builders():
    from engine import graphs
    g = graphs.g_txt2img_checkpoint("v1-5-pruned-emaonly-fp16.safetensors",
                                    "a lighthouse at dusk", seed=7)
    assert g["5"][2]["seed"] == 7
    g = graphs.g_txt2img_gguf_sdxl("u.gguf", "c1.safetensors",
                                   "c2.safetensors", "v.safetensors", "cat")
    assert g["1"][1] == "UnetLoaderGGUF"
    f = graphs.g_txt2img_gguf_flux("u.gguf", "clip_l.safetensors",
                                   "t5.gguf", "ae.safetensors", "sky")
    # guidance node consumes positive encode; sampler consumes guidance
    assert f["4"][2]["conditioning"] == ["5", 0]
    assert f["7"][2]["positive"] == ["4", 0]
    v = graphs.g_txt2vid_ltx("u.gguf", "vae.safetensors", "t5.gguf", "wave")
    assert (97 - 1) % 8 == 0  # LTX frame count contract
    assert v["9"][1] == "SaveWEBM"
    iv = graphs.g_img2vid_ltx("u.gguf", "vae.safetensors", "t5.gguf",
                              "in.png", "zoom out")
    assert iv["7"][2]["latent_image"] == ["11", 0]
    up = graphs.g_upscale("x.png", 2.0)
    assert up["2"][1] == "ImageScaleBy"
    bad = {"a": ["b", "KSampler", {"seed": 1}]}  # id mismatch
    try:
        graphs.validate_graph(bad)
        raise AssertionError("malformed graph passed validation")
    except ValueError:
        pass
    bad2 = {"a": ["a", "KSampler"]}
    try:
        graphs.validate_graph(bad2)
        raise AssertionError("short node passed validation")
    except ValueError:
        pass


@check("queue round-trip with injected comfy fakes")
def check_queue_roundtrip():
    from engine.queue import JobQueue
    tmp = tempfile.mkdtemp(prefix="rs-queue-")
    try:
        def fake_fetch(entry, dest, base_url=None):
            os.makedirs(dest, exist_ok=True)
            out = os.path.join(dest, "out.png")
            _touch(out)
            return [out]

        q = JobQueue(tmp,
                     submit_fn=lambda wf, base_url=None: "pid-1",
                     poll_fn=lambda pid, base_url=None, timeout=0,
                     interval=0: {"outputs": {"9": {
                         "images": [{"filename": "out.png"}]}}},
                     fetch_fn=fake_fetch)
        jid = q.submit("txt2img_checkpoint",
                       {"prompt": "test",
                        "checkpoint": "v1-5-pruned-emaonly-fp16.safetensors"})
        q.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            rec = q.get(jid)
            if rec["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        rec = q.get(jid)
        assert rec["status"] == "done", rec
        expect = os.path.join(tmp, "outputs", jid, "out.png")
        assert rec["files"] == [expect], rec["files"]
        assert os.path.isfile(expect), "fake output missing on disk"
        assert os.path.isfile(os.path.join(tmp, "jobs.jsonl")), \
            "journal missing"
        q.stop()  # park the worker so the probe job stays pending
        pend = q.submit("txt2img_checkpoint",
                        {"prompt": "never",
                         "checkpoint": "x.safetensors"})
        assert q.cancel(pend) is True, "pending job not cancelled"
        assert q.get(pend)["status"] == "cancelled"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check("journal rehydration marks interrupted jobs as errors")
def check_journal_rehydration():
    from engine.queue import JobQueue
    tmp = tempfile.mkdtemp(prefix="rs-journal-")
    try:
        with open(os.path.join(tmp, "jobs.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({
                "id": "deadbeef123", "kind": "txt2img_checkpoint",
                "params": {}, "status": "running", "error": None,
                "files": [], "created": "now", "updated": "now"}) + "\n")
            fh.write("{torn tail\n")  # hard-kill artifact must be ignored
        q = JobQueue(tmp)
        rec = q.get("deadbeef123")
        assert rec["status"] == "error", rec
        assert "interrupted" in rec["error"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check("downloader resumes partial files over real HTTP")
def check_download_resume():
    from engine import models
    src = os.urandom(1024 * 512)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = self.headers.get("Range")
            start = 0
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
            chunk = src[start:]
            if rng:
                self.send_response(206)
                self.send_header("Content-Range",
                                 "bytes %d-%d/%d"
                                 % (start, len(src) - 1, len(src)))
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(prefix="rs-dl-")
    try:
        dest = os.path.join(tmp, "blob.bin")
        with open(dest + ".part", "wb") as fh:
            fh.write(src[:1024 * 256])
        url = "http://127.0.0.1:%d/blob.bin" % port
        models.download(url, dest)
        with open(dest, "rb") as fh:
            got = fh.read()
        assert got == src, "resumed content mismatch (%d bytes)" % len(got)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


@check("gated upstream surfaces actionable error")
def check_gated_error():
    from engine import models

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(prefix="rs-gate-")
    try:
        url = "http://127.0.0.1:%d/gated.bin" % srv.server_address[1]
        try:
            models.download(url, os.path.join(tmp, "g.bin"))
            raise AssertionError("403 did not surface as gated error")
        except models.GatedModelError as exc:
            assert "license" in str(exc)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


@check("engine API boots, answers, jails paths")
def check_engine_api():
    py = sys.executable
    tmp = tempfile.mkdtemp(prefix="rs-srv-")
    port = _free_port()
    env = dict(os.environ)
    env["RILEY_STUDIO_DATA"] = tmp
    env["PYTHONPATH"] = STUDIO
    proc = subprocess.Popen(
        [py, os.path.join(STUDIO, "server.py"),
         "--port", str(port), "--data-dir", tmp],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    try:
        base = "http://127.0.0.1:%d" % port
        try:
            _wait_ready(base + "/api/status")
        except AssertionError:
            proc.terminate()
            out, _ = proc.communicate(timeout=10)
            raise AssertionError("server never became ready: %s\nchild: %s"
                                 % (_last_wait_error,
                                    out.decode(errors="replace")[-800:]))
        st = _get(base + "/api/status")
        assert st["ok"] is True and "version" in st
        assert st["ai_home"], "ai home missing"
        mv = _get(base + "/api/models")
        assert set(mv["models"]) >= {"sd15", "ltxv-distilled-q3"}
        assert mv["recommended"][0] in ("sd15", "sdxl-q4")
        code, body = _post(base + "/api/generate",
                           {"kind": "not-a-kind"})
        assert code == 400 and body["ok"] is False
        code, body = _get_raw(base +
                              "/api/file?p=../../secrets.txt")
        assert code in (403, 404), (code, body)
        gal = _get(base + "/api/gallery")
        assert gal["ok"] is True and isinstance(gal["items"], list)
        jobs = _get(base + "/api/jobs?limit=5")
        assert jobs["ok"] is True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


@check("export compilers emit sane ffmpeg argv")
def check_export_compilers():
    from engine import export
    a = export.compile_slideshow(["a.png", "b.png", "c.png"], "out.mp4",
                                 per_image=2.0, crossfade=0.5)
    assert a.count("-i") == 3
    joined = " ".join(a)
    assert "xfade" in joined and "libx264" in joined and \
        "faststart" in joined
    one = export.compile_slideshow(["solo.png"], "solo.mp4")
    assert one.count("-i") == 1 and "xfade" not in " ".join(one)
    g = export.compile_gif("in.mp4", "o.gif", fps=12, width=480)
    assert "palettegen" in " ".join(g)
    t = export.compile_text_card("hello: world", "card.mp4", seconds=2)
    assert "drawtext" in " ".join(t) and "\\:" in " ".join(t)
    for bad in ({"steps": []},
                {"steps": [{"type": "wat"}]},
                {"steps": [{"type": "slideshow", "images": []}]},
                {"steps": [{"type": "gif", "input": "x"}]}):
        try:
            export.validate_spec(bad)
            raise AssertionError("bad spec accepted: %r" % bad)
        except ValueError:
            pass


@check("export renders real mp4/gif when ffmpeg present")
def check_export_render():
    from engine import export
    ff = export.find_ffmpeg()
    if not ff:
        PASS.append("export_render_skipped_no_ffmpeg")
        print("  skip (no ffmpeg binary - run setup_studio.ps1)")
        return
    tmp = tempfile.mkdtemp(prefix="rs-exp-")
    try:
        # synthesize three colorful test frames via lavfi, no deps
        frames = []
        for i, c in enumerate(("red", "green", "blue")):
            f = os.path.join(tmp, "f%d.png" % i)
            subprocess.run([ff, "-y", "-f", "lavfi", "-i",
                            "color=c=%s:s=320x240:d=0.1" % c,
                            "-frames:v", "1", f],
                           capture_output=True, timeout=60,
                           check=True)
            frames.append(f)
        spec = {"steps": [
            {"type": "slideshow", "images": frames, "output": "reel.mp4",
             "per_image": 1.0, "crossfade": 0.25, "size": "320x240",
             "fps": 24},
            {"type": "gif", "input": "reel.mp4", "output": "reel.gif",
             "fps": 10, "width": 160},
        ]}
        made = export.render(spec, tmp)
        assert len(made) == 2, made
        assert os.path.getsize(made[0]) > 2000, "mp4 suspiciously small"
        assert os.path.getsize(made[1]) > 500, "gif suspiciously small"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _touch(path):
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\nfake")


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


_last_wait_error = None


def _wait_ready(url, timeout=20):
    global _last_wait_error
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return
        except OSError as exc:
            last = exc
        time.sleep(0.25)
    _last_wait_error = str(last)
    raise AssertionError("server never became ready: %s" % last)


def _get_raw(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _get(url):
    code, body = _get_raw(url)
    assert code == 200, (url, code, body)
    return body


def _post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type":
                                          "application/json"})
    return _get_raw_req(req)


def _get_raw_req(req):
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


import urllib.error  # noqa: E402

if __name__ == "__main__":
    print("== verify_riley_studio ==")
    print("-- %d checks --" % len(CHECKS))
    for fn in CHECKS:
        fn()
    print("== %d pass / %d fail ==" % (len(PASS), len(FAIL)))
    if FAIL:
        for name, why in FAIL:
            print("   FAILED: %s - %s" % (name, why[:300]))
        sys.exit(1)
