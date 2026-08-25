"""comfy - loopback-only client for a local ComfyUI instance.

Mirrors the kinema ai_bridge contract: remote hosts are refused unless
the operator explicitly sets RILEY_STUDIO_ALLOW_REMOTE=1. Flow is always
submit workflow graph -> poll history -> fetch output files.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_BASE = "http://127.0.0.1:8188"
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _base(base_url=None):
    base = base_url or os.environ.get("RILEY_STUDIO_COMFY_URL") or DEFAULT_BASE
    host = urllib.parse.urlparse(base).hostname or ""
    if host not in _LOOPBACK and \
            os.environ.get("RILEY_STUDIO_ALLOW_REMOTE") != "1":
        raise RuntimeError(
            "refusing non-loopback AI host %r "
            "(set RILEY_STUDIO_ALLOW_REMOTE=1 to override)" % host)
    return base.rstrip("/")


def status(base_url=None):
    """Server vitals, or None when the local AI tier is down."""
    try:
        with urllib.request.urlopen(_base(base_url) + "/system_stats",
                                    timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def object_info(base_url=None):
    """Node catalog of the running instance, or None when unreachable."""
    try:
        with urllib.request.urlopen(_base(base_url) + "/object_info",
                                    timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def upload_image(path, base_url=None, field="image"):
    """Upload a local file -> the name ComfyUI knows it by."""
    fname = os.path.basename(path)
    boundary = "----rileystudio" + uuid.uuid4().hex
    with open(path, "rb") as fh:
        payload = fh.read()
    parts = [
        ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; "
         "filename=\"%s\"\r\nContent-Type: application/octet-stream"
         "\r\n\r\n" % (boundary, field, fname)).encode("utf-8"),
        payload,
        ("\r\n--%s--\r\n" % boundary).encode("utf-8"),
    ]
    req = urllib.request.Request(
        _base(base_url) + "/upload/image",
        data=b"".join(parts),
        headers={"Content-Type":
                 "multipart/form-data; boundary=%s" % boundary})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))["name"]


def submit(workflow, base_url=None, client="riley-studio"):
    """Queue a workflow graph -> prompt_id."""
    body = json.dumps({"prompt": workflow,
                       "client_id": client}).encode("utf-8")
    req = urllib.request.Request(
        _base(base_url) + "/prompt", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["prompt_id"]


def poll(prompt_id, base_url=None, timeout=3600, interval=2.0):
    """Block until the queued prompt finishes; returns its history entry."""
    deadline = time.time() + timeout
    url = "%s/history/%s" % (_base(base_url), prompt_id)
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                hist = json.loads(resp.read().decode("utf-8"))
            if prompt_id in hist:
                entry = hist[prompt_id]
                if entry.get("status", {}).get("completed") or \
                        entry.get("outputs"):
                    return entry
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(interval)
    raise TimeoutError("AI render %s did not finish in %.0fs"
                       % (prompt_id, timeout))


def fetch_outputs(entry, dest_dir, base_url=None):
    """Download every produced file into dest_dir -> local paths."""
    import shutil
    os.makedirs(dest_dir, exist_ok=True)
    saved = []
    for _, outs in (entry.get("outputs") or {}).items():
        for key in ("images", "gifs", "videos"):
            for item in outs.get(key) or []:
                sub = item.get("subfolder", "")
                name = item.get("filename")
                if not name:
                    continue
                url = "%s/view?%s" % (_base(base_url), urllib.parse.urlencode(
                    {"filename": name, "subfolder": sub,
                     "type": item.get("type", "output")}))
                dest = os.path.join(dest_dir, name)
                with urllib.request.urlopen(url, timeout=300) as resp, \
                        open(dest, "wb") as fh:
                    shutil.copyfileobj(resp, fh)
                saved.append(dest)
    return saved
