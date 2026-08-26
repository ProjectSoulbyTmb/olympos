"""ARES v2 profiles - named L1-L3 defense policies in the vault.

A profile pins a default level plus auto-lock target directories and
an optional rotation age. Profiles are ordinary vault records
(kind=profile), so they inherit the vault's encryption and travel
inside the same sealed container.
"""

import os
import time
import uuid

try:
    from . import kernel                      # package context
except ImportError:
    import ares_kernel as kernel              # workshop-flat context


class ProfileError(Exception):
    pass


def new_profile(name, default_level=1, targets=(), max_age_days=None):
    if int(default_level) not in kernel.LEVELS:
        raise ProfileError("bad level %r" % (default_level,))
    now = round(time.time(), 3)
    return {"id": uuid.uuid4().hex[:12], "kind": "profile",
            "name": name, "default_level": int(default_level),
            "targets": [os.path.abspath(t) for t in targets],
            "max_age_days": max_age_days,
            "created": now, "updated": now}


def get(vault, name):
    for r in vault.records:
        if r.get("kind") == "profile" and r.get("name") == name:
            return r
    return None


def set_profile(vault, name, default_level=None, targets=None,
                max_age_days=None):
    """Create or update; None fields keep their current value."""
    rec = get(vault, name)
    if rec is None:
        rec = new_profile(name)
        rec["updated"] = 0
        vault.add(rec)
    if default_level is not None:
        if int(default_level) not in kernel.LEVELS:
            raise ProfileError("bad level %r" % (default_level,))
        rec["default_level"] = int(default_level)
    if targets is not None:
        rec["targets"] = [os.path.abspath(t) for t in targets]
    if max_age_days is not None:
        rec["max_age_days"] = max(0, int(max_age_days))
    rec["updated"] = round(time.time(), 3)
    return rec


def validate(rec):
    if int(rec.get("default_level", 1)) not in kernel.LEVELS:
        raise ProfileError("profile %r has corrupt level" % rec["name"])
    return True
