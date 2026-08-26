# How D:\new grows - ingest pipeline and catalog
keywords: ingest download catalog web_search run_ingest hd-only media_ingest
Three stdlib tools in the workspace repo feed and inspect the library.

1) DOWNLOADER - `ingest/media_ingest.py`. `D:\new\run_ingest.bat` wraps:
   `python ingest/media_ingest.py --discover --download --out D:\new --catalog D:\new\_ingest_catalog.json --hd-only >> D:\new\ingest.log`
   Source adapters are registered inside the tool (dbnaked model/site shapes, imagefap, etc.). `_ingest_catalog.json` tracks per-source `{dir, items, materialized, updated_at}`; runs are resumable, retries log to `ingest.log`; `.part` suffix marks incomplete downloads; `--hd-only` drops low-res.
2) FINDER - `ingest/web_search.py`, multi-engine adult media search:
   `python ingest/web_search.py "goth feet" --engine all --kind any`
   Writes `_riley_find.json` (query, engines, totals, ranked hits). Last run: query "goth feet" -> eporner returned 15 candidates.
3) SHAPE CLONE for a new model/site without hand-editing registry code:
   `python ingest/media_ingest.py --clone-source dbnaked-riley-reid-tube --as <new-name> --set-path "/models/general/O/Other-Model"`

House rules: everything lands in per-source folders under `D:\new`; nothing outside that root is written; after any download burst re-run the full scanner so `_media_index.json` stays truthful.
