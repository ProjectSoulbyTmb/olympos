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
- **Grid virtualization** — shells render eagerly, real media attaches only
  near the viewport via IntersectionObserver + a 256-entry LRU recycle;
  All-media scrolling stays smooth at 20k-item scale
- **Ratings (★1–5) + tags** — set in the lightbox (click stars / type tags,
  `1`–`5` keys); filter by min-rating dropdown or tag chips (`T`)
- **Continue-watching** — video positions persist every few seconds;
  reopening resumes with a toast; finished videos clear automatically;
  started videos show a progress bar on their tile
- **Multi-select & bulk actions** — Ctrl+click toggles, Shift+click ranges,
  bulk fav/unfav/rate/tag from the floating action bar
- **Duplicate finder** (`⧉ Dupes`) — size prefilter + head/tail hashing,
  time-budgeted, groups ranked by wasted bytes, click-through to lightbox
- **Command palette** (`Ctrl+K` or `/`) — fuzzy jump to any folder/file,
  plus slideshow/size/dupes/help commands
- **Hover video preview**, seeded **Shuffle** sort, S/M/L/XL tile sizes
  (persisted), keyboard help (`?`)
- Lightbox: zoom (wheel / `+` `-`), pan (drag), rotate (`R`), reset (`0`),
  fullscreen (`F`), info panel (`I`), native video controls, space play/pause
- Slideshow (`S`) with wrap-around; videos advance on playback end
- Filter All / Photos / Videos · sort by name/date/size/shuffle · live substring filter
- Keyboard: `←` `→` `Home` `End` `Esc`; hash-routed folders (deep-linkable)

## Security / privacy model

1. **Loopback bind** — reachable only from this machine.
2. **Library read-only** — GET/HEAD serve content; PUT/PATCH always 405.
   POST/DELETE exist *only* on the app-state routes (`/api/fav`, `/api/rate`,
   `/api/tag`, `/api/pos`, `/api/bulk`) and mutate solely APHRODITE's own
   state JSON under LOCALAPPDATA — never a byte of the media tree.
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
| `GET /api/dirs` | every visible directory under root, recursively, sorted |
| `GET /api/file?f=REL` | bytes; single RFC7233 `Range` supported (video seeking) |
| `GET /api/thumb?f=REL&s=PX` | cached JPEG thumbnail (64–1024 px box); falls back to original if GDI+ can't decode (SVG, AVIF…) |
| `GET /api/meta?f=REL` | mini-EXIF dict for JPEGs; `{}` otherwise |
| `GET /api/state` | live pruned app state: `{favorites, ratings, tags, positions}` |
| `GET /api/fav` | favorite list with live stat data |
| `POST /api/fav?f=REL` | add favorite (writable surface) |
| `DELETE /api/fav?f=REL` | remove favorite (writable surface) |
| `POST /api/rate?f=REL&v=N` | rate 0–5 (`v=0` clears); bad `v` → 400 |
| `POST /api/tag?f=REL&t=NAME` | add tag (idempotent); name validated → else 400 |
| `DELETE /api/tag?f=REL&t=NAME` | remove one tag |
| `POST /api/pos?f=REL&sec=S` | save video watch position (videos only) |
| `DELETE /api/pos?f=REL` | clear watch position (finished) |
| `POST /api/bulk?op=…&f=…&f=…` | batch fav/unfav/rate/tag/untag, ≤500 files; all-or-nothing — any invalid path aborts with no writes |
| `GET /api/dupes?minsize=N` | duplicate groups (size + head/tail digest), time-budgeted, `partial` flag |

App-state storage: `%LOCALAPPDATA%\APHRODITE\state\state-<roothash>.json`
(one file per library root). Pre-0.4 `favorites-<key>.json` files are
imported automatically on first load and left untouched.

## Verify

```
python verify_aphrodite.py
```

Boots the server against a throwaway fixture and runs 38 checks: containment
(`..`, encoded `%2e%2e`, absolute paths, hidden files, non-media — on
`file`, `thumb` and `fav` alike), range serving (206/suffix/416), method
policy (405 everywhere except the app-state write routes; DELETE limited to
fav/tag/pos), JSON error contract, tree/all/dirs listings, exact byte
fidelity, HEAD behavior, a favorites round-trip, rating/tag/position
round-trips incl. 400-validation paths, bulk atomicity (one bad path aborts
the whole batch), and duplicate detection on an exact-copy fixture. Exits
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
- **P3 (complete, v0.4.0)** — ratings, tags, watch positions, bulk ops,
  duplicate finder, command palette, hover previews, shuffle, tile sizes.
- **Packaging (v0.4.1)** — PyInstaller onefile `Aphrodite.exe` (~80 MB,
  bundles `index.html` + GDI+ helper binaries); rebuild with
  `python -m PyInstaller Aphrodite.spec --noconfirm` from `aphrodite/`.
  Smoke-tested: boots, serves `/api/info` contract and full index.

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
- Duplicate finder fingerprints head+tail 64 KB per same-size candidate
  (not full files) — exact-size + digest collisions are theoretically
  possible; treat results as high-confidence candidates, not proof.
- Command palette's file index loads lazily and caps at 20 000 paths;
  libraries beyond that fall back to folder navigation.
- Watch positions are per-root app state: moving a library to a new path
  starts history fresh (favorites migrate by content of the old file only
  if it sat under the same root path).
