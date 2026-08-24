# APHRODITE — standalone offline studio media viewer

Local photo + video viewing kernel for **one folder** (`D:\new` by default).
Private, offline, library-read-only. Python stdlib only — zero pip
dependencies, zero telemetry, zero network egress. Not wired into any other
realm. Thumbnails bind Windows GDI+ in-process via `ctypes` (still stdlib).

## Quickstart

```
aphrodite\launch_aphrodite.bat          # serves D:\new on http://127.0.0.1:43904
```

or manually:

```
python aphrodite\server.py --root "D:\new" --port 43904 --open
```

Stop with Ctrl+C (or close the console window).

## Flags

| Flag | Meaning | Default |
|---|---|---|
| `--root DIR` | the single folder to view | current directory |
| `--host HOST` | bind address | `127.0.0.1` (keep loopback) |
| `--port N` | listen port (`0` = ephemeral, used by tests) | `43904` |
| `--show-hidden` | include dot-hidden entries | off |
| `--open` | launch browser after binding | off |
| `--quiet` | suppress request log | off |

## Features

- Folder tree sidebar (lazy), breadcrumb navigation, **All-media** library-wide mode
- Responsive grid, lazy-loaded thumbnails, video tiles with duration badges
- Lightbox: zoom (wheel / `+` `-`), pan (drag), rotate (`R`), reset (`0`),
  fullscreen (`F`), info panel (`I`), native video controls, space play/pause
- Slideshow (`S`) with wrap-around; videos advance on playback end
- Filter All / Photos / Videos · sort by name/date/size · live substring filter
- Keyboard: `←` `→` `Home` `End` `Esc`; hash-routed folders (deep-linkable)

## Security / privacy model

1. **Loopback bind** — reachable only from this machine.
2. **Library read-only** — GET/HEAD serve content; PUT/PATCH always 405.
   POST/DELETE exist *only* on `/api/fav` and mutate solely APHRODITE's own
   favorites JSON under LOCALAPPDATA — never a byte of the media tree.
3. **One-root confinement** — every path resolves through
   `MediaLibrary.resolve()`: drive-letter/UNC forms rejected, `..` rejected,
   realpath must stay under root (symlink/junction escape caught).
   The same containment guards `/api/thumb` and `/api/fav`.
4. **Content-blind** — every media file under the root is listed and served;
   there is deliberately *no* content-level filtering of any kind.
   Hidden dot-files are excluded unless `--show-hidden`.
5. **JSON contract** — every JSON response carries `{"ok", "error", "data"}`;
   failures are structured, never partial HTML.

## HTTP API

| Route | Returns |
|---|---|
| `GET /` | the SPA (`index.html`, inline assets only) |
| `GET /api/info` | `{app, version, root_name, root}` |
| `GET /api/tree?dir=REL` | immediate `{dirs[], files[]}` of one folder |
| `GET /api/all?cap=N` | recursive media index (default cap 20 000, `truncated` flag) |
| `GET /api/file?f=REL` | bytes; single RFC7233 `Range` supported (video seeking) |
| `GET /api/thumb?f=REL&s=PX` | cached JPEG thumbnail (64–1024 px box); falls back to original if GDI+ can't decode (SVG, AVIF…) |
| `GET /api/meta?f=REL` | mini-EXIF dict for JPEGs; `{}` otherwise |
| `GET /api/fav` | favorite list with live stat data |
| `POST /api/fav?f=REL` | add to favorites (only writable route) |
| `DELETE /api/fav?f=REL` | remove from favorites |

## Verify

```
python verify_aphrodite.py
```

Boots the server against a throwaway fixture and runs 26 checks: containment
(`..`, encoded `%2e%2e`, absolute paths, hidden files, non-media — on
`file`, `thumb` and `fav` alike), range serving (206/suffix/416), method
policy (405 everywhere except the fav round-trip), JSON error contract,
tree/all/thumb/meta listings, exact byte fidelity, HEAD behavior, and a full
favorites add/list/remove cycle (app-state scrubbed afterwards). Exits
non-zero on any failure.

## Port registration (pending operator approval)

`:43904` chosen as the free fleet slot (ptah=43903, daedalus=43905).
Per the "not connected to any other trees" constraint, APHRODITE is **not**
registered in `realms/registry.json` yet — registration would place it under
sentinel/doctor gating. Ready-to-apply row when desired:

```json
{
  "name": "aphrodite",
  "kind": "viewer",
  "engine": "studio-media-viewer",
  "port": 43904,
  "sdk": null,
  "path": "aphrodite/server.py",
  "tier": 2,
  "lang": "python",
  "verify": ["python", "verify_aphrodite.py"],
  "profile": "watcher"
}
```

## Roadmap

- **P1 (shipped)** — browse/view/filter/slideshow/range-streaming, confinement.
- **P2 (shipped, v0.2.0)** — GDI+ thumbnails with EXIF-orientation handling
  and disk cache (`%LOCALAPPDATA%\APHRODITE\thumbs-<roothash>\`; measured
  0.55 s cold → 0.005 s warm on a 32 MB GIF); mini-EXIF info panel
  (camera/taken/exposure/f-number/ISO/focal/pixels — pure-python TIFF walk);
  ★ favorites (keyboard `K`, persisted under
  `%LOCALAPPDATA%\APHRODITE\state\`, dead entries auto-pruned).
- **P3 (partial, v0.3.0)** — grid virtualization: every item renders a cheap
  fixed-size shell; real `<img>`/`<video>` nodes attach only within a
  ~900 px band around the viewport (IntersectionObserver on the scrollport)
  and recycle through a 256-entry LRU (evicted videos are fully unloaded).
  Live DOM stays near-constant while scrolling All-media at library scale.
- **v0.4.0** — ratings/tags/boards/smart albums ("Muse & Marble"), duplicate
  finder, stream/subtitle ingest (`/api/stream`, `/api/subs`) with codec
  safety sets and optional vendored ffmpeg in `bin\`.
- **v0.5.0 (normal formats)** — every finding now reports `fmt` (source
  format) and `std` (whether it already views everywhere) in `/api/tree`
  and `/api/all`; `GET /api/file?f=REL&norm=1` serves the *standard viewing
  form*: BMP/TIFF/WebP/AVIF/HEIC → JPG (alpha → PNG, EXIF orientation
  baked in) via GDI+, `.jfif` → JPG lossless rename, exotic-container
  videos → MP4 via bundled ffmpeg (`-c copy` remux when streams are already
  browser-safe, H.264/AAC transcode otherwise). Artifacts cache under
  `%LOCALAPPDATA%\APHRODITE\normalized-<roothash>\` keyed by a source
  fingerprint (path+mtime+size), so stale copies never mask edits. Already-
  standard files pass through byte-identical — never re-encoded. The
  lightbox requests `norm=1` automatically for non-std items and says so.
  Still open in P3+: packaging polish (spec present, rebuild pending).

## Known limits

- Browser decides codecs: `.mp4`(H.264/AAC), `.webm`, `.jpg`, `.png`,
  `.gif`, `.webp` play natively everywhere; `.mkv/.avi/.mov` depend on the
  browser build. Unsupported videos still stream but may not decode.
- Thumbnails: GDI+ decodes JPG/PNG/GIF/BMP (and WebP on Win10+); SVG/AVIF
  fall back to serving the original file for tiles. EXIF orientation is
  applied at thumbnail time; the lightbox shows originals untouched.
- `/api/all` caps at 20 000 entries per query (library here ≈ 6.9k — safe).
- Mini-EXIF covers common display tags only; files stripped of EXIF
  (common in downloaded sets) correctly report `{}`.
- Grid is virtualized: video-tile duration badges populate once a tile
  scrolls near the viewport, and off-screen tiles release their media
  nodes (re-attach on scroll-back is instant via the thumbnail cache).
- Normalization (`norm=1`): first view of a non-standard *video* runs
  ffmpeg synchronously — large MKV/AVI files take a while before playback
  starts, then come from cache. Without a usable ffmpeg (see below),
  videos keep original bytes; image normalization is unaffected.
- `bin\ffmpeg.exe` / `bin\ffprobe.exe` are a local vendor drop (~100 MB
  each) and deliberately **excluded from version control** by the repo's
  global `*.exe` ignore rule; fresh clones simply report ffmpeg missing
  and degrade gracefully. For a fully normalized video experience see
  also `harmonia\` (dedicated normalized viewer, async build queue).
