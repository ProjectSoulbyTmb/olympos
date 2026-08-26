"""ARES CLI - v1 verbs plus the v2 vault suite.

v1:  init | seal | unseal | rotate | status
v2:  vault | profile | lock | audit | pair-* | sync-*

Secret hygiene: passphrases arrive via getpass (never argv/env/files).
The recovery codex prints ONCE at init and is never stored anywhere.
"""

import argparse
import getpass
import hashlib
import json
import os
import sys
import time

try:
    from . import kernel, machine, shamir     # package context
    from . import audit, autolock, pairing, profiles, sync, vault
except ImportError:                           # workshop-flat context
    import ares_kernel as kernel              # noqa: F401
    import ares_machine as machine            # noqa: F401
    import ares_shamir as shamir              # noqa: F401
    import ares_audit as audit                # noqa: F401
    import ares_autolock as autolock          # noqa: F401
    import ares_pairing as pairing            # noqa: F401
    import ares_profiles as profiles          # noqa: F401
    import ares_sync as sync                  # noqa: F401
    import ares_vault as vault                # noqa: F401

RAIL_DIRS = {".git", "__pycache__", ".opencode", ".worktrees"}
SKIP_SUFFIX = ".ares"
SELF_NAMES = {"ares", "ares_kernel.py", "ares_cli.py",
              "ares_machine.py", "ares_shamir.py",
              "ares_vault.py", "ares_profiles.py", "ares_audit.py",
              "ares_pairing.py", "ares_sync.py", "ares_autolock.py"}


class AresCliError(Exception):
    pass


def _vault_pw():
    return getpass.getpass("[ares] vault passphrase: ")


def _split_tags(text):
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    walk = here
    for _ in range(4):
        if os.path.isdir(os.path.join(walk, "realms")):
            return walk
        nxt = os.path.dirname(walk)
        if nxt == walk:
            break
        walk = nxt
    return os.getcwd()


def _inside_root(path, root):
    rp = os.path.realpath(path)
    rr = os.path.realpath(root)
    return rp == rr or rp.startswith(rr + os.sep)


def _rail_check(path, root, allow_anywhere=False):
    parts = set(part for part in
                os.path.normpath(path).replace("\\", "/").split("/")
                if part)
    if parts & RAIL_DIRS or parts & SELF_NAMES:
        raise AresCliError("RAIL: refusing protected path %s" % path)
    if path.endswith(SKIP_SUFFIX):
        raise AresCliError("RAIL: refusing to double-seal %s" % path)
    if not allow_anywhere and not _inside_root(path, root):
        raise AresCliError(
            "RAIL: %s escapes the repo root (use --anywhere)" % path)


def _gather_files(paths, recursive=False):
    found = []
    for p in paths:
        if os.path.isdir(p):
            if not recursive:
                raise AresCliError("%s is a directory "
                                   "(use --recursive)" % p)
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames
                               if d not in RAIL_DIRS]
                for f in sorted(filenames):
                    fp = os.path.join(dirpath, f)
                    if f.endswith(SKIP_SUFFIX):
                        continue
                    found.append(fp)
        else:
            found.append(p)
    seen = set()
    uniq = []
    for f in found:
        af = os.path.abspath(f)
        if af not in seen:
            seen.add(af)
            uniq.append(f)
    return uniq


def cmd_init(args):
    kernel.power_on_selftest(full=True)
    p = machine.provision()
    print("[ares] machine lock provisioned: %s" % p)
    while True:
        pw = getpass.getpass("[ares] passphrase (min 10 chars): ")
        if len(pw) < 10:
            print("      too short")
            continue
        pw2 = getpass.getpass("[ares] repeat passphrase: ")
        if pw == pw2:
            break
        print("      mismatch, try again")
    secret = os.urandom(kernel.KEY_LEN)
    shares = shamir.split(secret, threshold=3, shares=5)
    print()
    print("=" * 62)
    print("RECOVERY CODEX - print/store offline NOW.")
    print("Any THREE hex shares reconstruct an unlock phrase that")
    print("opens every sealed file exactly like your passphrase.")
    print("These lines will NEVER be shown again.")
    print("=" * 62)
    for x, s in shares:
        print("  SHARE %d/5: %s" % (x, s.hex()))
    print("=" * 62)
    probe = kernel.seal_bytes(b"codex-probe", secret.hex(), level=1)
    kernel.open_blob(probe, secret.hex())
    print("[ares] codex verified against the cipher. Ready.")
    return 0


def cmd_seal(args):
    root = _repo_root()
    files = _gather_files(args.paths, recursive=args.recursive)
    if not files:
        raise AresCliError("nothing to seal")
    pw = getpass.getpass("[ares] passphrase: ")
    done = 0
    for f in files:
        _rail_check(f, root, allow_anywhere=args.anywhere)
        out = kernel.seal_file(f, pw, level=args.level)
        done += 1
        print("[ares] sealed %-50s -> %s" % (f, os.path.basename(out)))
    print("[ares] %d file(s) sealed at L%d" % (done, args.level))
    return 0


def cmd_unseal(args):
    root = _repo_root()
    targets = []
    for p in args.paths:
        if os.path.isdir(p):
            for dirpath, _d, filenames in os.walk(p):
                for f in sorted(filenames):
                    if f.endswith(".ares"):
                        targets.append(os.path.join(dirpath, f))
        else:
            targets.append(p)
    if not targets:
        raise AresCliError("no .ares targets")
    pw = getpass.getpass("[ares] unlock phrase (passphrase or codex "
                         "hex): ")
    done = 0
    for t in targets:
        _rail_check(t[:-5], root, allow_anywhere=args.anywhere)
        out = kernel.unseal_file(t, pw)
        done += 1
        print("[ares] unsealed %-48s -> %s" %
              (os.path.basename(t), os.path.basename(out)))
    print("[ares] %d file(s) restored" % done)
    return 0


def cmd_rotate(args):
    pw = getpass.getpass("[ares] current unlock phrase: ")
    for t in args.paths:
        kernel.rotate_file(t, pw, new_level=args.level)
        print("[ares] rotated %s -> L%d" % (t, args.level))
    return 0


# ------------------------------------------------------- v2: vault --

def cmd_vault_add(args):
    pw = _vault_pw()
    v = vault.ensure(pw)
    rec = vault.new_item(args.name, tags=_split_tags(args.tags),
                         notes=args.notes or "")
    if args.path:
        p = os.path.abspath(args.path)
        if not os.path.isfile(p):
            raise AresCliError("no such file: %s" % args.path)
        rec["path"] = p
        rec["size"] = os.path.getsize(p)
        rec["sha256"] = _sha256_file(p)
    v.add(rec)
    v.save(pw)
    print("[ares] vaulted %-32s id=%s tags=%s" %
          (args.name, rec["id"], ",".join(rec["tags"]) or "-"))
    return 0


def cmd_vault_list(_args):
    v = vault.ensure(_vault_pw())
    if not v.records:
        print("[ares] vault is empty")
        return 0
    for r in sorted(v.records, key=lambda r: (r.get("kind"), r["name"])):
        kind = "*" if r.get("kind") == "profile" else " "
        print(" %s %-12s %-28s %-18s %s" %
              (kind, r["id"], r["name"],
               ",".join(r.get("tags", [])) or "-",
               time.strftime("%Y-%m-%d", time.gmtime(
                   r.get("updated", 0)))))
    return 0


def cmd_vault_search(args):
    v = vault.ensure(_vault_pw())
    hits = v.search(terms=args.terms, tag=args.tag)
    for r in hits:
        print("  %-12s %-28s %s" % (r["id"], r["name"],
                                    r.get("notes", "")))
    print("[ares] %d hit(s)" % len(hits))
    return 0


def cmd_vault_show(args):
    v = vault.ensure(_vault_pw())
    rec = v.get(args.ref)
    print(json.dumps(rec, indent=1, sort_keys=True, default=str))
    return 0


def cmd_vault_rm(args):
    pw = _vault_pw()
    v = vault.load(pw)
    rec = v.remove(args.ref)
    v.save(pw)
    print("[ares] removed %s (%s)" % (rec["id"], rec["name"]))
    return 0


def cmd_profile_set(args):
    pw = _vault_pw()
    v = vault.ensure(pw)
    targets = [str(t) for t in args.target] if args.target else None
    rec = profiles.set_profile(v, args.name,
                               default_level=args.level,
                               targets=targets,
                               max_age_days=args.max_age)
    v.save(pw)
    print("[ares] profile %-20s L%d targets=%d max_age=%s" %
          (args.name, rec["default_level"], len(rec["targets"]),
           rec["max_age_days"]))
    return 0


def cmd_profile_show(args):
    v = vault.ensure(_vault_pw())
    names = [args.name] if args.name else None
    found = 0
    for r in v.records:
        if r.get("kind") != "profile":
            continue
        if names and r["name"] not in names:
            continue
        found += 1
        print("  %-20s L%d max_age=%s targets:" %
              (r["name"], r["default_level"], r.get("max_age_days")))
        for t in r.get("targets", []):
            print("      %s" % t)
    if not found:
        print("[ares] no profiles%s" %
              (" named %r" % args.name if args.name else ""))
    return 0


# -------------------------------------------------- v2: autolock --

def cmd_lock(args):
    result = autolock.lock(paths=args.paths,
                           profile_name=args.profile,
                           level=args.level,
                           dry=args.dry)
    if result["dry"]:
        print("[ares] DRY RUN - would seal %d file(s) at L%d "
              "(profile %s)" % (len(result["files"]),
                                result["level"], result["profile"]))
        for f in result["files"]:
            print("   %s" % f)
        return 0
    for out in result["sealed"]:
        print("[ares] sealed %s" % os.path.basename(out))
    print("[ares] autolock done: %d file(s) at L%d (profile %s)" %
          (len(result["sealed"]), result["level"], result["profile"]))
    return 0


# ------------------------------------------------------ v2: audit --

def cmd_audit(args):
    if args.export:
        ok = audit.export(args.export, op=args.op, since=args.since,
                          tail=args.tail)
        print("[ares] audit written: %s" % args.export)
        return 0 if ok else 1
    text, ok = audit.show(op=args.op, since=args.since,
                          tail=args.tail)
    print(text)
    return 0 if ok else 1


# ---------------------------------------------------- v2: pairing --

def cmd_pair_begin(args):
    out, code = pairing.pair_begin(out_path=args.out)
    print("=" * 62)
    print("PAIRING CODE - show once on machine B, then destroy this")
    print("printout together with the .pair file when adoption is done.")
    print(code)
    print("=" * 62)
    print("[ares] pairing file: %s" % out)
    return 0


def cmd_pair_adopt(args):
    fp, path = pairing.pair_adopt(args.pair_file)
    print("[ares] adopted key %s -> %s" % (fp, path))
    print("[ares] this machine can now open blobs sealed by the "
          "paired device (and vice versa).")
    return 0


def cmd_pair_revoke(args):
    n = pairing.pair_revoke(None if args.all else args.fp)
    print("[ares] revoked %d adopted key(s)" % n)
    return 0


def cmd_pair_list(_args):
    rows = pairing.pair_list()
    if not rows:
        print("[ares] no adopted keys")
    for fp, size in rows:
        print("  %s  %s" % (fp, size))
    return 0


# ------------------------------------------------------- v2: sync --

def cmd_sync_pack(args):
    out, n = sync.pack(args.paths, args.out)
    print("[ares] packed %d blob(s) -> %s" % (n, out))
    return 0


def cmd_sync_import(args):
    into = os.path.abspath(args.into)
    written = sync.unpack(args.bundle, into=into, force=args.force)
    for w in written:
        print("[ares] imported %s" % os.path.basename(w))
    print("[ares] %d blob(s) restored under %s" % (len(written), into))
    return 0


# ------------------------------------------------- v2: sweep --

def cmd_sweep(args):
    row = autolock.sweep(profile_name=args.profile)
    if not row["ok"]:
        print("[ares] sweep failed: %s" % row["error"])
        return 1
    print("[ares] exposure sweep (profile %s): %d unsealed file(s)"
          % (row["profile"], row["exposed"]))
    for f in row["files"][:20]:
        print("   %s" % f)
    if len(row["files"]) > 20:
        print("   ... and %d more" % (len(row["files"]) - 20))
    return 0


def cmd_status(_args):
    kernel.power_on_selftest()
    print("ARES vault-cipher - status")
    print("  machine lock : %s" %
          ("present" if machine.has_machine_key() else "ABSENT "
           "(run: python -m ares init)"))
    ok, count, bad = kernel.verify_journal()
    print("  self-test    : green")
    print("  journal      : %s (%d entries%s)" %
          ("chain-ok" if ok else "CHAIN BROKEN", count,
           "" if bad is None else ", first bad @%d" % bad))
    return 0 if ok else 1


def build_parser():
    ap = argparse.ArgumentParser(prog="ares",
                                 description="ARES code-seal kernel")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="provision machine lock + codex")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("seal", help="encrypt files in place")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("-r", "--recursive", action="store_true")
    sp.add_argument("--level", type=int, default=1, choices=(1, 2, 3))
    sp.add_argument("--anywhere", action="store_true")
    sp.set_defaults(fn=cmd_seal)

    sp = sub.add_parser("unseal", help="restore sealed files")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--anywhere", action="store_true")
    sp.set_defaults(fn=cmd_unseal)

    sp = sub.add_parser("rotate", help="re-key sealed files")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--level", type=int, required=True,
                    choices=(1, 2, 3))
    sp.set_defaults(fn=cmd_rotate)

    sp = sub.add_parser("status", help="POST + journal chain check")
    sp.set_defaults(fn=cmd_status)

    # -------------------------------------------------- v2 verbs --
    sp = sub.add_parser("vault", help="encrypted metadata vault")
    vsub = sp.add_subparsers(dest="vaultcmd", required=True)

    p = vsub.add_parser("add", help="add a record")
    p.add_argument("name")
    p.add_argument("--tags", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--path", help="record facts about a real file")
    p.set_defaults(fn=cmd_vault_add)

    p = vsub.add_parser("list", help="list records")
    p.set_defaults(fn=cmd_vault_list)

    p = vsub.add_parser("search", help="search name/notes/tags")
    p.add_argument("terms", nargs="*")
    p.add_argument("--tag", default=None)
    p.set_defaults(fn=cmd_vault_search)

    p = vsub.add_parser("show", help="show one record (id or name)")
    p.add_argument("ref")
    p.set_defaults(fn=cmd_vault_show)

    p = vsub.add_parser("rm", help="remove one record")
    p.add_argument("ref")
    p.set_defaults(fn=cmd_vault_rm)

    sp = sub.add_parser("profile", help="defense policy profiles")
    psub = sp.add_subparsers(dest="profilecmd", required=True)

    p = psub.add_parser("set", help="create/update profile")
    p.add_argument("name")
    p.add_argument("--level", type=int, choices=(1, 2, 3))
    p.add_argument("--target", action="append",
                   help="directory to auto-lock (repeatable)")
    p.add_argument("--max-age", type=int, dest="max_age")
    p.set_defaults(fn=cmd_profile_set)

    p = psub.add_parser("show", help="show profiles")
    p.add_argument("name", nargs="?", default=None)
    p.set_defaults(fn=cmd_profile_show)

    sp = sub.add_parser("lock", help="auto-LOCK targets (unseal stays "
                                     "manual)")
    sp.add_argument("paths", nargs="*")
    sp.add_argument("--profile")
    sp.add_argument("--level", type=int, choices=(1, 2, 3))
    sp.add_argument("--dry", action="store_true")
    sp.set_defaults(fn=cmd_lock)

    sp = sub.add_parser("sweep", help="unattended exposure audit "
                                      "(dry-run, no secrets)")
    sp.add_argument("--profile")
    sp.set_defaults(fn=cmd_sweep)

    sp = sub.add_parser("audit", help="chain-verified journal viewer")
    sp.add_argument("--tail", type=int)
    sp.add_argument("--op")
    sp.add_argument("--since", help="YYYY-MM-DD or Nd days back")
    sp.add_argument("--export")
    sp.set_defaults(fn=cmd_audit)

    sp = sub.add_parser("pair-begin", help="export pairing file + code")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_pair_begin)

    sp = sub.add_parser("pair-adopt", help="adopt a paired key")
    sp.add_argument("pair_file")
    sp.set_defaults(fn=cmd_pair_adopt)

    sp = sub.add_parser("pair-revoke", help="drop adopted key(s)")
    sp.add_argument("fp", nargs="?", default=None)
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(fn=cmd_pair_revoke)

    sp = sub.add_parser("pair-list", help="list adopted keys")
    sp.set_defaults(fn=cmd_pair_list)

    sp = sub.add_parser("sync-pack", help="bundle .ares blobs, signed")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--out", required=True)
    sp.set_defaults(fn=cmd_sync_pack)

    sp = sub.add_parser("sync-import", help="verify + unpack bundle")
    sp.add_argument("bundle")
    sp.add_argument("--into", default=".")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_sync_import)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (kernel.AresError, machine.AresMachineError,
            shamir.AresShamirError, AresCliError,
            vault.VaultError, profiles.ProfileError,
            audit.AuditError, pairing.PairingError,
            sync.SyncError, autolock.LockError) as exc:
        print("[ares] FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
