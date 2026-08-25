# Watch it - APHRODITE viewer, the primary browser for D:\new
keywords: aphrodite viewer gallery ratings tags boards slideshow continue-watching dupes export 43904
APHRODITE (`D:\aphrodite`) is the purpose-built offline viewer for `D:\new`. Launch: `aphrodite\launch_aphrodite.bat` -> http://127.0.0.1:43904 (loopback only, library read-only, content-blind serving).

Skills worth knowing:
- All-media mode with grid virtualization (smooth at ~20k items); lazy folder tree, breadcrumbs, hash-routed deep links; filter All/Photos/Videos; sort name/date/size/shuffle; live substring filter.
- Lightbox: wheel/+/- zoom, drag pan, R rotate, 0 reset, F fullscreen, I info panel, space play/pause. Slideshow on S (videos advance at playback end). Arrows/Home/End/Esc navigate; `?` shows help.
- Ratings (keys 1-5) + tags typed in the lightbox; filter by min-rating dropdown or tag chips (T). Ctrl-click / Shift-click multi-select -> floating bulk bar (fav/unfav/rate/tag). Continue-watching persists positions every few seconds and resumes with tile progress bars.
- Duplicate finder button (size prefilter + head/tail hashing) and command palette Ctrl+K or / (fuzzy jump to any folder/file plus slideshow/size/dupes commands).
- Universal playback `/api/stream?f=REL&t=S`: native stream or on-the-fly ffmpeg transcode of non-browser codecs; sidecar subtitles `/api/subs` (.srt converted to .vtt); mini-EXIF via `/api/meta`.
- Export jobs: POST `/api/export?f=REL&mode=frame|clip|audio|image`, poll `/api/export?id=`; output lands in `%USERPROFILE%\AphroditeExports`.
- Studio overlay extras: boards, smart albums, contact-sheet export, client-side palette extractor; API rows /api/boards, /api/smart, /api/tags-index, /api/dupes.
Ratings/tags/positions state lives in `%LOCALAPPDATA%\APHRODITE\state\state-<roothash>.json` - media bytes are never modified. Gate: `python verify_aphrodite.py` (51 checks).
