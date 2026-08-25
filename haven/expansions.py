"""expansions - the full technological-expansion curriculum for HAVEN.

Each entry becomes a topic card: {domain, title, body_md, keywords,
source(optional rel path)}. Bodies are written for kernel learners:
what it is, the canonical open tools/models, how it plugs into OUR
stack (riley-studio engine graphs / canvas / ffmpeg compositor), and
VRAM feasibility tiers on the operator's hardware:

  [4GB-ok]   runs today on the GTX 1650 class
  [8GB+]     needs a VRAM upgrade path (RTX 3060 12GB class)
  [CPU-ok]   no GPU required

Confidence marker at the end of each body: [core] = long-established,
[current-2026] = verified against this machine's ecosystem during the
2026-08 build, [evolving] = fast-moving, re-check before relying.
"""

EXPANSIONS = [
# ================================================================ control
{"domain": "generation-control", "title": "ControlNet: directed composition",
 "keywords": "controlnet pose depth canny tile lineart scribble",
 "body_md": """Conditioning nets that steer diffusion with a spatial map instead of hoping the prompt lands it.

Canonical open implementation: lllyasviel/ControlNet (v1.1 zoo) + ComfyUI's native `ControlNetLoader`/`ControlNetApplyAdvanced`. For SDXL use TTPlanet/SDXL control models; for Flux/Qwen-era bases, XLabs/Shakker variants [evolving].

Maps we care about, ranked by studio value:
- **depth** (Depth Anything v2, MiDaS): lock blocking/composition from a photo or 3D previz
- **openpose** (DWPose estimator): exact body posing for characters
- **canny/lineart/scribble**: ink-to-image, sketch-to-final
- **tile**: upscale-with-reimagination without changing global layout
- **softedge/mlsd**: architecture/product edges

Our integration path: riley-studio engine gains a `control` param on txt2img graph builders -> ControlNetApplyAdvanced between CLIP encode and KSampler; canvas gets a 'guide map' layer type (image dropped onto stage, exported as conditioning input via comfy /upload/image).

VRAM: standard ControlNets add 0.3-1.5GB activations [4GB-ok at fp16 for SD1.5-size, tight for SDXL]; Q8/Q4 quantized control nets exist for the GGUF route [current-2026].

Rule of thumb: strength 0.6-1.0 for structure you must keep, 0.35-0.6 for guidance you may deviate from. Pair with lower CFG (5-7) or the guide fights the prompt. [core][current-2026]"""},

{"domain": "generation-control", "title": "T2I-Adapter: lightweight steering",
 "keywords": "t2i adapter adapter steering lightweight",
 "body_md": """TencentARC/T2I-Adapter: ControlNet's little sibling. Same idea (feed depth/sketch/palette/color maps into the UNet) at a fraction of the parameters (~77M vs 350M+) - one adapter loads in ~150MB.

Choose over ControlNet when: VRAM is scarce [4GB-ok], or when approximate guidance is fine. Weaker structural fidelity; best maps are sketch, depth, and especially **color-grid palettes** (prompt says 'sunset', adapter enforces WHERE colors sit).

ComfyUI: `T2IAdapterLoader` + `T2IAdapterApply`. Integration mirrors our ControlNet plan - same `control` param slot, adapter picked by map kind. [core]"""},

{"domain": "generation-control", "title": "IP-Adapter & reference-only conditioning",
 "keywords": "ip-adapter faceid style reference image prompt pulid instantid",
 "body_md": """Image-as-prompt. IP-Adapter (tencent-ailab) decouples image features via a parallel cross-attention encoder: give it a photo -> outputs follow its subject/style while the text keeps steering.

Variants that matter:
- **IP-Adapter standard** (style/object reference, weight 0.3-0.8)
- **IP-Adapter-FaceID / FaceID-PlusV2**: identity lock from a face photo (needs insightface embeddings)
- **IP-Adapter Plus / SDXL**: stronger fidelity
- **InstantID / PuLID**: zero-training identity preservation, one reference portrait [current-2026]

Studio use: character sheets across shots, product placement, 'paint it like THIS'. Our stack: load via ComfyUI `IPAdapterModelLoader`+`IPAdapterAdvanced` (ComfyUI_IPAdapter_plus pack); engine param `ip_image` + `ip_weight`; canvas 'reference' panel uploads via /upload/image like ControlNet guides.

VRAM: +0.5-1.2GB with the CLIP vision encoder [4GB-ok SD1.5 tier, tight SDXL]. Face ID also wants an insightface onnxruntime install. [core][current-2026]"""},

{"domain": "generation-control", "title": "Regional prompting & attention coupling",
 "keywords": "regional prompting attention couple mask blending compose",
 "body_md": """Put DIFFERENT prompts in different regions: left half 'a knight', right half 'a dragon', one shared background.

Open routes: ComfyUI `AttentionCouple` node pair, or mask-conditioned conditioning Combine ( ConditioningSetMask + ConditioningCombine ) - pure stock nodes, no custom pack needed. Latent-blend fallback (two full renders composited then img2img) loses coherence; attention-level coupling does not.

Engine shape: txt2img params grow `regions:[{mask,x,y,w,h,prompt,strength}]` -> builder emits SetMask+Combine chain. Canvas synergy: rectangular selection tool already exists (rect layers) -> convert selection to region prompt.

VRAM: negligible extra [4GB-ok]. [core]"""},
# ============================================================ consistency
{"domain": "generation-consistency", "title": "LoRA: styles & characters without retraining the base",
 "keywords": "lora finetune style character kohya trigger words weight",
 "body_md": """Low-Rank Adapters: 10-500MB patches that bend any checkpoint toward a style, character, product, or concept trained via kohya_ss/OneTrainer.

Usage law: load with `LoraLoaderModelOnly` (or full `LoraLoader` incl. clip), strength 0.5-1.2; >1.3 usually burns contrast and anatomy. Stack up to 2-3 before interference; put character LoRAs before style LoRAs in the chain. Trigger words come from the LoRA's own card - our manager should index them.

Ecosystem sources: Civitai (largest), HuggingFace. License-check per asset (many are base-model-gated: SDXL-derived inherits SDXL license).

Our plan: `lora:[name:weight]` inline grammar parsed by the prompt engine + a Models-window tab listing installed loras (scan ai-home models/loras) with preview thumbnails and trigger-word index. Engine: loop `LoraLoader` nodes between checkpoint and KSampler.

VRAM: adapter weights only [4GB-ok]. Training is separate (kohya, 12GB+ recommended) - out of scope until the hardware upgrade. [core][current-2026]"""},

{"domain": "generation-consistency", "title": "Textual inversions & embeddings",
 "keywords": "textual inversion embedding ti easynegative",
 "body_md": """Tiny (~5-50KB) token vectors teaching ONE concept ('that artist's line weight', 'bad-hands-avoid'). Loaded via `EmbeddingLoader`/CLIPTextEncode with the embedding filename as a literal token in the prompt.

Famous utility embeddings: EasyNegative, BadHands, FastNegativeV2 - drop into negatives for automatic quality cleanup.

Difference vs LoRA: embeddings touch only the text encoder (weaker, cheaper); LoRAs reshape the UNet (stronger). Use embeddings for negative-cleanup and micro-concepts; LoRA for anything needing real capacity. [4GB-ok]. [core]"""},

{"domain": "generation-consistency", "title": "Character/product consistency across shots",
 "keywords": "consistency seed faceid reference storyboard same character",
 "body_md": """Ranked toolkit for keeping the same face/product across a shoot (the storyboard problem):

1. **Same seed + same LoRA + same prompt skeleton**, vary only scene tokens - cheapest, drifts slowly [4GB-ok]
2. **IP-Adapter-FaceID / InstantID / PuLID** from one reference portrait - strong identity, some stiffness [4GB-ok SD1.5]
3. **Reference-only ControlNet** on the previous approved frame - shot-to-shot chaining
4. **Face swap post-pass** (ReActor/inswapper_128) - last resort; identity comes from a real photo, so it sits behind our acceptable-use gate: fictional characters only, never a real person without their consent [house-rules]
5. Full **DreamBooth/LoRA training** of the subject - gold standard [needs 12GB+ training rig]

Director-mode tie-in: Riley picks takes from an XY grid of method x seed, locks the winning recipe into the project manifest. [core][current-2026]"""},
# ================================================================ refine
{"domain": "generation-refine", "title": "Inpainting: surgical regeneration",
 "keywords": "inpaint mask vaeinpaint denoise repair hands",
 "body_md": """Regenerate ONLY a masked region. Stock ComfyUI chain: LoadImage(mask alpha) -> VAEEncodeForInpaint (or SetLatentNoiseMask) -> KSampler(denoise 0.4-0.9) -> VAEDecode. Dedicated inpaint checkpoints (runwayml sd15-inpaint, SDXL brushnet/fool-inpaint) handle large holes better than generic ones.

Studio workflow (Phase 2 target): canvas mask brush paints red overlay -> export PNG with alpha -> POST /api/generate {kind:'inpaint', image:<rel>, mask:<rel>, prompt, denoise} -> result replaces layer non-destructively (kept as history step).

Classic uses: hands, faces, text artifacts, object removal (mask + empty prompt + denoise 1.0 with inpaint model).

VRAM: same as base model pass [4GB-ok]. GrowMask node expands soft edges - always feather 8-24px. [core]"""},

{"domain": "generation-refine", "title": "Outpainting: extending the frame",
 "keywords": "outpaint uncrop expand canvas fill",
 "body_md": """Grow the canvas beyond the original pixels. Two stock strategies:
1. Pad latent (PadImageForOutpaint) + full denoise - model invents freely
2. Mask-the-border + moderate denoise (0.55-0.75) - keeps center locked

Canvas integration is uniquely strong for us: user drags the STAGE bounds bigger, marks old-vs-new with the mask brush, engine receives composed base+alpha. Iterate outward 512px per pass for panoramas. [4GB-ok]. [core]"""},

{"domain": "generation-refine", "title": "Hires-fix & multi-pass refinement",
 "keywords": "hires fix latent upscale second pass refine detail",
 "body_md": """Why: direct 1024px+ sampling on SD1.5/SDXL duplicates heads and melts geometry. The fix: compose at native res (512/1024), latent-upscale 1.5-2x, second KSampler pass at denoise 0.35-0.55 with added-detail prompt tail.

Stock nodes: LatentUpscaleBy -> KSampler #2. Variants: upscale MODEL first (4x-UltraSharp) then VAE-encode down - sharper micro-texture at same cost.

Engine shape: `hires:true, scale:1.6, second_denoise:0.45` params on txt2img builders; costs ~2.2x render time. [4GB-ok at 512->819 latent; 1024-base hires needs the upgrade]. [core]"""},

{"domain": "generation-refine", "title": "Pro upscalers: ESRGAN family to SUPIR",
 "keywords": "esrgan realesrgan supir upscale 4x ultra sharp tiled",
 "body_md": """Ladder, cheapest first:
- **Lanczos/ffmpeg** - geometry only, zero ML [CPU-ok, shipped]
- **4x-UltraSharp / RealESRGAN_x4plus / ESRGAN_anime** (~65MB .pth each, UpscaleModelLoader+ImageUpscaleWithModel) - crisp 4x, occasionally hallucinate texture [4GB-ok]
- **CCSR / ResShift** - faithful upscaling, less invention
- **SUPIR** - diffusion-based 'super resolution' with text steering; stunning, 12GB+ and slow [8GB+]

Tiled inference (TiledDiffusion/TiledVAE) breaks the 4GB wall for big prints: process 1024px tiles with 50% overlap + seam blend. Engine: manifest entries for UltraSharp/RealESRGAN downloads into models/upscale_models + `upscale_model` param on the upscale kind; ffmpeg stays the final resize/format pass. [core][current-2026]"""},

{"domain": "generation-refine", "title": "Detail & face restoration",
 "keywords": "adetailer facedetailer gfpgan codeformer restore hands",
 "body_md": """Detect-fix-paste loops: run a face/hand detector, crop each hit, img2img at high denoise with a restoration net, paste back with blended seams.

Tools: ADetailer pack for ComfyUI (Ultralytics YOLO detectors: face, hands, person) + **GFPGAN v1.4** / **CodeFormer** (fidelity-weight 0.5-0.7) restorers; MeshGraphormer-class hand refiners for the hardest case.

Engine shape: post-process flag `detail_faces:true` on txt2img -> detector+restore subgraph appended after VAEDecode. Gallery action 'fix faces' on existing renders.

VRAM: YOLO ~200MB + GFPGAN ~300MB [4GB-ok]. Ethics unchanged: restoration operates on generated/fictional faces; never tuned to identify real people. [core]"""},
# ================================================================= models
{"domain": "models-2026", "title": "Base model landscape (images)",
 "keywords": "sd15 sdxl sd35 flux qwen hidream playground pony illustrious",
 "body_md": """What each open base is FOR (mid-2026 view):

- **SD 1.5** - tiny, infinite ecosystem, 512px native. Our fast tier. Aging but unbeatable for drafts on 4GB.
- **SDXL 1.0** - 1024px native, dual CLIP. Derivative empires: Pony/Illustrious (anime), Juggernaut (photo). Our quality tier via Q4 GGUF unet.
- **SD 3.5 Medium/Large** - MMDiT arch, strong prompt adherence + legible text; Medium runs 8GB-ish quantized [8GB+].
- **FLUX.1 dev/schnell/Krea** - 12B flow-matching; best-in-class text rendering & composition. Schnell = 4-step Apache-2.0 (our flagship tier); dev = guidance-distilled, non-commercial license CAREFUL.
- **Qwen-Image, HiDream-I1** - 2025 entrants, excellent bilingual text/render; heavy [8GB+, GGUF partials] [evolving].

Selection heuristic for learners: draft=SD1.5, deliver=SDXL-Q4 or Flux-schnell-Q4, typography-heavy=Flux, anime=Pony-family SDXL. All load through our existing checkpoint/gguf graph routes. [current-2026]"""},

{"domain": "models-2026", "title": "Quantization formats: GGUF, fp8, nf4",
 "keywords": "gguf q4 q8 fp8 nf4 quantization vram compression city96",
 "body_md": """How big models squeeze into small cards:

- **GGUF** (city96 packs): k-quants Q2-Q8. Q4_K_S ~= 60% size, minor quality loss; Q8 ~= near-lossless. Loads via UnetLoaderGGUF (our installed ComfyUI-GGUF). Best quality-per-GB below 8GB cards.
- **fp8 (e4m3)**: native half-of-half precision; official Comfy-Org repacks (our flux-schnell-fp8 option). Needs fp8-capable cards for speed wins; else runs emulated.
- **nf4/bnb int4**: bitsandbytes route, similar ballpark to Q4.

Tradeoff ladder for the same 12B Flux: fp16 22GB -> fp8 11-16GB -> Q8 12GB -> Q6 8.5GB -> Q4 6.4GB. Below Q4, composition degrades faster than texture.

Operator rule baked into our Models window: pick the largest quant whose weights+activations fit under (VRAM - 700MB OS headroom); the picker already does this via vram_gb fields. [current-2026]"""},
# ================================================================== video
{"domain": "video-generation", "title": "DiT video models: Wan, Hunyuan, CogVideoX, LTX-2",
 "keywords": "wan hunyuan cogvideo ltx mochi video diffusion transformer",
 "body_md": """The 2025-26 open-video field is transformer-based (DiT), not UNet:

- **Wan 2.1/2.2** (Alibaba, Apache): 14B (best quality, [8GB+ quantized]) and TI2V-5G (compact, native 720p@24 sound-ready [8GB+]). Text+img2vid.
- **HunyuanVideo** (Tencent, 13B): cinematic motion, community LoRAs [8GB+ GGUF].
- **CogVideoX-2B/5B**: older but lightest true DiT; 2B borderline [4GB+ with Q4 + cpu-offload].
- **LTX-Video 0.9.x -> LTX-2.x** (Lightricks): realtime-fast distilled inference; our ltxv-distilled-q3 tier is exactly this family [4GB-ok]; LTX-2 adds audio-native tracks [evolving - city96 GGUFs seen on HF 2026-08].
- **Mochi** (Genmo): 14B alternative [8GB+].

Practical knobs that matter everywhere: steps (distilled=4-8, base=20-50), CFG (distilled 1-3, base 6-9), frame count 8n+1, resolution multiples of 32/64, shift/scheduler per family.

Our roadmap Phase 4/5 targets Wan-TI2V as the quality jump once VRAM allows; LTX remains the 4GB workhorse. [current-2026][evolving]"""},

{"domain": "video-generation", "title": "Image-to-video & first-frame direction",
 "keywords": "img2vid first frame keyframe animate ltxv imagetovideo",
 "body_md": """Animate a still: image encodes to initial latent (LTXVImgToVideo / WanImageEmbed / CogVideoX ImageToVideo), text drives MOTION not appearance ('slow push in, hair moving, rain falling').

Craft rules that hold across families:
- describe camera + atmosphere, NOT new objects (they flicker in)
- low CFG on distilled models (1.5-3); over-guidance = boiling
- 97 frames @24fps ~= 4s sweet spot for LTX-distilled on 4GB
- feed CLEAN upscaled first frames; artifacts amplify 10x in motion

Already shipped in our engine: g_img2vid_ltx + canvas Animate button. Next: endframe/keyframe conditioning (Wan FLF / VACE-style start+end frames) so storyboards interpolate A->B [evolving]. [current-2026]"""},

{"domain": "video-generation", "title": "Vid2vid: restyling real footage",
 "keywords": "vid2vid restyle transfer footage controlnet video denoise",
 "body_md": """Take owned footage -> diffusion-restyled output while keeping motion. Routes:
1. **Frame-batch img2img + temporal glue**: denoise 0.35-0.5 per frame with fixed seed/LoRA, then RIFE smooth + ffmpeg deflicker. Cheap, flickers without glue. [4GB-ok short clips]
2. **ControlNet-tiling pipelines** (depth+lineart multi-control, TileMaster-style): structure locked by maps, style free. Better coherence. [4GB-ok at 512]
3. **True vid2vid DiTs** (Wan 2.2 fun/VACE variants): native coherent rewrite [8GB+].

House-law reminder: source footage must be operator-owned/licensed; acceptable-use line applies to what the OUTPUT depicts. Kinema already fingerprints owned footage - reuse its ingest as the vid2vid front door. [core][current-2026]"""},

{"domain": "video-generation", "title": "Motion & camera control",
 "keywords": "motion control drag trajectory camera dolly dragnuwa vace",
 "body_md": """Beyond text-hoping:
- **Trajectory/drag steering** (DragNUWA, Motion-I2V, MOFA-Video class): draw arrows/paths -> objects track them [mixed VRAM, 4GB marginal]
- **Camera presets**: zoom/pan/orbit prompt tags standardized across families ('dolly in', 'orbit left 15deg'); LTX responds well to explicit focal language
- **Keyframe pairs** (start/end frame conditioning): most robust directorial primitive, shipping next in our engine [current-2026]
- **LoRA motion vocabularies**: community camera-move LoRAs for Wan/LTX

Integration: canvas timeline already has per-clip durations; Phase 4 adds per-clip motion tags -> engine builds conditioned graphs. Treat camera language as data, not vibes: store chosen tag + seed in the clip record for replay. [evolving]"""},
# ============================================================= video-post
{"domain": "video-post", "title": "Frame interpolation: RIFE, FILM, GIMM",
 "keywords": "rife film gimm interpolation 60fps smooth frames",
 "body_md": """Generated video is typically 16-24fps; delivery wants 30/60. Interpolators synthesize in-between frames:

- **RIFE** (ncnn/real-esrgan ports, Practical-RIFE): fastest, good on clean synthetic content; ComfyUI-Frame-Interpolation pack or standalone CLI [4GB-ok / CPU slow-ok]
- **FILM** (Google): better on large motion, slower
- **GIMM-VFI**: SOTA quality on complex motion [current-2026], heavier

Pipeline position: generate 97f@16fps -> interpolate x2/x4 -> encode 48/64fps -> NVENC mux. Beware interpolating BEFORE color grading (double work) and on heavily quantized sources (interpolates the artifacts too).

Engine home: new post step type `interpolate:{model,factor}` in export.py compiled to the RIFE CLI; ffmpeg minterpolate stays CPU fallback (slow, artifacty - prefer RIFE). [core][current-2026]"""},

{"domain": "video-post", "title": "Deflicker, stabilize, cleanup",
 "keywords": "deflicker vidstab stabilize denoise temporal cleanup",
 "body_md": """Temporal hygiene for generated/restyled clips:
- **deflicker** (ffmpeg `deflicker` filter or exposure-keyframe passes): kills luminance pumping from per-frame diffusion variance
- **vidstab** (ffmpeg two-pass `vidstabdetect`/`vidstabtransform`): steadies handheld source before vid2vid - huge quality win, [CPU-ok]
- **temporal smoothing**: mt_bloom/hqdn3d light denoise between interpolation and grade
- **scene-cut aware processing** (kinema's detector): never interpolate across a cut

Order of operations that works: stabilize -> deflicker -> restyle/generate -> interpolate -> grade -> encode. Each stage reversible in our job journal. [core]"""},
# =================================================================== audio
{"domain": "audio-tech", "title": "Local TTS: Piper & friends",
 "keywords": "piper tts voice narration speech coqui xtts",
 "body_md": """Narration without cloud:
- **Piper** (rhasspy): tiny ONNX voices, ~real-time on CPU, 30+ languages, MIT voices [CPU-ok]. THE default for our narration tracks: WAV out -> timeline audio layer -> ffmpeg amix.
- **Coqui XTTS-v2**: voice cloning from 6s reference, GPU-warm [4GB-ok slow]; license non-commercial - flag in license ledger
- **Whisper-voice / F5-TTS class** [evolving]: better prosody, heavier

Pipeline: script text -> Piper (--model en_US-lessac-medium) -> optional ffprobe duration -> auto-fit slideshow per_image to narration length (already have per-clip durations). Voice consistency across a reel = pin ONE model+speaker id in project settings. [core][current-2026]"""},

{"domain": "audio-tech", "title": "Transcription & captions: whisper.cpp",
 "keywords": "whisper cpp subtitles srt transcription captions asr",
 "body_md": "**whisper.cpp** runs OpenAI Whisper models fully local on CPU (base/small = sweet spot) [CPU-ok]: audio -> timestamped segments -> we render both a burn-in subtitle track (ffmpeg subtitles filter w/ styled ASS) and a sidecar .srt.\n\nUses beyond captions: auto-title reels from narration keywords; searchable transcript stored in gallery metadata; kinema watcher could auto-caption ingested footage.\n\nModels: ggml-base.en ~148MB, small ~466MB, distil-large-v3 [quality/speed trade]. Word-level timestamps need --max-len or tiny model tweaks; segment-level suffices for reels. [core][current-2026]"""},

{"domain": "audio-tech", "title": "Music & SFX generation, licensing-safe beds",
 "keywords": "musicgen maudio audiocraft sfx sound bed cc0 library",
 "body_md": """Two supply paths for soundtracks:
1. **Generate locally**: Meta AudioCraft MusicGen (small=300M runs [4GB-ok slow], medium/large [8GB+]) for instrumental beds; MMaudio-class joint audio-video models emerging [evolving]. SFX: AudioGen/AudioLDM2 short-fx mode.
2. **Curated CC0 library**: ship a `haven/audio-beds/` folder of Kevin MacLeod-class CC0 loops indexed by mood tags; deterministic, instant, zero-license-risk. RECOMMENDED default; generation fills gaps.

Sync law: music ducking under narration (sidechaincompress in ffmpeg), loudness normalize to -14 LUFS (loudnorm filter) for web delivery. Timeline gets an audio track type with fade handles; export compiles via amix + loudnorm chain. [core][current-2026]"""},

{"domain": "audio-tech", "title": "Lip sync post-pass",
 "keywords": "lipsync latentsync wav2lip talking head sync",
 "body_md": """Aligning a generated/filmed face to narration AFTER the fact: Wav2LiP-class (light, mushy) -> LatentSync/Sonic-class diffusion lipsync (convincing, [8GB+] mostly; distilled variants coming down) [evolving].

Scope guard: applies to FICTIONAL avatars or operator-owned performances. Combined with our no-real-person-likeness rule this stays clean; document that in the feature's UI copy when Phase 6+ lands.

Integration shape: audio track + face-track selection -> job kind `lipsync:{clip,audio,model}` -> replaced video layer. Not scheduled before the VRAM upgrade. [current-2026]"""},
# ============================================================== delivery
{"domain": "encode-delivery", "title": "Hardware encode: NVENC on the 1650",
 "keywords": "nvenc h264 hevc hardware encode gpu ffmpeg",
 "body_md": """The GTX 1650 carries a Turing NVENC unit INDEPENDENT of CUDA cores - encoding never touches our generation VRAM budget meaningfully (~100MB session overhead).

ffmpeg switches: `-c:v h264_nvenc -preset p5 -rc vbr -cq 23` (HEVC: hevc_nvenc, AV1 NOT supported on Turing). Quality vs libx264: slightly larger files at same SSIM, 5-10x faster - decisive for reels.

Fallback ladder our export.py should compile: h264_nvenc -> libx264 (preset veryfast) if nvenc session fails (driver-less machines). Also nvenc for live-preview proxies at ultrafast.

Probe: `ffmpeg -encoders | findstr nvenc`. Session limits: consumer cards historically capped 3-8 concurrent NVENC sessions - irrelevant for our serial queue. [core][current-2026]"""},

{"domain": "encode-delivery", "title": "Masters, ladders & platform exports",
 "keywords": "prores dnxhr master bitrate ladder platform export preset",
"body_md": """Delivery discipline:
- **Archive master**: ProRes 422 HQ (.mov) or DNxHR HR - intra-frame, edit-friendly, huge. One per project, kept on D:.
- **Web ladder** from master: H.264 High@L4 yuv420p CRF 18-21 faststart (YouTube/IG), HEVC CRF 22 for smaller, AV1 (SVT-AV1 crf 30) when platforms pay off [CPU slow-ok].
- **Per-platform crops**: one source, three aspect cuts (16:9, 9:16, 1:1) via our canvas presets + ffmpeg crop/scale - compile as multi-step export spec (engine supports chained steps already).
- **Audio**: aac 192k stereo, loudnorm -14 LUFS.

Export dialog (Phase 4): master checkbox + platform chips; compiles to N sequential engine jobs with progress per rung. [core]"""},

{"domain": "encode-delivery", "title": "Color management & LUTs",
 "keywords": "lut cube color grade srgb rec709 hdr pq hlg scopes",
 "body_md": """Keep color honest end-to-end:
- Working space: sRGB stills / Rec.709 video, 8-bit pipeline today, 10-bit (yuv420p10le) when grading hard
- **LUT support**: ffmpeg `lut3d=file.cube` applied post-interpolate/pre-encode; ship curated creative LUTs (teal-orange etc) + accept user .cube drops in `haven/luts/`
- **Scopes**: waveform/vectorscope previews (ffmpeg showspectregraph/waveform filter rendered to png for the canvas inspector)
- **HDR path** (PQ/HLG 10-bit, bt2020): encode-capable via NVENC hevc 10bit; full HDR pipeline deferred until displays/demand justify [evolving]

Grade order: normalize (levels/white balance) -> creative LUT -> vignette/grain -> encode. Store LUT name + intensity per project for replay. [core]"""},
# ============================================================ performance
{"domain": "performance-vram", "title": "VRAM orchestration & OOM recovery",
 "keywords": "vram orchestrator oom offload block swap keep warm unload",
 "body_md": """4GB survival kit, ordered by leverage:
1. **Quant right-sizing** (Models window already advises)
2. **--lowvram/--novram ComfyUI flags + block-swap** (ComfyUI-GGUF/native): stream layers over PCIe, trading speed for fit
3. **Sequential model policy**: our queue is serial by design - enforce `unload models between kinds` (free memory before video after images) via /api or ComfyUI /free endpoint
4. **OOM catch-retry ladder**: catch torch OOM in worker -> retry at width*0.8 / steps*0.7 -> retry quant-down if alternate installed -> fail gracefully with actionable message
5. **Keep-warm set**: pin the tier the operator actually uses (sd15) to avoid 20s reloads; evict on video jobs

Telemetry worth surfacing: nvidia-smi utilization+memory polled into tray tooltip (shell already polls health). [current-2026]"""},

{"domain": "performance-vram", "title": "Result cache & replay determinism",
 "keywords": "cache hash seed deterministic replay dedupe",
 "body_md": """Hash-address everything: key = sha256(model_sha + graph_json + sampler_params + seed). Cache hits return instantly from disk instead of re-rendering identical requests; gallery dedupes on the same key.

Determinism contract: same key => pixel-identical output on same hardware/driver. Enemies: nondeterministic kernels (cuDNN autotune - mitigate torch.use_deterministic_algorithms where supported), float atomics, and ANY change in node versions -> therefore graph_json AND comfy commit hash join the key.

Storage: cache table in a sidecar sqlite (not HAVEN - that's curriculum; this is operational state) keyed by hash -> outputs path. LRU eviction by bytes with operator cap. Replay manifests (roadmap Phase 5) build directly on these keys. [core][current-2026]"""},
# =========================================================== provenance
{"domain": "provenance-rights", "title": "C2PA content credentials on exports",
 "keywords": "c2pa content credentials provenance signing watermark",
 "body_md": """Cryptographic 'what made this' metadata embedded in exports (JPEG/PNG/MP4): generator identity, edit history chain, timestamps. c2pa-python-SDK (rust core) signs; validate with c2patool/Verify button.

Why it matters here: our whole stack is local/unfiltered - credentials are how PROVENANCE travels with the file without phoning home. Sign exports with a local key; disclosure is optional-but-available.

Watermarks complement: invisible StableSignature-style decoder marks + optional visible badge. Both are post-VAEDecode image ops - cheap to append in graphs.

License ledger (companion): before a gated pull completes, require recorded acceptance (who/when/license-url) persisted in the models db; Models window surfaces it. Roadmap Phase 5 ships both. [current-2026]"""},
# =============================================================== editor
{"domain": "editor-tech", "title": "Undo/redo command stacks in editors",
 "keywords": "undo redo command pattern history editor memento",
 "body_md": """Pattern for our canvas (Phase 1): Command pattern - every mutation is an object {do(), undo(), label}; two stacks (undo/redo) + coalescing windows (drag = one command per gesture via pointerup commit; slider = commit on change-end).

Rules learned the hard way: undo must restore SELECTION and scroll too; store commands, not full snapshots (memory), except layer-delete which snapshots the subtree; cap stack at ~200 steps; clear redo stack on new mutation; persist nothing across app restarts (autosave journal is a separate, coarser safety net at 10s intervals + on blur).

Test contract: property-test random mutation sequences against a snapshot oracle (serialize-project equality after do+undo). [core]"""},

{"domain": "editor-tech", "title": "Blend modes & adjustment math",
 "keywords": "blend multiply screen overlay opacity composite formula css ffmpeg",
 "body_md": """Per-layer blend modes, canvas AND export parity:
- normal(N), multiply(N*B), screen(N+B-NB), overlay(B<.5?2NB:1-2(1-N)(1-B)), soft-light, difference(|N-B|), lighten/darken(min/max)
- CSS implements all (mix-blend-mode) for live view; ffmpeg mirrors via `blend=all_mode=multiply` on padded inputs - parity is testable: render single-frame mp4, decode, compare to canvas raster within tolerance.

Adjustment layers (applied to composite below them): brightness/contrast (CSS filter / ffmpeg eq), hue-rotate/saturate (hue/saturation filters), vignette, film grain (noise filter, seeded for determinism).

Implementation order: modes as canvas 2d globalCompositeOperation (free), adjustments as SVG filter chains mirrored to ffmpeg eq strings. [core]"""},

{"domain": "editor-tech", "title": "Keyframes & easing for motion",
 "keywords": "keyframes easing bezier timeline animation tween",
 "body_md": """Timeline engine core: track = list of {time, value, ease} keys; evaluator lerps between keys with easing fn. Standard easings: linear, sine/quad/cubic in-out, back(overshoot), bounce, expo. Bezier easing (css cubic-bezier syntax) covers 90% of pro feels.

Tracks per layer: x,y,scaleX/Y(uniform toggle),rotation,opacity + effect params (blur,vignette strength). Playback: rAF loop mapping playhead->evaluator->style writes (GPU-cheap: transforms+opacity only).

Export parity: sample evaluator at fps grid -> per-frame transform values -> either frame-sequence render (canvas rasterizer) OR expr-driven ffmpeg filters (zoompan/rotate with expressions) for simple moves; complex nests fall back to frame-sequence + NVENC. Determinism: sample times = integer frame indices, never accumulated time. [core]"""},
# ============================================================= prompting
{"domain": "prompting", "title": "A1111 prompt grammar & wildcards",
 "keywords": "prompt grammar weights alternating wildcard a1111 syntax",
 "body_md": """De-facto standard grammar to parse into conditioning emphasis:
- `(word)` = 1.1x, `(word:1.35)` explicit, `((word))` multiplicative
- `[a|b]` alternate each step; `[a:b:0.4]` switch at 40% steps
- `BREAK` splits chunked encoding (helps regional setups)
- wildcards: `__color__` expanded from a library file at submit-time (record expansion IN the manifest for reproducibility!)

Parser lives prompt-side (pure JS in renderer + python mirror in engine for API users); output = normalized prompt string + emphasis tree the graph builders flatten into plain text (ComfyUI CLIPTextEncode accepts the raw A1111 syntax natively for weights - parser mainly serves wildcards, alternation and UI affordances).

Negative prompts are first-class citizens: maintain house default negative sets per tier (photography/anime/product) selectable in Generate panel. [core]"""},

{"domain": "prompting", "title": "XYZ sweeps: choosing takes like a photographer",
 "keywords": "xyz grid sweep seed steps cfg comparison batch contact sheet",
 "body_md": """Batch exploration: fix a prompt, sweep axes (seed x cfg x steps x lora-weight x sampler) -> contact-sheet grid with axis labels burned in.

Implementation: queue submits N jobs (serial GPU anyway), gallery assembles grid via ffmpeg tile filter with drawtext labels; click-through reopens any cell's full params (result-cache keys make cells free to revisit).

Methodology: coarse pass (cfg 4-9 x seeds) -> refine winner (steps +/-, hires on) -> lock recipe into project. Riley director-mode automates the coarse pass and narrates picks. [core]"""},
# ============================================================ automation
{"domain": "automation-ops", "title": "Watch folders & headless rendering",
 "keywords": "watch folder automation cli headless batch render queue",
 "body_md": """Hands-free operations on the kinema pattern:
- **Watch folders**: config roots polled on interval; new files trigger recipes (auto-upscale drops, auto-caption footage, auto-posterize stills). Events land in events.jsonl; quarantine folder catches poison inputs so one bad file never wedges the loop.
- **Headless CLI**: `python -m riley_studio render project.rsproj --preset reel --out D:/exports` - boots engine in-proc, executes export spec, exits nonzero on failure. CI-able; scheduled-task-able (register-*-task.ps1 conventions exist).
- **LAN render node** (deferred, opt-in): same server binary bound to the LAN interface WITH an explicit operator override env + token auth; loopback stays the default law. [core][current-2026]"""},
]

assert isinstance(EXPANSIONS, list) and len(EXPANSIONS) >= 30
