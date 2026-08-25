# Library census - 2026-08-25 refresh
keywords: d:\new library census folders tags size duplicates generated quarantine
Ground truth from `ingest/media_scanner.py --sniff --dedupe`, generated 2026-08-25T11:50Z, after the duplicate cleanup.

TOTALS: 8,879 media files, 272.1 GB.
Mix: .jpg 8,583, .mp4 226, .png 62, .gif 4, .webp 4.
Filename tags: tattoo 99, feet 42, bdsm 32, pmv 28, latex 20, goth 12.
Integrity: video_audit --all --fix (2026-08-25) quarantined all 6 duplicate videos; zero problems and zero duplicate groups remain in the live library.

SHAPE:
- Loose files at the root: 172 items, 208.7 GB - mostly `EPORNER.COM - [id] Title (res).mp4` downloads; largest single file ~9 GB.
- `pics\` = 526 files, 60.7 GB (second-largest block).
- OnlyFans WEBDL photo sets: Hazel Madison (746), Tihomirova Natali (965), Evessfeet (848).
- Curated scrapes: babesource-{feet,goth,tattoo}, imagefap-{emo,goth,tattoo}-feet families, pornpics-{feet,goth,tattoo}, dbnaked-<model>-{pics,tube} (riley-reid, piper-perri, joanna-angel, kleio-valentien, draven-star, rocky-emerson, charlotte-sartre, leigh-raven + model-clone/tattoo/feet aggregates), burningangel-{pics,tube}, auto-pictures/auto-tube bdsm+alt families, ExposedRussianGFs + HawtTVGirls image sets.
- `generated\` = RILEY's drop zone: 62 PNG each with a `.riley.json` provenance sidecar (newest: artgen phyllotaxis/murmuration/strata/truchet/voronoi/moire/attractors/flowfield renders, morning of 2026-08-25).
- `_audit_quarantine\` = 7 files, 8.78 GB, held for operator review (never auto-deleted): one legacy hold + the six duplicates moved by `video_audit --fix` on 2026-08-25 (`1080 (1)/(2).mp4` partial re-downloads, Edging/Hotel-Room/PMVHQ `(1)` clones, `pics\` twin of 4K Female Finishes Part 4). Deleting these frees the 8.78 GB - operator's call only.

LARGEST FILES: Wet Dreams AI Cock Hero 2160p 9.01 GB; Ultimate Compilation 1080p 8.07 GB; Horny Brunette Secretary 2160p 5.80 GB; BS Katie 2160p 5.67 GB; Delilah Dagger Downward Doggy 2160p 5.31 GB.

Artifacts beside the media: `_media_index.json` (file-level index), `_video_audit.json` (integrity+dupes), `_ingest_catalog.json` (download sources), `_riley_find.json` (web-search report), `ingest.log`, `run_ingest.bat`.

Refresh after any change: `python ingest/media_scanner.py --root D:\new --sniff --dedupe`
