"""DAEDALUS blueprint: kinema-host - the video domain adapter.

Batch V7 studio tier. Woven form proves the KINEMA host law offline:

  B7  determinism - same job spec + seed => identical artifact sha256,
      proven end-to-end with a synthetic local backend (the real
      FFmpeg backend binds at commissioning; the digest law above it
      is what this blueprint owns).
  Schema gates - hostile specs are refused BEFORE any byte is written:
      traversal workdirs, escaping outputs, unknown step types,
      missing keys, zero/negative rates.

Extension shape: the woven module exposes host_execute() plus a
register(executors) adapter for APOLLO's drop-in protocol
(video produce/analyze/catalog verbs land on this)."""

import sys

HOST = '''"""KINEMA host - job-spec law + deterministic execution seam."""

import hashlib
import json
import os

KNOWN_STEPS = {
    "slideshow": ("images", "output"),
    "text": ("input", "text", "output"),
    "gif": ("input", "output"),
    "concat": ("inputs", "output"),
    "trim": ("input", "start", "end", "output"),
    "scale": ("input", "size", "output"),
    "fade": ("input", "output"),
    "watermark": ("input", "mark", "output"),
    "extract": ("input", "output"),
}


class SpecViolation(ValueError):
    pass


def _safe_rel(p):
    """Relative, forward-slashed, no dot-dot, no drive, no abs."""
    raw = str(p or "").replace("\\\\", "/")
    if not raw.strip("/"):
        raise SpecViolation("empty path: %r" % p)
    if raw.startswith("/"):
        raise SpecViolation("absolute path: %r" % p)
    s = raw.strip("/")
    if ":" in s:
        raise SpecViolation("drive letter: %r" % p)
    parts = [x for x in s.split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts):
        raise SpecViolation("traversal path: %r" % p)
    return "/".join(parts)


def validate_spec(spec):
    """-> list[str] problems. Empty means buildable."""
    p = []
    if not isinstance(spec, dict):
        return ["spec must be an object"]
    if not str(spec.get("name") or "").strip():
        p.append("name required")
    try:
        wd = _safe_rel(spec.get("workdir"))
    except SpecViolation as exc:
        return p + [str(exc)]
    if not wd or wd.startswith("out/") is False and wd != "out":
        pass  # any safe relative workdir is legal
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        return p + ["steps must be a non-empty list"]
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            p.append("step %d must be an object" % i)
            continue
        typ = st.get("type")
        if typ not in KNOWN_STEPS:
            p.append("step %d unknown type %r" % (i, typ))
            continue
        for key in KNOWN_STEPS[typ]:
            v = st.get(key)
            if v is None or (isinstance(v, (str, list)) and not v):
                p.append("step %d missing %s" % (i, key))
        for key in ("fps", "per_image"):
            if key in st:
                try:
                    if float(st[key]) <= 0:
                        p.append("step %d %s must be > 0" % (i, key))
                except (TypeError, ValueError):
                    p.append("step %d %s not numeric" % (i, key))
        if "start" in st and "end" in st:
            try:
                if float(st["end"]) < float(st["start"]):
                    p.append("step %d end before start" % i)
            except (TypeError, ValueError):
                p.append("step %d start/end not numeric" % i)
        for key in ("output",):
            if st.get(key):
                try:
                    op = _safe_rel(st[key])
                    if not op.startswith(wd + "/"):
                        p.append("step %d output escapes workdir"
                                 % i)
                except SpecViolation as exc:
                    p.append("step %d %s" % (i, exc))
    return p


def canonical(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":"))


def job_digest(spec, seed):
    return hashlib.sha256(
        (str(seed) + "|" + canonical(spec)).encode("utf-8")).hexdigest()


def build_plan(spec):
    return [{"index": i, "type": st["type"],
             "args": {k: v for k, v in st.items() if k != "type"}}
            for i, st in enumerate(spec.get("steps", []))]


class LocalBackend(object):
    """Synthetic deterministic renderer: artifact bytes derive from
    the job digest, so identical spec+seed yields identical sha256 -
    B7 provable with zero ffmpeg present. Commissioning swaps in
    kinema.produce behind the same seam; the digest law is upstream
    of any encoder."""

    def render(self, plan, base_dir, job_sha):
        artifacts = []
        for step in plan:
            out_rel = _safe_rel(step["args"]["output"])
            out_abs = os.path.join(base_dir,
                                   out_rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(out_abs), exist_ok=True)
            blob = (b"KINEMA-SYNTHETIC:" + job_sha.encode("utf-8")
                    + (":%d" % step["index"]).encode("utf-8"))
            with open(out_abs, "wb") as fh:
                fh.write(blob)
            artifacts.append({
                "path": out_rel,
                "sha256": hashlib.sha256(blob).hexdigest()})
        return artifacts


def host_execute(spec, seed, base_dir):
    problems = validate_spec(spec)
    if problems:
        return {"ok": False, "errors": problems}
    job_sha = job_digest(spec, seed)
    plan = build_plan(spec)
    # Outputs are job-root-relative; workdir is the containment gate
    # (validated above: every output starts with it), not an extra
    # path prefix. Rendering roots at base_dir so bytes land exactly
    # where the manifest says they do.
    wd_rel = _safe_rel(spec.get("workdir") or "out")
    os.makedirs(os.path.join(base_dir,
                             wd_rel.replace("/", os.sep)),
                exist_ok=True)
    artifacts = LocalBackend().render(plan, base_dir, job_sha)
    return {"ok": True, "job_sha256": job_sha, "artifacts": artifacts}


def register(executors):
    """APOLLO drop-in adapter: video domain lands here."""
    def _produce(session, cmd, ctx):
        import json as _json
        try:
            spec = _json.loads(str(cmd.target or ""))
        except ValueError:
            return {"ok": False, "error": "produce target must be "
                                         "a JSON job spec"}
        return host_execute(spec, ctx["seed"], ctx["root"])
    executors[("video", "produce")] = _produce
'''

GATE = '''"""Self-test gate for kinema-host (exit 0 = green)."""

import hashlib
import json
import os
import shutil
import sys

from kinema_host import (LocalBackend, SpecViolation, build_plan,
                         host_execute, job_digest, validate_spec)

SPEC = {"name": "muster reel", "workdir": "out",
        "steps": [
            {"type": "slideshow",
             "images": ["a.png", "b.png"],
             "per_image": 2.5, "fps": 30, "crossfade": 0.6,
             "size": "1920x1080", "output": "out/reel.mp4"},
            {"type": "gif", "input": "out/reel.mp4", "fps": 12,
             "width": 480, "output": "out/reel.gif"},
        ]}


def main():
    # B7: same spec + seed => identical digests, twice over
    r1 = host_execute(SPEC, "seed-7", "run-a")
    r2 = host_execute(SPEC, "seed-7", "run-b")
    assert r1["ok"] and r2["ok"], (r1, r2)
    assert r1["job_sha256"] == r2["job_sha256"], "digest drift"
    assert [a["sha256"] for a in r1["artifacts"]] == \\
           [a["sha256"] for a in r2["artifacts"]], "artifact drift"

    # seed sensitivity: different seed MUST move the digest
    r3 = host_execute(SPEC, "seed-8", "run-c")
    assert r3["job_sha256"] != r1["job_sha256"], \\
        "digest did not track the seed"

    # artifact bytes really derive from the digest
    blob = open(os.path.join("run-a", "out", "reel.mp4"),
                "rb").read()
    assert hashlib.sha256(blob).hexdigest() == \\
        r1["artifacts"][0]["sha256"]

    # schema gates refuse hostility before any write
    bad_specs = [
        {"name": "x", "workdir": "../esc", "steps": SPEC["steps"]},
        dict(SPEC, steps=[{"type": "teleport", "output":
                           "out/x.mp4"}]),
        dict(SPEC, steps=[{"type": "gif", "input": "in.mp4"}]),
        dict(SPEC, steps=[dict(SPEC["steps"][0],
                               output="../escape.mp4")]),
        dict(SPEC, steps=[dict(SPEC["steps"][0], fps=0)]),
        dict(SPEC, steps=[]),
    ]
    for bad in bad_specs:
        problems = validate_spec(bad)
        assert problems, "schema gate let slip: %r" % bad
        verdict = host_execute(bad, "seed-7", "refused")
        assert not verdict["ok"] and verdict["errors"], verdict

    print("kinema-host gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {"kinema_host.py": HOST, "verify_kinemahost.py": GATE}


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # canonical form gutted -> every spec hashes alike; the
    # seed-sensitivity assertion goes red (independent breaker)
    "digest_skip": ("kinema_host.py",
                    'return hashlib.sha256(\n'
                    '        (str(seed) + "|" + '
                    'canonical(spec)).encode("utf-8")).hexdigest()',
                    'return hashlib.sha256(b"gutted").hexdigest()'),
}

BLUEPRINT = {
    "description": "VOLTAGE kinema-host (video domain): job-schema "
                   "gates + B7 digest determinism, synthetic backend",
    "files": FILES,
    "gate": [sys.executable, "verify_kinemahost.py"],
    "faults": dict(FAULTS),
}
