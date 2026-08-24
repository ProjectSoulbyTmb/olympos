"""jobs - production job-spec schema + validation.

A job is JSON:
  {"name": "...", "workdir": "out/", "steps": [ {...}, ... ]}

Step types: slideshow, concat, trim, scale, crop, fade, watermark,
text, speed, gif, extract_frames. Steps run in order; any step may
reference an earlier step's output by path relative to the workdir.
"""
import os

STEP_TYPES = {
    # type -> (required keys, optional keys)
    "slideshow": (
        ["images", "output"],
        ["per_image", "crossfade", "size", "fps", "audio"],
    ),
    "concat": (["inputs", "output"], []),
    "trim": (["input", "output"], ["start", "end", "reencode"]),
    "scale": (["input", "output"], ["width", "height"]),
    "crop": (["input", "output", "width", "height"], ["x", "y"]),
    "fade": (["input", "output"], ["fade_in", "fade_out"]),
    "watermark": (["input", "output", "image"],
                  ["position", "opacity", "margin"]),
    "text": (["input", "output", "text"],
             ["position", "fontsize", "start", "end", "fontfile",
              "color"]),
    "speed": (["input", "output", "factor"], []),
    "gif": (["input", "output"], ["fps", "width"]),
    "extract_frames": (["input", "out_dir"], ["count", "format"]),
}

MEDIA_KEYS = ("input", "image", "audio")
LIST_KEYS = ("images", "inputs")

POSITIONS = {
    "br": "main_w-overlay_w-{m}:main_h-overlay_h-{m}",
    "bl": "{m}:main_h-overlay_h-{m}",
    "tr": "main_w-overlay_w-{m}:{m}",
    "tl": "{m}:{m}",
    "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
}


def validate(job, base_dir=None, produced=None):
    """Return (cleaned_job, errors_list). Empty errors list == valid.

    `produced` is the set of output names earlier/later steps in the
    same job declare - references to those skip existence checks
    (they will exist once their producing step renders).
    """
    if not isinstance(job, dict):
        return None, ["job must be a JSON object"]
    errors = []
    name = str(job.get("name") or "").strip()
    if not name:
        errors.append("missing 'name'")
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("'steps' must be a non-empty list")
        steps = []
    produced = {str(p) for p in (produced or ())}
    for step in steps:
        if isinstance(step, dict):
            for key in ("output", "out_dir"):
                if step.get(key):
                    produced.add(str(step[key]))
                    if key == "output":
                        produced.add(
                            os.path.basename(str(step[key])))
    cleaned = {"name": name,
               "workdir": str(job.get("workdir") or "out"),
               "steps": []}
    for i, step in enumerate(steps):
        where = "step[%d]" % i
        if not isinstance(step, dict):
            errors.append("%s: must be an object" % where)
            continue
        stype = step.get("type")
        if stype not in STEP_TYPES:
            errors.append("%s: unknown type %r" % (where, stype))
            continue
        req, opt = STEP_TYPES[stype]
        clean = {"type": stype}
        for key in req:
            if step.get(key) in (None, "", []):
                errors.append("%s (%s): missing '%s'"
                              % (where, stype, key))
        for key in list(req) + list(opt):
            value = step.get(key)
            if key != "type" and value not in (None, ""):
                clean[key] = value
        for key in step:
            if key != "type" and key not in req and key not in opt:
                errors.append("%s (%s): unknown field '%s'"
                              % (where, stype, key))
        for key in MEDIA_KEYS:
            if key in clean and _missing(clean[key], produced) and \
                    not os.path.exists(_resolve(clean[key], base_dir)):
                errors.append("%s: '%s' not found: %s"
                              % (where, key, clean[key]))
        for key in LIST_KEYS:
            for ref in clean.get(key) or []:
                if not isinstance(ref, (str, bytes, os.PathLike)):
                    errors.append("%s: %s entries must be paths"
                                  % (where, key))
                elif _missing(ref, produced) and \
                        not os.path.exists(_resolve(ref, base_dir)):
                    errors.append("%s: %s entry not found: %s"
                                  % (where, key, ref))
        cleaned["steps"].append(clean)
    return cleaned, errors


def _missing(ref, produced):
    p = str(ref)
    return p not in produced and os.path.basename(p) not in produced


def _resolve(path, base_dir):
    p = os.fspath(path)
    if os.path.isabs(p) or base_dir is None:
        return p
    return os.path.join(base_dir, p)
