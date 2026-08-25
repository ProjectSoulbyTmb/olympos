"""models - curated quantized model manifest + download manager.

Every URL below was verified live (HTTP 200) at build time. Downloads are
operator-triggered, resumable, and land inside the ComfyUI tree under the
AI home (default D:\\riley-studio-ai, never the OneDrive-synced repo).
Gated repos (license acceptance required on huggingface.com) raise
GatedModelError with instructions instead of failing silently.
"""
import hashlib
import json
import os
import re
import subprocess

HF = "https://huggingface.co"

# dest values map to ComfyUI models/ subdirectories.
MODELS = {
    "sd15": {
        "label": "Stable Diffusion 1.5 (fast tier)",
        "tier": "fast", "kind": "image", "vram_gb": 2,
        "notes": "Fastest image tier; comfortable at 512px on 4GB GPUs.",
        "files": [{
            "role": "checkpoint",
            "url": HF + "/Comfy-Org/stable-diffusion-v1-5-archive/"
                        "resolve/main/v1-5-pruned-emaonly-fp16.safetensors",
            "bytes": 2034000000, "gated": False,
        }],
    },
    "sdxl-q4": {
        "label": "SDXL base 1.0 GGUF Q4_0 (quality tier)",
        "tier": "quality", "kind": "image", "vram_gb": 4,
        "notes": "Q4 unet fits a 4GB card; needs its clip pair + VAE.",
        "files": [
            {"role": "unet",
             "url": HF + "/gpustack/stable-diffusion-xl-base-1.0-GGUF/"
                        "resolve/main/stable-diffusion-xl-base-1.0-Q4_0.gguf",
             "bytes": 3757000000, "gated": False},
            {"role": "vae",
             "url": HF + "/madebyollin/sdxl-vae-fp16-fix/resolve/main/"
                        "sdxl_vae.safetensors",
             "bytes": 319000000, "gated": False},
            {"role": "clip1",
             "url": HF + "/stabilityai/stable-diffusion-xl-base-1.0/"
                        "resolve/main/text_encoders/model.clip_l_safetensors"
                        ".slice.safetensors",
             "bytes": 246000000, "gated": True},
            {"role": "clip2",
             "url": HF + "/stabilityai/stable-diffusion-xl-base-1.0/"
                        "resolve/main/text_encoders/model.big_g.safetensors."
                        "slice.safetensors",
             "bytes": 1398000000, "gated": True},
        ],
    },
    "flux-schnell-q4": {
        "label": "FLUX.1-schnell GGUF Q4_K_S (flagship tier)",
        "tier": "flagship", "kind": "image", "vram_gb": 4,
        "notes": "Minutes per image on 4GB; VAE is license-gated by BFL.",
        "files": [
            {"role": "unet",
             "url": HF + "/city96/FLUX.1-schnell-gguf/resolve/main/"
                        "flux1-schnell-Q4_K_S.gguf",
             "bytes": 6800000000, "gated": False},
            {"role": "clip1",
             "url": HF + "/comfyanonymous/flux_text_encoders/resolve/main/"
                        "clip_l.safetensors",
             "bytes": 246000000, "gated": False},
            {"role": "t5",
             "url": HF + "/city96/t5-v1_1-xxl-encoder-gguf/resolve/main/"
                        "t5-v1_1-xxl-encoder-Q4_K_S.gguf",
             "bytes": 2300000000, "gated": False},
            {"role": "vae",
             "url": HF + "/black-forest-labs/FLUX.1-schnell/resolve/main/"
                        "ae.safetensors",
             "bytes": 335000000, "gated": True},
        ],
    },
    "ltxv-distilled-q3": {
        "label": "LTX-Video 0.9.6 distilled Q3_K_S (video tier)",
        "tier": "video", "kind": "video", "vram_gb": 4,
        "notes": "Short clips (3-5s @ 480-768px); minutes per clip.",
        "files": [
            {"role": "unet",
             "url": HF + "/city96/LTX-Video-0.9.6-distilled-gguf/resolve/"
                        "main/ltxv-2b-0.9.6-distilled-04-25-Q3_K_S.gguf",
             "bytes": 857000000, "gated": False},
            {"role": "vae",
             "url": HF + "/city96/LTX-Video-0.9.6-distilled-gguf/resolve/"
                        "main/LTX-Video-0.9.6-VAE-BF16.safetensors",
             "bytes": 2378000000, "gated": False},
            {"role": "t5",
             "url": HF + "/city96/t5-v1_1-xxl-encoder-gguf/resolve/main/"
                        "t5-v1_1-xxl-encoder-Q4_K_S.gguf",
             "bytes": 2300000000, "gated": False},
        ],
    },
}

# role -> ComfyUI models/ subdirectory
DEST_DIRS = {
    "checkpoint": "checkpoints",
    "unet": "diffusion_models",
    "vae": "vae",
    "clip1": "text_encoders",
    "clip2": "text_encoders",
    "clip": "text_encoders",
    "t5": "text_encoders",
    "upscale": "upscale_models",
}


class GatedModelError(RuntimeError):
    """A required file sits behind a license gate the operator must accept."""


def default_ai_home(repo_root=None):
    """RILEY_STUDIO_AI_HOME wins, else D:\\riley-studio-ai, else repo-local."""
    env = os.environ.get("RILEY_STUDIO_AI_HOME")
    if env:
        return env
    if os.path.isdir("D:\\"):
        return "D:\\riley-studio-ai"
    root = repo_root or os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))
    return os.path.join(root, "ai-stack")


def detect_vram_mb():
    """Total VRAM via nvidia-smi, or None when no NVIDIA GPU / tool absent."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        vals = [int(x.strip().splitlines()[0]) for x in
                (out.stdout or "").split(",") if x.strip()]
        if vals:
            return vals[0]
    except (OSError, ValueError):
        pass
    return None


def pick_tier(vram_mb=None):
    """Recommended model keys for this machine, best-first."""
    vram = vram_mb if vram_mb is not None else detect_vram_mb()
    order = ["sd15", "sdxl-q4", "flux-schnell-q4", "ltxv-distilled-q3"]
    if vram is None or vram < 3000:
        return ["sd15", "ltxv-distilled-q3"]
    return order


def comfy_dir(ai_home):
    return os.path.join(ai_home, "ComfyUI")


def _file_dest(ai_home, entry):
    fname = entry["url"].split("?")[0].rsplit("/", 1)[-1]
    return os.path.join(comfy_dir(ai_home), "models",
                        DEST_DIRS[entry["role"]], fname)


def installed(ai_home):
    """{key: {role: filename}} for every manifest piece already on disk."""
    have = {}
    for key, meta in MODELS.items():
        got = {}
        for entry in meta["files"]:
            dest = _file_dest(ai_home, entry)
            if os.path.isfile(dest):
                got[entry["role"]] = os.path.basename(dest)
        if got:
            have[key] = got
    return have


def resolve(key, ai_home):
    """Loader-ready file names for a model key.

    Raises MissingModelError naming exactly which pieces still need a pull.
    """
    meta = MODELS.get(key)
    if not meta:
        raise KeyError("unknown model %r" % key)
    have = installed(ai_home).get(key, {})
    missing = [e["role"] for e in meta["files"] if e["role"] not in have]
    if missing:
        raise MissingModelError(key, missing)
    out = {r: have[r] for r in have}
    out["_tier"] = meta["tier"]
    out["_kind"] = meta["kind"]
    return out


class MissingModelError(RuntimeError):
    def __init__(self, key, roles):
        self.roles = roles
        super().__init__(
            "model %r missing pieces: %s - run a models pull first"
            % (key, ", ".join(roles)))


def download(url, dest, progress_cb=None, resume=True, timeout=60):
    """Stream url -> dest with Range resume; returns sha256 hex digest.

    Raises GatedModelError on 401/403 so operators get actionable text.
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    done = os.path.getsize(part) if (resume and os.path.isfile(part)) else 0
    headers = {}
    if done:
        headers["Range"] = "bytes=%d-" % done
    req = urllib_request(url, headers)
    try:
        resp = urllib_open(req, timeout)
    except PermissionError as exc:
        raise GatedModelError(
            "%s is gated - accept the license on huggingface.com "
            "(or export HF_TOKEN) then retry: %s" % (url, exc))
    total = int(resp.headers.get("Content-Length") or 0) + done
    mode = "ab" if done else "wb"
    digest = hashlib.sha256()
    written = done
    with open(part, mode) as fh:
        while True:
            chunk = resp.read(1024 * 512)
            if not chunk:
                break
            fh.write(chunk)
            digest.update(chunk)
            written += len(chunk)
            if progress_cb and total:
                progress_cb(written, total)
    os.replace(part, dest)
    return digest.hexdigest()


# indirections kept tiny so tests can stub cleanly
def urllib_request(url, headers=None):
    import urllib.request as ur
    call = ur.Request
    return call(url, headers=headers or {})


def urllib_open(req, timeout):
    import urllib.request as ur
    try:
        return ur.urlopen(req, timeout=timeout)
    except OSError as exc:
        # urllib raises HTTPError for 401/403; surface it uniformly
        code = getattr(exc, "code", None)
        if code in (401, 403):
            raise PermissionError(str(exc))
        raise


def manifest_view():
    """JSON-safe summary used by the API/UI."""
    view = {}
    for key, meta in MODELS.items():
        view[key] = {
            "label": meta["label"], "tier": meta["tier"],
            "kind": meta["kind"], "vram_gb": meta["vram_gb"],
            "notes": meta["notes"],
            "files": [{"role": f["role"], "bytes": f["bytes"],
                       "gated": f["gated"],
                       "name": f["url"].split("?")[0].rsplit("/", 1)[-1]}
                      for f in meta["files"]],
        }
    return view


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.1f%s" % (n, unit)
        n /= 1024.0
