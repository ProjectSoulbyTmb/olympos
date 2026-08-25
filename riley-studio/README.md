# RILEY STUDIO - Riley's fully local AI creative suite

A stable Windows application suite for AI image and video creation.
Quantized open-weight models run through a loopback-only ComfyUI tier;
an Electron canvas app gives layers, text, templates and a video
timeline. Prompts go straight to the weights - there is no vendor
filter in the stack, because nothing ever leaves the machine.

> **Acceptable use (hard line).** Riley Studio runs unfiltered models
> locally, on you: fictional and abstract work, licensed material, your
> own performances. It contains no face-swap, identity-clone or
> person-likeness tooling, and must not be used to synthesize intimate
> or deceptive material of real, identifiable people.

## Tiers (sized for a 4GB laptop GPU; auto-detected)

| Key | Tier | What | Download |
|---|---|---|---|
| `sd15` | fast | SD 1.5 checkpoint, seconds per image @512px | ~2.0 GB |
| `sdxl-q4` | quality | SDXL GGUF Q4 + dual CLIP + VAE | ~5.7 GB |
| `flux-schnell-q4` | flagship | FLUX.1-schnell GGUF Q4, minutes/image | ~9.7 GB |
| `ltxv-distilled-q3` | video | LTX-Video 0.9.6 distilled Q3, short clips | ~5.5 GB |

All Hugging Face URLs were verified live at build time. Two pieces are
license-gated upstream (SDXL clip slices, Flux VAE) - accept the license
on huggingface.com once, then re-run the pull.

## Install

```powershell
powershell -ExecutionPolicy Bypass -File riley-studio\setup_studio.ps1        # core (ffmpeg)
powershell -ExecutionPolicy Bypass -File riley-studio\setup_studio.ps1 -Ai    # + ComfyUI stack
```

The AI stack lands in `$env:RILEY_STUDIO_AI_HOME`, else `D:\riley-studio-ai`,
else repo-local `ai-stack\` - never inside OneDrive-synced storage.
Model weights pull from the Studio Models window or:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8288/api/models/pull `
  -Body '{"key":"sd15"}' -ContentType application/json
```

## Run

```powershell
python riley-studio\server.py          # engine API on 127.0.0.1:8288
# ComfyUI (started by the Studio app, or by hand):
#   D:\riley-studio-ai\venv\Scripts\python.exe D:\riley-studio-ai\ComfyUI\main.py --port 8188 --lowvram
npm --prefix riley-studio\studio start # canvas app (dev mode)
```

## Engine API (loopback only, {"ok":true} envelope)

```
GET  /api/status            vitals: comfy up, VRAM, queue depth, disk
GET  /api/models            manifest + install state + tier advice
POST /api/models/pull       {"key":"sd15"}           -> background download
POST /api/generate          {"kind":"txt2img","model":"sd15","prompt":"...",
                             "width":512,"height":512,"seed":7}
GET  /api/job/<id>          status: pending|running|done|error|cancelled
GET  /api/gallery           every finished output with metadata
GET  /api/file?p=outputs/…  path-jailed file serving
```

Kinds: `txt2img_checkpoint`, `txt2img_gguf_sdxl`, `txt2img_gguf_flux`,
`img2img_checkpoint` (+`image` path), `upscale` (+`image`,`scale_by`),
`txt2vid_ltx`, `img2vid_ltx`. Or pass `"kind":"txt2img"` plus a
`"model"` key and the queue picks the right graph automatically.

## Layout

| Path | Role |
|---|---|
| `engine/comfy.py` | loopback-only ComfyUI client |
| `engine/models.py` | verified manifest, resumable downloader, VRAM tier picker |
| `engine/graphs.py` | workflow graph builders + structural validator |
| `engine/queue.py` | crash-safe serial queue, JSONL journal |
| `server.py` | stdlib HTTP API binding 127.0.0.1 |
| `studio/` | Electron canvas app (layers, gallery, models, timeline) |
| `scripts/` | stabilize / package / installer pipeline |

## Verify gate

```powershell
python verify_riley_studio.py     # repo root; offline-safe, exit code = verdict
```
