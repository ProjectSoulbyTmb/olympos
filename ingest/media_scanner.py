"""media_scanner - Riley's offline media scanner and library index.

Indexes every image and video under a root: magic-byte validation,
resolution tags from filenames, content tags (pmv/goth/feet/tattoo/
bdsm/alt/latex), per-folder rollups, largest/newest listings, regex
finder, and optional duplicate-clone detection (size groups -> head+tail
sample digest, bounded by --max-hash-gb). Zero network; writes a single
index JSON for fast follow-up queries.

Usage:
  python ingest/media_scanner.py --root D:\\new
  python ingest/media_scanner.py --root D:\\new --find "pmv.*1080"
  python ingest/media_scanner.py --root D:\\new --tags feet,goth
  python ingest/media_scanner.py --root D:\\new --largest 15 --dedupe
  python ingest/media_scanner.py --root D:\\new --sniff   # + magic check
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

APP = "media_scanner"
VERSION = "1.0"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}

TAG_PATTERNS = {
    "pmv": re.compile(r"\bpmv\b|cock\s?hero", re.I),
    "goth": re.compile(r"goth", re.I),
    "feet": re.compile(r"\bfeet\b|foot(?!ball|age)|\bsoles?\b|\btoes?\b",
                       re.I),
    "tattoo": re.compile(r"tattoo|inked|\bpierc", re.I),
    "bdsm": re.compile(r"bdsm|bondage|\bfemdom|bound", re.I),
    "alt": re.compile(r"\bemo\b|\bpunk\b|alternative", re.I),
    "latex": re.compile(r"latex|rubber", re.I),
}

RES_RE = re.compile(r"\((2160|1440|1080|720|480)\)")
HD_RES = {2160, 1440, 1080, 720}

SAMPLE_BYTES = 1024 * 1024
QUARANTINE_NAME = "_audit_quarantine"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def tags_for(name):
    return [t for t, rx in TAG_PATTERNS.items() if rx.search(name)]


def sniff_one(path, ext):
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    if ext in (".jpg", ".jpeg"):
        return head[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return head[:4] == b"\x89PNG"
    if ext == ".gif":
        return head[:4] in (b"GIF8",)
    if ext == ".bmp":
        return head[:2] == b"BM"
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext in VIDEO_EXTS:
        if ext in (".mp4", ".m4v", ".mov"):
            return len(head) >= 8 and head[4:8] == b"ftyp"
        if ext in (".webm", ".mkv"):
            return len(head) >= 4 and head[:4] == b"\x1aE\xdf\xa3"
        if ext == ".avi":
            return (len(head) >= 12 and head[:4] == b"RIFF"
                    and head[8:12] == b"AVI ")
    return True


def sample_digest(path):
    h = hashlib.sha256()
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        h.update(fh.read(SAMPLE_BYTES))
        fh.seek(max(0, size - SAMPLE_BYTES))
        h.update(fh.read())
    return h.hexdigest()


def load_prev_index(root):
    p = os.path.join(root, "_media_index.json")
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return {r["path"]: r for r in data.get("files", [])}
    except Exception:
        return {}


def scan(root, find_rx=None, tag_filter=None, dedupe=False,
         max_hash_gb=2.0, save_index=True, sniff=False):
    qname = QUARANTINE_NAME + os.sep
    files = []
    scanned = 0
    prev = load_prev_index(root) if sniff else {}
    for dirpath, dirs, names in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel.split(os.sep)[0].startswith("_audit_quarantine"):
            dirs[:] = []
            continue
        for n in sorted(names):
            ext = os.path.splitext(n)[1].lower()
            kind = ("image" if ext in IMAGE_EXTS else
                    "video" if ext in VIDEO_EXTS else None)
            if not kind:
                continue
            p = os.path.join(dirpath, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            scanned += 1
            if scanned % 1000 == 0:
                log(f"  ...{scanned} files indexed")
            res_m = RES_RE.search(n)
            res = int(res_m.group(1)) if res_m else None
            old = prev.get(p)
            if sniff:
                if old and old.get("mtime") == datetime.fromtimestamp(
                        st.st_mtime, timezone.utc).isoformat() \
                        and old.get("bytes") == st.st_size \
                        and old.get("magic_ok") is not None:
                    magic = old["magic_ok"]
                else:
                    magic = sniff_one(p, ext)
            else:
                magic = None
            rec = {
                "path": p, "folder": rel.split(os.sep)[0], "kind": kind,
                "ext": ext, "bytes": st.st_size,
                "mtime": datetime.fromtimestamp(
                    st.st_mtime, timezone.utc).isoformat(),
                "magic_ok": magic,
                "res": res, "hd": bool(res and res >= 720),
                "tags": tags_for(n),
            }
            if find_rx and not find_rx.search(n):
                continue
            if tag_filter and not set(rec["tags"]) & tag_filter:
                continue
            files.append(rec)

    dupes = []
    if dedupe:
        budget = max_hash_gb * 1024 ** 3
        by_size = {}
        for r in files:
            if r["bytes"] > 0:
                by_size.setdefault(r["bytes"], []).append(r)
        claimed = set()
        for size, members in sorted(by_size.items()):
            if len(members) < 2 or size * len(members) > budget:
                continue
            hashes = {}
            for m in members:
                try:
                    hashes.setdefault(sample_digest(m["path"]), []).append(m)
                except OSError:
                    continue
            for digest, same in hashes.items():
                if len(same) < 2:
                    continue
                same.sort(key=lambda m: (len(os.path.basename(m["path"])),
                                         os.path.basename(m["path"])))
                for m in same:
                    claimed.add(m["path"])
                dupes.append({"bytes": size, "hash": digest[:16],
                              "keep": same[0]["path"],
                              "dupes": [m["path"] for m in same[1:]]})
        for d in dupes:
            for path in d["dupes"]:
                m = next(x for x in files if x["path"] == path)
                m["dup_of"] = d["keep"]

    rollup_ext = {}
    rollup_folder = {}
    for r in files:
        rollup_ext[r["ext"]] = rollup_ext.get(r["ext"], 0) + 1
        f = r["folder"]
        e = rollup_folder.setdefault(f, {"files": 0, "bytes": 0})
        e["files"] += 1
        e["bytes"] += r["bytes"]
    tag_counts = {t: sum(1 for r in files if t in r["tags"])
                  for t in TAG_PATTERNS}
    index = {
        "app": APP, "v": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": root, "indexed": scanned, "matched": len(files),
        "total_bytes": sum(r["bytes"] for r in files),
        "by_ext": dict(sorted(rollup_ext.items(),
                              key=lambda kv: -kv[1])),
        "tags": tag_counts,
        "folders": dict(sorted(rollup_folder.items(),
                               key=lambda kv: -kv[1]["bytes"])),
        "duplicates": dupes,
        "largest": [{"path": r["path"], "bytes": r["bytes"]}
                    for r in sorted(files, key=lambda r: -r["bytes"])[:10]],
        "newest": [{"path": r["path"], "mtime": r["mtime"]}
                   for r in sorted(files, key=lambda r: r["mtime"],
                                   reverse=True)[:10]],
        "files": files,
    }
    if save_index:
        idx_path = os.path.join(root, "_media_index.json")
        tmp = idx_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, idx_path)
    return index


def show(index):
    log(f"indexed {index['indexed']} media files "
        f"({index['total_bytes'] / 1e9:.1f} GB), "
        f"{index['matched']} matched filters")
    log(f"by ext: {index['by_ext']}")
    log(f"tags: { {k: v for k, v in index['tags'].items() if v} }")
    for d in index["duplicates"][:10]:
        log(f"  ~~ clone x{len(d['dupes'])} ({d['bytes'] / 1e6:.0f} MB)"
            f" :: {os.path.basename(d['keep'])[:60]}")
    for r in index["largest"][:5]:
        log(f"  big {r['bytes'] / 1e9:.2f} GB :: "
            f"{os.path.basename(r['path'])[:70]}")


def main(argv=None):
    p = argparse.ArgumentParser(prog=APP)
    p.add_argument("--root", default=r"D:\new")
    p.add_argument("--find", default=None, help="regex on filename")
    p.add_argument("--tags", default=None,
                   help="comma list; file needs >=1 of these tags")
    p.add_argument("--dedupe", action="store_true",
                   help="detect duplicate clones (sample digests)")
    p.add_argument("--max-hash-gb", type=float, default=2.0)
    p.add_argument("--no-index", dest="save_index",
                   action="store_false")
    p.add_argument("--sniff", action="store_true",
                   help="validate magic bytes (opens every file; cached "
                        "against the previous index when unchanged)")
    args = p.parse_args(argv)
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        log(f"no such root: {root}")
        return 2
    find_rx = re.compile(args.find, re.I) if args.find else None
    tag_filter = ({t.strip().lower() for t in args.tags.split(",")
                   if t.strip()} if args.tags else None)
    unknown = tag_filter - set(TAG_PATTERNS) if tag_filter else set()
    if unknown:
        log(f"unknown tags ignored: {sorted(unknown)}")
        tag_filter -= unknown
    index = scan(root, find_rx=find_rx, tag_filter=tag_filter,
                 dedupe=args.dedupe, max_hash_gb=args.max_hash_gb,
                 save_index=args.save_index, sniff=args.sniff)
    show(index)
    for r in index["files"][:25]:
        print(f"  {r['kind']:<5} {r['ext']:<5} "
              f"{r['bytes'] / 1e6:>9.1f}MB "
              f"{'HD' if r['hd'] else '  '} "
              f"[{','.join(r['tags'])}] {r['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
