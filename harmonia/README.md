# HARMONIA — normalized studio viewer

Companion to APHRODITE. Where APHRODITE browses the library *as it is*,
HARMONIA presents every finding in a **standard viewing format**: JPG /
PNG / GIF for images, MP4 / WebM for video. What you see is what any
device, browser and photo app opens without a fight.

Private, offline, one folder (`D:\new` by default), Python stdlib only —
zero pip dependencies, zero telemetry, zero network egress. Not wired
into any other realm.

## Quickstart

```
harmonia\launch_harmonia.bat "D:\new"     # serves http://127.0.0.1:43907
```

or manually:

```
python harmonia\server.py --root "D:\new" --port 43907 --open
```

## The normalization contract

| Source | Becomes | How |
|---|---|---|
| `.bmp` `.tif` `.tiff` `.webp` `.avif` `.heic` `.heif` | JPG (alpha → PNG) | Windows GDI+ decode/re-encode, EXIF orientation baked in |
| `.jfif` | JPG | lossless byte-copy rename |
| `.mkv` `.mov` `.avi` `.ogv` with safe streams | MP4 | ffmpeg **remux** (`-c copy`, `+faststart`) — instant, no re-encode |
| videos with exotic codecs | MP4 H.264/AAC | ffmpeg **transcode** (`veryfast`, CRF 20) |
| already-standard files | themselves | byte-identical passthrough, never re-encoded |

Tool discovery order: `--tools-dir` flag → `harmonia\bin\` →
`aphrodite\bin\` (shared vendor drop) → `PATH`. Without ffprobe/ffmpeg,
video findings degrade honestly: served as-is and flagged non-std; image
normalization is unaffected (GDI+ is in-process).

Normalized artifacts live under
`%LOCALAPPDATA%\HARMONIA\norm-<roothash>\`, mirroring the library tree.
Artifact names embed a hash of source path+mtime+size, so an edited
source can never be masked by a stale copy. The media root itself stays
byte-read-only — always.

## Flags

| Flag | Meaning | Default |
|---|---|---|
| `--root DIR` | the single folder to view | current directory |
| `--host HOST` | bind address | `127.0.0.1` (keep loopback) |
| `--port N` | listen port (`0` = ephemeral) | `43907` |
| `--show-hidden` | include dot-hidden entries | off |
| `--tools-dir DIR` | where ffmpeg/ffprobe live | auto-discovery |
| `--open` | launch browser after binding | off |
| `--quiet` | suppress request log | off |

## HTTP API

| Route | Returns |
|---|---|
| `GET /` | the SPA (inline assets only) |
| `GET /api/info` | `{app, version, root_name, root, norm_dir, tools{ffmpeg,ffprobe,gdi}}` |
| `GET /api/tree?dir=REL` | findings for one folder; each file carries `{path, kind, fmt, std, size, mtime}` |
| `GET /api/all?cap=N` | recursive findings index (default cap 20 000, `truncated` flag) |
| `GET /api/dirs` | every visible directory, recursively |
| `GET /api/file?f=REL&v=1&k=kind` | **the viewing bytes**: normalized artifact when needed, original otherwise (`v=0` = raw provenance bytes) |
| `GET /api/thumb?f=REL&s=PX` | cached JPEG thumbnail of the *viewing* source |
| `GET /api/build` | worker status `{queued, running, done, failed, failures[]}` |
| `POST /api/build` | enqueue a full-library normalization pass (only writable route; touches LOCALAPPDATA only) |

Findings semantics: `fmt` is the source extension; `std` says whether the
file as-is already plays everywhere. The UI badge shows the format you
actually get (`viewOf`) plus a `✓norm` marker on converted items.

## Verify

```
python verify_harmonia.py
```

Boots against a throwaway fixture and runs 22 checks: containment
(plain/encoded/absolute traversal, hidden, non-media — on file, thumb and
norm views alike), JSON contract, method policy (405 everywhere except
`POST /api/build`), byte fidelity for originals and standard passthroughs,
real GDI+ BMP→JPEG normalization, JFIF lossless rename, thumbnail-from-
normalized-source, artifact placement under LOCALAPPDATA with the media
root verified pristine, codec-aware std flags via ffprobe, and — when the
vendored ffmpeg is present — a true MKV→MP4 remux end-to-end plus
graceful fallback for undecodable input. Exits non-zero on any failure.

## Security / privacy model

1. Loopback bind only; no egress.
2. Library read-only: writes exist solely on `POST /api/build` and mutate
   only HARMONIA's own LOCALAPPDATA store.
3. One-root confinement through `MediaLibrary.resolve()` (drive letters,
   `..`, symlink escapes rejected) guarding `/api/file`, `/api/thumb`
   *and* both `v=1` normalized views.
4. Content-blind listing; dot-files excluded unless `--show-hidden`.
5. JSON contract `{"ok", "error", "data"}` on every response.

## Port registration (pending operator approval)

`:43907` chosen deliberately: ptah=43903, aphrodite=43904,
daedalus=43905, and `:43906` is the known rogue listener from cycle
2026-08-24-1138. Registry row can mirror aphrodite's once approved.

## Roadmap

- **P1 (shipped)** — normalization engine (GDI+ images, ffmpeg
  remux/transcode), findings schema (`fmt`/`std`), build queue with live
  progress, badges + lightbox conversion notes.
- **P2 (candidate)** — orphan sweep for stale artifacts, per-folder
  selective builds, audio-file support, duration badges via ffprobe.
