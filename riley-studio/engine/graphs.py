"""graphs - ComfyUI workflow builders for every generation kind.

Each builder returns a plain {node_id: [id, class, inputs]} graph ready
for POST /prompt. Node classes are stock ComfyUI unless noted:
CheckpointLoaderGGUF / UnetLoaderGGUF come from the ComfyUI-GGUF pack the
setup script installs. validate_graph() is the offline contract check.
"""
import json


def validate_graph(graph):
    """Structural contract: unique ids, [id, class, dict] shape everywhere."""
    if not isinstance(graph, dict) or not graph:
        raise ValueError("graph must be a non-empty dict")
    seen = set()
    for nid, node in graph.items():
        if not (isinstance(node, list) and len(node) == 3):
            raise ValueError("node %r malformed (want [id, class, inputs])"
                             % nid)
        cid, cls, inputs = node
        if cid != nid:
            raise ValueError("node id mismatch %r != %r" % (cid, nid))
        if not isinstance(cls, str) or not cls:
            raise ValueError("node %r has bad class %r" % (nid, cls))
        if not isinstance(inputs, dict):
            raise ValueError("node %r inputs must be a dict" % nid)
        if cid in seen:
            raise ValueError("duplicate node id %r" % cid)
        seen.add(cid)
    return graph


# ---------------------------------------------------------------- images

def g_txt2img_checkpoint(checkpoint, prompt, negative="", width=512,
                         height=512, steps=20, cfg=7.0, seed=0,
                         sampler="euler", scheduler="normal"):
    """Stock single-file checkpoint path (SD1.5 fast tier)."""
    g = {
        "1": ["1", "CheckpointLoaderSimple", {"ckpt_name": checkpoint}],
        "2": ["2", "CLIPTextEncode", {"text": prompt, "clip": ["1", 1]}],
        "3": ["3", "CLIPTextEncode", {"text": negative, "clip": ["1", 1]}],
        "4": ["4", "EmptyLatentImage",
              {"width": width, "height": height, "batch_size": 1}],
        "5": ["5", "KSampler",
              {"seed": seed, "steps": steps, "cfg": cfg,
               "sampler_name": sampler, "scheduler": scheduler,
               "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0],
               "negative": ["3", 0], "latent_image": ["4", 0]}],
        "6": ["6", "VAEDecode", {"samples": ["5", 0], "vae": ["1", 2]}],
        "7": ["7", "SaveImage", {"filename_prefix": "riley/img",
                                 "images": ["6", 0]}],
    }
    return validate_graph(g)


def g_txt2img_gguf_sdxl(unet, clip1, clip2, vae, prompt, negative="",
                        width=768, height=768, steps=24, cfg=6.5, seed=0,
                        sampler="dpmpp_2m", scheduler="karras"):
    """GGUF-unet SDXL path (UnetLoaderGGUF from ComfyUI-GGUF)."""
    g = {
        "1": ["1", "UnetLoaderGGUF", {"unet_name": unet}],
        "2": ["2", "DualCLIPLoader",
              {"clip_name1": clip1, "clip_name2": clip2, "type": "sdxl"}],
        "3": ["3", "VAELoader", {"vae_name": vae}],
        "4": ["4", "CLIPTextEncode", {"text": prompt, "clip": ["2", 0]}],
        "5": ["5", "CLIPTextEncode", {"text": negative, "clip": ["2", 0]}],
        "6": ["6", "EmptyLatentImage",
              {"width": width, "height": height, "batch_size": 1}],
        "7": ["7", "KSampler",
              {"seed": seed, "steps": steps, "cfg": cfg,
               "sampler_name": sampler, "scheduler": scheduler,
               "denoise": 1.0, "model": ["1", 0], "positive": ["4", 0],
               "negative": ["5", 0], "latent_image": ["6", 0]}],
        "8": ["8", "VAEDecode", {"samples": ["7", 0], "vae": ["3", 0]}],
        "9": ["9", "SaveImage", {"filename_prefix": "riley/img",
                                 "images": ["8", 0]}],
    }
    return validate_graph(g)


def g_txt2img_gguf_flux(unet, clip1, t5, vae, prompt, negative="",
                        width=768, height=768, steps=4, cfg=1.0, seed=0):
    """GGUF FLUX.1-schnell distilled path (4-step, ComfyUI-GGUF pack)."""
    g = {
        "1": ["1", "UnetLoaderGGUF", {"unet_name": unet}],
        "2": ["2", "DualCLIPLoader",
              {"clip_name1": clip1 or "", "clip_name2": t5,
               "type": "flux"}],
        "3": ["3", "VAELoader", {"vae_name": vae}],
        "4": ["4", "FluxGuidance", {"conditioning": ["4b", 0],
                                    "guidance": cfg}],
        "5": ["5", "CLIPTextEncode", {"text": prompt, "clip": ["2", 0]}],
        "6": ["6", "EmptyLatentImage",
              {"width": width, "height": height, "batch_size": 1}],
        "7": ["7", "KSampler",
              {"seed": seed, "steps": steps, "cfg": 1.0,
               "sampler_name": "euler", "scheduler": "simple",
               "denoise": 1.0, "model": ["1", 0], "positive": ["4", 0],
               "negative": ["5", 0], "latent_image": ["6", 0]}],
        "8": ["8", "VAEDecode", {"samples": ["7", 0], "vae": ["3", 0]}],
        "9": ["9", "SaveImage", {"filename_prefix": "riley/img",
                                 "images": ["8", 0]}],
    }
    # rewire: guidance node consumes the positive text encode
    g["4"][2]["conditioning"] = ["5", 0]
    g["7"][2]["positive"] = ["4", 0]
    return validate_graph(g)


def g_img2img_checkpoint(checkpoint, uploaded_image, prompt, negative="",
                         width=512, height=512, steps=20, cfg=7.0,
                         denoise=0.6, seed=0, sampler="euler",
                         scheduler="normal"):
    base = g_txt2img_checkpoint(checkpoint, prompt, negative, width, height,
                                steps, cfg, seed, sampler, scheduler)
    base["10"] = ["10", "LoadImage", {"image": uploaded_image}]
    base["11"] = ["11", "VAEEncode", {"pixels": ["10", 0], "vae": ["1", 2]}]
    base["5"][2]["denoise"] = denoise
    base["5"][2]["latent_image"] = ["11", 0]
    return validate_graph(base)


def g_upscale(uploaded_image, scale_by=2.0):
    """Pure-stock resize upscale (no external ESRGAN file needed)."""
    g = {
        "1": ["1", "LoadImage", {"image": uploaded_image}],
        "2": ["2", "ImageScaleBy",
              {"upscale_method": "lanczos", "scale_by": scale_by,
               "image": ["1", 0]}],
        "3": ["3", "SaveImage", {"filename_prefix": "riley/up",
                                 "images": ["2", 0]}],
    }
    return validate_graph(g)


# ----------------------------------------------------------------- video

def g_txt2vid_ltx(unet, vae, t5, prompt, negative="", width=480,
                  height=480, length=97, fps=24, steps=8, cfg=3.0, seed=0):
    """LTX-Video distilled GGUF path. length = frames (must be 8n+1).

    Uses stock LTX nodes plus UnetLoaderGGUF/VAELoader/T5 from the packs
    installed by setup_studio.ps1.
    """
    g = {
        "1": ["1", "UnetLoaderGGUF", {"unet_name": unet}],
        "2": ["2", "CLIPLoader", {"clip_name": t5, "type": "ltxv"}],
        "3": ["3", "VAELoader", {"vae_name": vae}],
        "4": ["4", "CLIPTextEncode", {"text": prompt, "clip": ["2", 0]}],
        "5": ["5", "CLIPTextEncode", {"text": negative, "clip": ["2", 0]}],
        "6": ["6", "EmptyLTXVLatentVideo",
              {"width": width, "height": height, "length": length,
               "batch_size": 1}],
        "7": ["7", "KSampler",
              {"seed": seed, "steps": steps, "cfg": cfg,
               "sampler_name": "euler", "scheduler": "simple",
               "denoise": 1.0, "model": ["1", 0], "positive": ["4", 0],
               "negative": ["5", 0], "latent_image": ["6", 0]}],
        "8": ["8", "VAEDecode", {"samples": ["7", 0], "vae": ["3", 0]}],
        "9": ["9", "SaveWEBM", {"filename_prefix": "riley/vid",
                                "codec": "vp9", "fps": fps,
                                "crf": 32, "images": ["8", 0]}],
    }
    return validate_graph(g)


def g_img2vid_ltx(unet, vae, t5, uploaded_image, prompt, negative="",
                  width=480, height=480, length=97, fps=24, steps=8,
                  cfg=3.0, seed=0):
    g = g_txt2vid_ltx(unet, vae, t5, prompt, negative, width, height,
                      length, fps, steps, cfg, seed)
    g["10"] = ["10", "LoadImage", {"image": uploaded_image}]
    g["11"] = ["11", "LTXVImgToVideo",
               {"positive": ["4", 0], "negative": ["5", 0],
                "vae": ["3", 0], "image": ["10", 0],
                "width": width, "height": height, "length": length,
                "batch_size": 1, "strength": 1.0,
                "crop": "center"}]
    g["7"][2]["latent_image"] = ["11", 0]
    return validate_graph(g)


# ------------------------------------------------------------- dispatch

BUILDERS = {}

for _fn in (g_txt2img_checkpoint, g_txt2img_gguf_sdxl, g_txt2img_gguf_flux,
            g_img2img_checkpoint, g_upscale, g_txt2vid_ltx,
            g_img2vid_ltx):
    BUILDERS[_fn.__name__[2:]] = _fn


def dumps(graph):
    return json.dumps(graph, indent=1)
