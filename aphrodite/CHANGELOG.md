# Changelog

## v0.5.0-muse - 2026-08-24

### Added
- **Ratings** (`/api/rate`) - 0-5 stars per file, app-side
- **Tags** (`/api/tag`, `/api/tags-index`) - lowercased 1-48 chars,
  reverse index endpoint
- **Boards** (`/api/boards`) - ordered moodboards with live-stat detail,
  dead-entry pruning, and `/api/board/export?b=ID` contact-sheet HTML
- **Smart albums** (`/api/smart`) - saved queries over kind / min-rating /
  tag, evaluated live against the library walk
- **Studio overlay** in the SPA - boards, smart albums and a client-side
  k-means palette extractor (canvas, click-to-copy hex)
- Fleet citizenship: registered tier 2 (:43904); DESIGN.md row;
  36-check gate (was 26)

### Notes
- Ratings/tags were completed from the P3 open list; boards/smart/palette
  are the muse layer. Library bytes remain untouched by every writable
  route.
