# ROADMAP — Riley Studio → professional AI video/imagine suite

Status: proposed, phased. Each phase ships independently, gates green
before the next starts. Companion audit: chat 2026-08-24; consumer of
this file: muse-db curriculum (topic domain `roadmap`).

## Phase 1 — Editor foundations (pure JS, low risk)
Undo/redo command stack; autosave + crash-recovery journal; blend modes
per layer; adjustment layers (curves/HSL/vignette/grain); mask brushes
(dual-duty as inpaint masks); bezier pen + snapping/guides/groups.
Acceptance: undo covers every mutation; crash-kill mid-edit reopens with
<=30s loss; node tests + boot smoke green.

## Phase 2 — Control & consistency
A1111 prompt grammar ((word:1.3), [alt], wildcards); ControlNet graphs
(depth/pose/canny/tile, Q4) with canvas preview; LoRA manager with
trigger-word index; inpaint-from-canvas-mask round trip; IP-Adapter on
SD1.5 tier. Acceptance: pose-guided render matches skeleton within
tolerance; same seed+grammar byte-stable across runs.

## Phase 3 — Sound & captions
Piper TTS narration track; whisper.cpp transcription -> subtitle track +
.srt sidecar; music-bed library folder (CC0); audio clips in timeline;
NVENC-aware mux. Acceptance: narrated reel exports end-to-end offline.

## Phase 4 — Video mastery
Keyframe engine (pos/scale/rot/opacity/easing per track, scrubbable
playhead); NVENC encoder path (GTX 1650 has it); RIFE frame
interpolation to 60fps; transition library beyond xfade; .cube LUT
support; ProRes-master + web-derivative delivery ladders. Acceptance:
16fps gen -> smooth 60fps deliverable; export time dominated by NVENC.

## Phase 5 — Provenance & cache
Replay manifests (model sha + workflow hash + params per output);
hash-addressed result cache; C2PA content credentials on exports;
license ledger enforced before gated pulls. Acceptance: replay of any
gallery item reproduces pixel-identical output on same hardware.

## Phase 6 — Director mode & automation
XYZ sweep grids; Riley storyboard->reel pipeline (brief -> shot grid ->
picks -> assembled reel); watch folders; headless CLI
`python -m riley_studio render project.rsproj`; optional LAN render node
(loopback default preserved).

## Hardware ceiling note
4GB GPU tier: SD1.5 / SDXL-Q4 / Flux-Q4 images, LTX-distilled micro
clips. Wan 2.2 / SD3.5-large / HunyuanVideo / SUPIR require 8-12GB+.
Recommended unlock: RTX 3060 12GB class card.
