"""ai_bridge - optional local AI video generation tier (ComfyUI).

Talks ONLY to a loopback ComfyUI API (default 127.0.0.1:8188). Nothing
leaves the machine; remote hosts are refused unless the operator sets
KINEMA_ALLOW_REMOTE_HOST=1 explicitly.

Flow: build workflow JSON -> submit -> poll history -> download
outputs into the studio workdir, where they become inputs for the mp4
production engine (produce.py).

The bundled text2video/img2video templates target common node packs;
exact node names depend on what the operator installed into their
local ComfyUI (see setup_kinema_stack.ps1 for the one-command stack).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8188"


def _base(base_url=None):
    base = base_url or os.environ.get("KINEMA_COMFY_URL") or DEFAULT_BASE
    host = urllib.parse.urlparse(base).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1") and \
            os.environ.get("KINEMA_ALLOW_REMOTE_HOST") != "1":
        raise RuntimeError(
            "refusing non-loopback AI host %r "
            "(set KINEMA_ALLOW_REMOTE_HOST=1 to override)" % host)
    return base.rstrip("/")


def status(base_url=None):
    """Server vitals or None when the local AI tier is down."""
    try:
        with urllib.request.urlopen(_base(base_url) + "/system_stats",
                                    timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError):
        return None


def submit(workflow, base_url=None, client="kinema"):
    """POST a workflow graph -> prompt_id."""
    body = json.dumps({"prompt": workflow, "client_id": client})\
        .encode("utf-8")
    req = urllib.request.Request(
        _base(base_url) + "/prompt", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["prompt_id"]


def poll(prompt_id, base_url=None, timeout=1800, interval=2.0):
    """Wait until the queued prompt finishes; returns its history."""
    deadline = time.time() + timeout
    url = "%s/history/%s" % (_base(base_url), prompt_id)
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                hist = json.loads(resp.read().decode("utf-8"))
            if prompt_id in hist:
                entry = hist[prompt_id]
                status_bit = entry.get("status", {}).get("completed")
                if status_bit or entry.get("outputs"):
                    return entry
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(interval)
    raise TimeoutError("AI render %s did not finish in %.0fs"
                       % (prompt_id, timeout))


def fetch_outputs(entry, dest_dir, base_url=None):
    """Download every produced file into dest_dir; returns local paths."""
    os.makedirs(dest_dir, exist_ok=True)
    saved = []
    for node_out in (entry.get("outputs") or {}).values():
        for key in ("images", "gifs", "videos"):
            for item in node_out.get(key) or []:
                name = item.get("filename")
                if not name:
                    continue
                qs = urllib.parse.urlencode({
                    "filename": name,
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output")})
                url = "%s/view?%s" % (_base(base_url), qs)
                dst = os.path.join(dest_dir, name.replace("/", "_"))
                with urllib.request.urlopen(url, timeout=300) as resp, \
                        open(dst, "wb") as fh:
                    fh.write(resp.read())
                saved.append(dst)
    return saved


def generate(workflow, dest_dir, base_url=None, timeout=1800):
    """One-call local generation: submit -> poll -> download."""
    pid = submit(workflow, base_url=base_url)
    entry = poll(pid, base_url=base_url, timeout=timeout)
    files = fetch_outputs(entry, dest_dir, base_url=base_url)
    return {"prompt_id": pid, "files": files}


# ------------------------------------------------------------- templates

def image2video_template(**_):
    """Skeleton img->vid graph mirroring ComfyUI's default SVD nodes.
    Operators adjust model names to whatever sits in models/checkpoints
    of their local install."""
    return {
        "2": {"class_type": "ImageOnlyCheckpointLoader",
              "inputs": {"ckpt_name": "svd_xt.safetensors"}},
        "3": {"class_type": "SVD_img2vid_Conditioning",
              "inputs": {"clip_vision": ["11", 0],
                         "init_image": ["10", 0],
                         "vae": ["2", 2],
                         "width": 1024, "height": 576,
                         "video_frames": 25, "motion_bucket_id": 127,
                         "fps": 8, "augmentation_level": 0.0}},
        "4": {"class_type": "VideoLinearCFGGuidance",
              "inputs": {"model": ["2", 0], "min_cfg": 1.0}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": 0, "steps": 20, "cfg": 2.5,
                         "sampler_name": "euler", "scheduler": "karras",
                         "denoise": 1.0,
                         "model": ["4", 0], "positive": ["3", 0],
                         "negative": ["3", 1], "latent_image": ["3", 2]}},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["2", 2]}},
        "7": {"class_type": "VideoCombine",
              "inputs": {"images": ["6", 0], "frame_rate": 8,
                         "loop_count": 0, "format": "h264-mp4",
                         "crf": 20, "pingpong": False,
                         "save_output": True}},
    }


def write_template(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",
                exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(image2video_template(), fh, indent=1)
    return path
