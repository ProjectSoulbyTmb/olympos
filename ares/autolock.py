"""ARES v2 autolock - seal on schedule; unseal stays manual BY LAW.

lock() seals every unsealed file under the given paths or a named
profile's targets, one passphrase prompt per run. There is deliberately
NO auto-unseal: schedules can only tighten secrecy, never loosen it.
"""

import getpass

try:
    from . import kernel, profiles, vault     # package context
except ImportError:
    import ares_kernel as kernel              # workshop-flat context
    import ares_profiles as profiles
    import ares_vault as vault


class LockError(Exception):
    pass


def resolve_targets(paths, profile_name=None, vault_passphrase=None):
    """Merge CLI paths with profile targets; return (targets, level)."""
    targets = [str(p) for p in paths]
    lvl = None
    if profile_name:
        vp = vault_passphrase or getpass.getpass(
            "[ares] vault passphrase: ")
        v = vault.ensure(vp)
        rec = profiles.get(v, profile_name)
        if rec is None:
            raise LockError("no such profile: %s" % profile_name)
        profiles.validate(rec)
        if not targets:
            targets = list(rec.get("targets", []))
        lvl = rec.get("default_level")
        if not targets:
            raise LockError("profile %r has no targets"
                            % profile_name)
    return targets, lvl


def lock(paths=(), profile_name=None, level=None, passphrase=None,
         vault_passphrase=None, dry=False, root=None):
    """Seal everything unsealed under targets; returns a summary dict.
    root pins the rail boundary (tests inject a synthetic root; the
    CLI leaves it None for repo-root law)."""
    import ares.cli as cli            # lazy: cli imports this module
    targets, prof_lvl = resolve_targets(paths, profile_name,
                                        vault_passphrase)
    lvl = int(level or prof_lvl or 1)
    root = root or cli._repo_root()
    files = cli._gather_files(targets, recursive=True)
    todo = []
    for f in files:
        cli._rail_check(f, root)
        todo.append(f)
    if dry:
        return {"dry": True, "files": todo, "level": lvl,
                "profile": profile_name or "-"}
    if not todo:
        kernel._journal_append("autolock", {"sealed": 0,
                                            "profile":
                                            profile_name or "-",
                                            "level": lvl})
        return {"dry": False, "sealed": [], "level": lvl,
                "profile": profile_name or "-"}
    pw = passphrase or getpass.getpass("[ares] seal passphrase: ")
    sealed = []
    for f in todo:
        sealed.append(kernel.seal_file(f, pw, level=lvl))
    kernel._journal_append("autolock", {"sealed": len(sealed),
                                        "profile": profile_name or "-",
                                        "level": lvl})
    return {"dry": False, "sealed": sealed, "level": lvl,
            "profile": profile_name or "-"}


def _exposure_log():
    import os as _os
    d = kernel.state_dir()
    _os.makedirs(d, exist_ok=True)
    return _os.path.join(d, "exposure.jsonl")


def sweep(profile_name=None):
    """Unattended exposure audit: DRY-RUN only. Reports what WOULD be
    sealed. Deliberately refuses to automate real sealing - that needs
    the passphrase, and storing it would defeat the threat model."""
    import json as _json
    import os as _os
    import time as _time
    try:
        result = lock(paths=(), profile_name=profile_name,
                      dry=True)
    except LockError as exc:
        row = {"t": round(_time.time(), 3), "ok": False,
               "error": str(exc)}
        with open(_exposure_log(), "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(row) + "\n")
        raise
    exposed = result["files"]
    row = {"t": round(_time.time(), 3), "ok": True,
           "profile": result["profile"], "exposed": len(exposed),
           "files": exposed}
    with open(_exposure_log(), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write(_json.dumps(row) + "\n")
    return row
