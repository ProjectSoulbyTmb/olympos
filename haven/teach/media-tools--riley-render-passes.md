# Create from it - RILEY render passes over library refs
keywords: riley render refs cinemagraph upscale filter gif artgen chain batch kits 43907 generated
RILEY (`D:\riley`, http://127.0.0.1:43907) mounts `D:\new` read-only as her ref-root and writes finished work to `D:\new\generated\<asset>` plus a `<asset>.riley.json` provenance sidecar (prompt/seed/module/engine recorded at birth). APHRODITE picks new work up automatically through that filesystem seam.

Browsing refs: GET `/api/reflist` (capped 5000), `/api/ref?f=REL` (ranged bytes), `/api/thumb?f=REL&s=PX` (cached JPEG).

Render passes over library stills/clips:
- `vid.animate` - ken-burns cinemagraph from any library still.
- `img.upscale` - lanczos x2-x4. `img.filter` - color grades: warm/cool/fade/noir/vivid/vignette.
- `vid.gif` - palette-tuned looping GIF from any clip (fps 5-30, width clamp, dur trim).
- `img.art` / `vid.art` - seeded generative art incl. nine artgen styles: attractors, flowfield, truchet, guilloche, strata, moire, phyllotaxis, voronoi, murmuration. Byte-identical re-render per (style, seed, size).
- Batch `count=N` (1-32) fans one job into deterministic variants; chains (2-8 steps, JSON body POST /api/jobs) pipe steps forward - a step without `ref` inherits the previous output (e.g. img.art -> img.upscale -> img.convert webp). Kits (`/api/kits` CRUD) store reusable param bundles.
Queue with POST `/api/jobs?kind=...`, poll `/api/job?id=`; introspect `/api/kern`. ML diffusion modules stay parked on this 4 GB GPU; the CPU render engine is fully live.
