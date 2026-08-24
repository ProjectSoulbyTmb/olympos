"""video_audit - Riley's offline video auditor for APHRODITE libraries.

Scans a library root for video files, classifies them into categories
(pmv / goth / feet by filename markers), and runs a full integrity audit:
container magic bytes, zero-byte/truncation heuristics, resolution tag
from the filename, and duplicate-clone detection (sha256 content match
for equal-size files + normalized name twins; files over 256 MB are
compared by head+tail sample digest and reported as "content-sampled").

Stdlib only, zero network - safe to run against any root at any time.
Existing files are never modified; output is a single JSON report.

Usage:
  python ingest/video_audit.py --root D:\\new
  python ingest/video_audit.py --root D:\\new --categories pmv,goth,feet
  python ingest/video_audit.py --root D:\\new --all
  python ingest/video_audit.py --root D:\\new --fix   # quarantine problem files

Fixing never deletes: problem files (duplicate clones, zero-byte,
bad-magic, truncated) are moved to <root>\\_audit_quarantine\\ for review;
the kept/canonical copy always stays in place.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

APP = "video_audit"
VERSION = "1.0"

VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}

CATEGORY_PATTERNS = {
    "pmv": re.compile(r"\bpmv\b|cock\s?hero", re.I),
    "goth": re.compile(r"goth", re.I),
    "feet": re.compile(r"\bfeet\b|foot(?!ball|age)|\bsoles?\b|\btoes?\b",
                       re.I),
}

RES_RE = re.compile(r"\((2160|1440|1080|720|480)\)")
HD_RES = {2160, 1440, 1080, 720}

NAME_TWIN_RE = re.compile(r"\s*\(\d+\)\s*$")

TAIL_WINDOW = 65536
SAMPLE_BYTES = 4 * 1024 * 1024
FULL_HASH_MAX = 256 * 1024 * 1024
QUARANTINE_NAME = "_audit_quarantine"
SOFT_PROBLEMS = {"tiny"}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def classify(name, categories):
    hits = [c for c in categories
            if CATEGORY_PATTERNS[c].search(os.path.basename(name))]
    return hits


def normalize_base(name):
    base = os.path.splitext(name)[0]
    prev = None
    while prev != base:
        prev = base
        base = NAME_TWIN_RE.sub("", base).strip()
    return re.sub(r"\s+", " ", base).lower()


def magic_ok(path, ext):
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    if ext in (".mp4", ".m4v", ".mov"):
        return len(head) >= 8 and head[4:8] == b"ftyp"
    if ext in (".webm", ".mkv"):
        return len(head) >= 4 and head[:4] == b"\x1aE\xdf\xa3"
    if ext == ".avi":
        return (len(head) >= 12 and head[:4] == b"RIFF"
                and head[8:12] == b"AVI ")
    return True


def tail_all_zero(path, size):
    if size == 0:
        return False
    with open(path, "rb") as fh:
        fh.seek(max(0, size - TAIL_WINDOW))
        tail = fh.read(TAIL_WINDOW)
    return len(tail) > 0 and not any(tail)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sample_digest(path, size):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read(SAMPLE_BYTES))
        fh.seek(max(0, size - SAMPLE_BYTES))
        h.update(fh.read())
    return h.hexdigest()


def file_digest(path, size):
    if size <= FULL_HASH_MAX:
        return sha256_file(path), "content"
    return sample_digest(path, size), "content-sampled"


def audit_file(path, size):
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    res_m = RES_RE.search(name)
    res = int(res_m.group(1)) if res_m else None
    rec = {
        "path": path,
        "name": name,
        "ext": ext,
        "bytes": size,
        "res": res,
        "hd": bool(res and res >= 720),
        "magic_ok": magic_ok(path, ext),
        "zero_byte": size == 0,
        "suspect_truncated": tail_all_zero(path, size),
        "tiny": 0 < size < 512 * 1024,
    }
    problems = []
    if rec["zero_byte"]:
        problems.append("zero-byte")
    if not rec["magic_ok"] and not rec["zero_byte"]:
        problems.append("bad-magic")
    if rec["suspect_truncated"]:
        problems.append("truncated-tail")
    if rec["tiny"]:
        problems.append("tiny")
    rec["problems"] = problems
    return rec


def find_duplicates(records):
    by_size = {}
    for r in records:
        if r["bytes"] > 0:
            by_size.setdefault(r["bytes"], []).append(r)
    groups = []
    claimed = set()
    for size, members in sorted(by_size.items()):
        if len(members) < 2:
            continue
        hashes = {}
        kind = "content"
        for m in members:
            log(f"  hashing {os.path.basename(m['path'])[:60]} "
                f"({size / 1e6:.0f} MB)")
            try:
                digest, k = file_digest(m["path"], size)
            except OSError:
                continue
            kind = k
            hashes.setdefault(digest, []).append(m)
        for digest, same in hashes.items():
            if len(same) < 2:
                continue
            same.sort(key=lambda m: (len(os.path.basename(m["path"])),
                                     os.path.basename(m["path"])))
            for m in same:
                claimed.add(m["path"])
            groups.append({"kind": kind, "hash": digest[:16],
                           "bytes": size,
                           "keep": same[0]["path"],
                           "dupes": [m["path"] for m in same[1:]]})
    by_base = {}
    for r in records:
        by_base.setdefault(normalize_base(r["name"]), []).append(r)
    for base, members in sorted(by_base.items()):
        if len(members) < 2:
            continue
        paths = {m["path"] for m in members}
        fresh = [m for m in members
                 if m["path"] not in claimed and len(paths) > 1]
        if len(fresh) < 2:
            continue
        fresh.sort(key=lambda m: (len(os.path.basename(m["path"])),
                                  os.path.basename(m["path"])))
        groups.append({"kind": "name", "base": base,
                       "keep": fresh[0]["path"],
                       "dupes": [m["path"] for m in fresh[1:]]})
    return groups


def quarantine_problem_files(root, report):
    qdir = os.path.join(root, QUARANTINE_NAME)
    os.makedirs(qdir, exist_ok=True)
    moved = []
    for r in report["problem_files"]:
        if set(r["problems"]) <= SOFT_PROBLEMS:
            continue
        base = os.path.basename(r["path"])
        dest = os.path.join(qdir, base)
        n = 2
        while os.path.exists(dest):
            stem, ext = os.path.splitext(base)
            dest = os.path.join(qdir, f"{stem} ({n}){ext}")
            n += 1
        try:
            os.replace(r["path"], dest)
            moved.append({"from": r["path"], "to": dest})
            log(f"  quarantined :: {base[:70]}")
        except OSError as e:
            log(f"  FIX FAIL {base[:60]}: {e}")
    return moved


def run_audit(root, categories, report_path, match_all=False):
    categories = [c for c in CATEGORY_PATTERNS if c in categories]
    records = []
    matched = []
    scanned = 0
    qdir = os.path.join(root, QUARANTINE_NAME)
    for dirpath, _dirs, names in os.walk(root):
        if os.path.relpath(dirpath, root).split(os.sep)[0] == \
                QUARANTINE_NAME:
            continue
        for n in sorted(names):
            ext = os.path.splitext(n)[1].lower()
            if ext not in VIDEO_EXTS:
                continue
            p = os.path.join(dirpath, n)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            scanned += 1
            if scanned % 250 == 0:
                log(f"  ...{scanned} videos enumerated")
            cats = classify(n, categories)
            rec = audit_file(p, size)
            rec["categories"] = cats
            records.append(rec)
            if cats or match_all:
                matched.append(rec)
    dupes = find_duplicates(matched)
    for d in dupes:
        for path in d["dupes"]:
            m = next(r for r in matched if r["path"] == path)
            m.setdefault("problems", [])
            if "duplicate" not in m["problems"]:
                m["problems"].append("duplicate")
            m["dup_of"] = d["keep"]
    report = {
        "app": APP, "v": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": root, "categories": categories,
        "videos_scanned": scanned,
        "matched": len(matched),
        "by_category": {c: sum(1 for r in matched if c in r["categories"])
                        for c in categories},
        "problem_files": [r for r in matched if r["problems"]],
        "duplicates": dupes,
        "files": matched,
    }
    tmp = report_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, report_path)

    log(f"scanned {scanned} videos, matched {len(matched)} "
        f"in scope {categories}")
    for c in categories:
        log(f"  {c}: {report['by_category'][c]}")
    bad = report["problem_files"]
    log(f"integrity: {len(bad)} problem files, "
        f"{len(dupes)} duplicate groups")
    for r in bad[:15]:
        log(f"  !! {','.join(r['problems'])} :: {r['name'][:70]}")
    for d in dupes[:10]:
        log(f"  ~~ {d['kind']} clone x{len(d['dupes'])} :: "
            f"{os.path.basename(d['keep'])[:60]}")
    log(f"report: {report_path}")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(prog=APP)
    p.add_argument("--root", default=r"D:\new")
    p.add_argument("--report", default=None)
    p.add_argument("--categories", default="pmv,goth,feet")
    p.add_argument("--all", action="store_true",
                   help="audit every video, not just scoped categories")
    p.add_argument("--fix", action="store_true",
                   help="quarantine problem files, then re-audit")
    args = p.parse_args(argv)
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        log(f"no such root: {root}")
        return 2
    cats = (list(CATEGORY_PATTERNS) if args.all
            else [c.strip().lower() for c in args.categories.split(",")
                  if c.strip()])
    unknown = [c for c in cats if c not in CATEGORY_PATTERNS]
    if unknown:
        log(f"unknown categories ignored: {unknown}")
        cats = [c for c in cats if c in CATEGORY_PATTERNS]
    if not cats:
        log("nothing to audit")
        return 2
    report_path = args.report or os.path.join(root, "_video_audit.json")
    report = run_audit(root, cats, report_path, match_all=args.all)
    if args.fix and report["problem_files"]:
        log(f"fixing: quarantining {len(report['problem_files'])} files")
        moved = quarantine_problem_files(root, report)
        log(f"moved {len(moved)} files -> "
            f"{os.path.join(root, QUARANTINE_NAME)}")
        run_audit(root, cats, report_path, match_all=args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
