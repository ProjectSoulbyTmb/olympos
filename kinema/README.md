# KINEMA - Riley's Private Offline Video Studio

Local-first video creation, enhanced analysis and a folder-fed
learning catalog. Free, open tooling only: FFmpeg does the media
work, an optional ComfyUI tier adds local AI generation, and every
line in this realm is stdlib Python. Nothing leaves the machine.

> **Acceptable use (hard line).** KINEMA is for footage you own or
> have the right to use. It deliberately contains **no** face-swap,
> identity-clone or person-likeness training tech, and must not be
> pointed at libraries of real people's intimate content to
> synthesize new material of them. Synthetic-video generation is
> allowed for abstract/stylized content, licensed stock, your own
> performances, and fictional scenes that do not depict real,
> identifiable people.

## Install (one command)

```powershell
powershell -ExecutionPolicy Bypass -File kinema\setup_kinema_stack.ps1
```

That drops portable `ffmpeg.exe`/`ffprobe.exe` into `kinema\bin\`
(offline forever after). Optional local AI tier:

```powershell
powershell -ExecutionPolicy Bypass -File kinema\setup_kinema_stack.ps1 -Ai          # NVIDIA GPU
powershell -ExecutionPolicy Bypass -File kinema\setup_kinema_stack.ps1 -Ai -CpuOnly # CPU-only
```

The AI tier clones ComfyUI + a venv under `ai-stack\` (gitignored).
You choose and download model weights yourself; the studio then talks
to `127.0.0.1:8188` only - remote hosts are refused by default.

## Use

```powershell
python -m kinema                 # interactive studio menu
python -m kinema doctor          # environment check
python -m kinema analyze --root D:\my-footage     # learn from folder
python -m kinema catalog --list                   # what was learned
python -m kinema sample --input clip.mp4 --count 8 --format png
python -m kinema produce --demo  # end-to-end synthetic mp4+gif
python -m kinema produce --job job.json           # full pipeline
python -m kinema watch-config --add-root D:\my-footage
python -m kinema watch --once    # sweep new files now / --loop
python -m kinema ai status | ai template wf.json | ai run ...
```

## What each piece does

| Module | Role |
|---|---|
| `ffmpeg_tools.py` | binary discovery, bounded subprocess runs, ffprobe JSON normalization |
| `imaging.py` | pure-Python PPM decode, perceptual hashes (aHash/dHash), color histograms, scene-cut detection, motion scoring |
| `analysis.py` | per-video fingerprints -> resumable `data/kinema/catalog.json`; aggregate **style profile** (shot cadence, resolution mix, motion) = the folder's learned taste |
| `watcher.py` | poll loop over configured roots: new videos auto-analyzed + preview-sampled, events logged to `events.jsonl` |
| `jobs.py` / `produce.py` | JSON job specs rendered by FFmpeg: slideshow (hard cuts **or** xfade dissolves), concat, trim, scale, crop, fades, watermark, timed text cards, speed ramps, palette GIFs, frame extraction |
| `ai_bridge.py` | loopback-only ComfyUI client: submit workflow -> poll -> download clips ready for the production engine |

### Job spec example

```json
{"name": "my reel", "workdir": "out",
 "steps": [
   {"type": "slideshow", "images": ["a.png", "b.png", "c.png"],
    "per_image": 2.5, "crossfade": 0.6, "size": "1920x1080",
    "fps": 30, "audio": "track.mp3", "output": "reel.mp4"},
   {"type": "text", "input": "reel.mp4", "output": "reel_titled.mp4",
    "text": "summer 2026", "fontsize": 72, "start": 0, "end": 4},
   {"type": "gif", "input": "reel_titled.mp4", "output": "reel.gif",
    "fps": 12, "width": 480}]}
```

Steps run in order inside `workdir`; later steps may use earlier
outputs by relative path. A `<name>.report.json` lands beside them.
Encoders fall back automatically (`libx264`, else `mpeg4`) so any
FFmpeg build works.

## Verify gate

```powershell
python verify_kinema.py
```

Offline-safe: synthesizes its own frames/videos, skips FFmpeg-bound
tests when the binary is absent, exits non-zero on any failure.
