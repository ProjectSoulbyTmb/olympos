# Query skills - media_scanner recipes
keywords: media_scanner find tags dedupe sniff largest index recipes filtered partial index lesson
Riley's offline indexer: `python ingest/media_scanner.py --root D:\new [flags]`. Writes `_media_index.json` with file-level records (path, folder, kind, bytes, mtime, magic_ok, res, hd, tags).

Recipes:
- Full verified pass (the canonical refresh): `--sniff --dedupe` - magic-byte validation cached against unchanged mtimes; clone groups via head+tail sample digests within the `--max-hash-gb` budget.
- By name regex: `--find "pmv.*1080"` or `--find "cock hero"`.
- By tag (any-of): `--tags feet,goth` - known tags: pmv goth feet tattoo bdsm alt latex.
- Biggest/newest: read the saved index's `largest` / `newest` blocks; the CLI prints the first 25 rows.
- Query without touching the master index: append `--no-index`.

CRITICAL house lesson (learned 2026-08-24): a FILTERED run (`--find`/`--tags`) saves only the matched subset into `_media_index.json`. The master index was once left partial that way (892 of ~9.7k records). After any filtered query, re-run a FULL scan (no filters) to restore the complete index before teaching or auditing from it.
