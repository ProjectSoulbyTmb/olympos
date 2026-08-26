# Integrity skills - video_audit and duplicate policy
keywords: video_audit integrity duplicates quarantine fix truncation clones policy
`python ingest/video_audit.py --root D:\new [--all | --categories pmv,goth,feet] [--fix]`
Checks container magic bytes, zero-byte/truncation heuristics, resolution tags from filenames. Duplicate detection: sha256 for equal-size files up to 256 MB, head+tail sample digests above that ("content-sampled"), plus name-twin matching for `(1)`-style suffixes.

Latest verdict (2026-08-25, `--all`, report in `D:\new\_video_audit.json`): 232 videos scanned, zero corruption; 6 duplicate files across 5 groups:
- `1080.mp4` vs `1080 (1).mp4` vs `1080 (2).mp4` - name twins.
- Edging Compilation (1080) + its `(1)` copy - content-sampled clones, ~1.13 GB each.
- In Hotel Room With Two Amazing Girls - content-sampled clone pair, ~1.03 GB each.
- PMVHQ Compilation Vol.1 (1080) `(1)` - name twin.
- 4K Female Finishes Part 4 (2160) - name twin.

POLICY: `--fix` never deletes; it moves problem files into `D:\new\_audit_quarantine\` and keeps the canonical copy in place. The quarantine currently holds one 3.56 GB file awaiting operator review. Deleting true duplicates would free several GB but stays an operator decision, not an automation default.
