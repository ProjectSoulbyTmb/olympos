# Assemble with it - KINEMA offline video studio
keywords: kinema ffmpeg slideshow xfade concat trim gif scene-cut perceptual production
KINEMA (workspace repo `kinema\`) is the FFmpeg production engine for when viewing turns into making. It renders JSON job specs headlessly, stdlib-only around an ffmpeg/ffprobe binary:

- slideshow: images[] joined with hard cuts OR xfade dissolves; plus concat, trim, scale, crop, fades, watermark, timed text cards, speed ramps, palette GIFs, frame extraction.
- Enhanced analysis: perceptual hashes, scene-cut detection, motion scoring - the fast way to distill highlight reels out of long `D:\new` compilations.
- Resumable folder-fed learning catalog with style profiles; watch-loop ingest; optional loopback-only ComfyUI AI tier (dark on this hardware).

Setup: `powershell -File kinema\setup_kinema_stack.ps1`; gate: `python verify_kinema.py`; job-spec examples in `kinema\README.md`.

Division of labor across the sisters: APHRODITE = look (browse/rate/cull), RILEY = transform singles (animate/upscale/grade/GIF), KINEMA = assemble many into a finished mp4.
