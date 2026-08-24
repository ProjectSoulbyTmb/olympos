"""watcher - folder-feed loop: new/changed videos flow into the studio.

Reads data/kinema/watch.json:
  {"roots": ["D:\\my-footage"], "interval": 60,
   "catalog": "data/kinema/catalog.json", "samples": "data/kinema/samples"}

Each cycle: find videos, analyze unseen ones into the learning
catalog, extract preview frames per video into samples/, and append a
line to data/kinema/events.jsonl. Fully local; no network.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kinema import DATA_DIR  # noqa: E402

from analysis import analyze_folder  # noqa: E402

DEFAULT_CONFIG = {
    "roots": [],
    "interval": 60,
    "catalog": None,
    "samples": None,
}


def config_path():
    return os.path.join(DATA_DIR, "watch.json")


def load_config():
    path = config_path()
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(config_path(), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)


def _events_path():
    return os.path.join(DATA_DIR, "events.jsonl")


def log_event(kind, payload):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_events_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "kind": kind, **payload}) + "\n")


def sample_videos(videos, samples_dir, count=6):
    """Preview frame extraction for the visual index."""
    from analysis import extract_frames
    written = {}
    for vid in videos:
        tag = "%016x" % (abs(hash(os.path.abspath(vid).lower())) %
                         (1 << 64))
        dest = os.path.join(samples_dir, tag)
        try:
            frames = extract_frames(vid, dest, count=count)
            if frames:
                # keep only the first; the folder is the preview set
                written[vid] = dest
        except Exception:  # noqa: BLE001 - previews are best effort
            continue
    return written


def run_once(cfg=None, do_samples=True):
    """One sweep across all roots. Returns summary dict."""
    cfg = cfg or load_config()
    catalog = cfg.get("catalog") or os.path.join(DATA_DIR, "catalog.json")
    samples = cfg.get("samples") or os.path.join(DATA_DIR, "samples")
    roots = [r for r in (cfg.get("roots") or []) if r and
             os.path.isdir(r)]
    summary = {"roots_scanned": len(roots), "results": []}
    from analysis import Catalog, find_videos
    cat = Catalog(catalog)
    pending = [v for root in roots for v in find_videos(root)
               if not cat.has_current(v)]
    for root in roots:
        result = analyze_folder(root, catalog_path=catalog,
                                log=lambda m: print("[kinema]", m))
        summary["results"].append(result)
    if pending and do_samples:
        previews = sample_videos(pending, samples)
        if previews:
            log_event("samples", {"videos": list(previews)})
    if summary["results"]:
        log_event("sweep", {k: v for k, v in summary.items()
                            if k != "results"})
    return summary


def watch(interval=None):
    """Continuous guard-loop sweep."""
    while True:
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001 - never die
            log_event("error", {"error": str(exc)[:300]})
        time.sleep(max(int(interval or load_config().get("interval", 60)),
                       5))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="folder-feed watcher")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=None)
    args = ap.parse_args()
    if args.once:
        print(json.dumps(run_once(), indent=1))
    else:
        watch(args.interval)
