"""Self-test gate for ares-vault (exit 0 = green).

Runs entirely on synthetic vectors inside temp dirs; never touches the
operator's real key store or any real passphrase.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

STATE = tempfile.mkdtemp(prefix="ares-gate-state-")
KEYS = tempfile.mkdtemp(prefix="ares-gate-keys-")
WORK = tempfile.mkdtemp(prefix="ares-gate-work-")
os.environ["ARES_STATE_DIR"] = STATE
os.environ["ARES_KEY_DIR"] = KEYS

RESULTS = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append(True)
        print("  PASS  %-46s %s" % (name, detail))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(False)
        print("  FAIL  %-46s %s: %s" % (name, type(exc).__name__, exc))


try:
    # deployed context: ares/ package beside this gate at repo root
    from ares.kernel import (AresError, KEY_LEN, NONCE_LEN, SALT_LEN,
                             MAGIC, open_blob, power_on_selftest,
                             rotate_file, seal_bytes, seal_file,
                             unseal_file, verify_journal)
    from ares import (audit, autolock, machine, pairing, profiles,
                      shamir, sync, vault)
    import ares.cli as cli
except ImportError:
    # workshop-flat context: modules woven flat beside this gate
    from ares_kernel import (AresError, KEY_LEN, NONCE_LEN, SALT_LEN,
                             MAGIC, open_blob, power_on_selftest,
                             rotate_file, seal_bytes, seal_file,
                             unseal_file, verify_journal)
    import ares_machine as machine
    import ares_shamir as shamir
    import ares_audit as audit
    import ares_autolock as autolock
    import ares_pairing as pairing
    import ares_profiles as profiles
    import ares_sync as sync
    import ares_vault as vault
    import ares_cli as cli

MK_A = bytearray(range(KEY_LEN))          # synthetic machine keys
MK_B = bytearray(reversed(range(KEY_LEN)))
PW = "gate-vector-alpha-42!"
PW2 = "gate-vector-beta-99!"
RECOVERY_HEX = None


def t_post():
    assert power_on_selftest(full=True)
    return "KATs + roundtrip green"


def t_shamir():
    secret = bytes(range(32))
    shares = shamir.split(secret, 3, 5)
    assert len(shares) == 5
    for combo in ((0, 1, 2), (0, 3, 4), (1, 2, 4)):
        got = shamir.combine([shares[i] for i in combo], 3)
        assert got == secret, "subset %r diverged" % (combo,)
    try:
        shamir.combine(shares[:2], 3)
    except shamir.AresShamirError:
        return "3-of-5 works, 2-of-5 refused"
    raise AssertionError("2-of-5 reconstruction was allowed")


def t_roundtrip():
    blob = seal_bytes(b"attack at dawn" * 100, PW, level=1,
                      machine_key=MK_A)
    assert blob[:5] == MAGIC and blob[-64:] != blob[:64]
    pt = open_blob(blob, PW, machine_key=MK_A)
    assert pt == b"attack at dawn" * 100
    try:
        open_blob(blob, PW2, machine_key=MK_A)
    except AresError:
        return "open/seal symmetric, wrong pass refused"
    raise AssertionError("wrong passphrase accepted")


def t_theft():
    blob = seal_bytes(b"crown jewels", PW, level=1, machine_key=MK_A)
    try:
        open_blob(blob, PW, machine_key=MK_B)
    except AresError:
        return "foreign machine key refused"
    raise AssertionError("stolen blob opened on foreign machine")


def t_tamper_matrix():
    blob = bytearray(seal_bytes(b"integrity matters", PW, level=1,
                                machine_key=MK_A))
    flipped = bytearray(blob)
    flipped[40] ^= 0x01                     # mid-ciphertext bit flip
    try:
        open_blob(bytes(flipped), PW, machine_key=MK_A)
        raise AssertionError("bit-flip accepted")
    except AresError:
        pass
    try:
        open_blob(bytes(blob[:-10]), PW, machine_key=MK_A)
        raise AssertionError("truncation accepted")
    except AresError:
        pass
    other = seal_bytes(b"other plaintext entirely", PW, level=1,
                       machine_key=MK_A)
    franken = bytes(blob[:30]) + other[30:]  # cross-file swap
    try:
        open_blob(franken, PW, machine_key=MK_A)
        raise AssertionError("blob-swap accepted")
    except AresError:
        return "flip+truncate+swap all refused"


def t_nonce_uniqueness():
    seen = set()
    off = 7 + SALT_LEN          # header: MAGIC5 VER1 LVL1 SALT16 NONCE16
    for i in range(24):
        blob = seal_bytes(b"n%d" % i, PW, level=1, machine_key=MK_A)
        nonce = blob[off:off + NONCE_LEN]
        assert nonce not in seen, "nonce reuse at %d" % i
        seen.add(nonce)
    return "24 seals, 24 distinct nonces"


def t_file_lifecycle():
    src = os.path.join(WORK, "treasure.txt")
    payload = b"classified source code\n" * 50
    with open(src, "wb") as fh:
        fh.write(payload)
    sealed = seal_file(src, PW, level=1)
    assert sealed.endswith(".ares")
    assert not os.path.exists(src), "original survived sealing"
    back = unseal_file(sealed, PW)
    assert back == src
    with open(src, "rb") as fh:
        assert fh.read() == payload
    return "seal->gone, unseal->identical"


def t_rotate():
    src = os.path.join(WORK, "rot.txt")
    with open(src, "wb") as fh:
        fh.write(b"rotate me")
    sealed = seal_file(src, PW, level=1)
    with open(sealed, "rb") as fh:
        before = fh.read()
    rotate_file(sealed, PW, new_level=1)
    with open(sealed, "rb") as fh:
        after = fh.read()
    assert before != after, "rotate did not re-key"
    assert unseal_file(sealed, PW) == src
    with open(src, "rb") as fh:
        assert fh.read() == b"rotate me"
    return "fresh keys, stable plaintext"


def t_journal():
    ok, count, bad = verify_journal()
    assert ok, "journal chain broken: %r @%s" % (ok, bad)
    assert count >= 3, "expected journaled ops, got %d" % count
    with open(os.path.join(STATE, "journal.jsonl"), "r+b") as fh:
        data = fh.read()
        idx = data.find(b'"op":"seal"')
        assert idx > 0
        fh.seek(idx)
        fh.write(b'"Xp"')
    ok, count, bad = verify_journal()
    assert not ok, "tampered chain passed verification"
    return "%d entries, tamper detected @%s" % (count, bad)


def t_rails():
    root = WORK
    try:
        cli._rail_check(os.path.join(root, ".git", "config"), root)
        raise AssertionError(".git accepted")
    except cli.AresCliError:
        pass
    try:
        cli._rail_check(os.path.join(root, "x.py.ares"), root)
        raise AssertionError("double-seal accepted")
    except cli.AresCliError:
        pass
    outside = os.path.join(os.path.dirname(WORK), "outside.txt")
    try:
        cli._rail_check(outside, root)
        raise AssertionError("escape accepted")
    except cli.AresCliError:
        return ".git/double-seal/escape all blocked"


def t_codex_unlock():
    secret = bytes(range(KEY_LEN))
    shares = shamir.split(secret, 3, 5)
    codex = shamir.combine([shares[4], shares[0], shares[2]], 3)
    blob = seal_bytes(b"codex cargo", codex.hex(), level=1,
                      machine_key=MK_A)
    assert open_blob(blob, codex.hex(),
                     machine_key=MK_A) == b"codex cargo"
    return "recovery hex opens like a passphrase"


VPW = "vault-pass-alpha!"


def t_keyring():
    pt = b"ring cargo"
    blob = seal_bytes(pt, PW, level=1)     # sealed by primary key
    assert open_blob(blob, PW) == pt       # ring answers for primary
    try:
        open_blob(blob, PW, machine_key=MK_B)
    except AresError:
        return "explicit foreign key still refused"
    raise AssertionError("foreign explicit key accepted")


def t_vault_lifecycle():
    v = vault.create(VPW)
    r1 = vault.new_item("alpha-doc", tags=["work", "crown"],
                        notes="crown notes")
    r2 = vault.new_item("beta-doc", tags=["personal"])
    v.add(r1)
    v.add(r2)
    v.save(VPW)
    v2 = vault.load(VPW)
    assert len(v2.records) == 2
    hits = v2.search(["alpha"])
    assert len(hits) == 1 and hits[0]["id"] == r1["id"]
    assert len(v2.search(tag="CROWN")) == 1        # tag case-insens
    try:
        vault.load("wrong-vault-pass!")
        raise AssertionError("wrong vault passphrase accepted")
    except vault.VaultError:
        pass
    v2.remove(r2["id"])
    v2.save(VPW)
    assert len(vault.load(VPW).records) == 1
    assert os.path.exists(vault.vault_path() + ".bak")
    return "add/search/rm/save/load green"


def t_vault_tamper():
    p = vault.vault_path()
    with open(p, "rb") as fh:
        good = fh.read()
    flipped = bytearray(good)
    flipped[40] ^= 0x01
    with open(p, "wb") as fh:
        fh.write(bytes(flipped))
    try:
        vault.load(VPW)
        raise AssertionError("tampered vault opened")
    except vault.VaultError:
        pass
    with open(p, "wb") as fh:
        fh.write(good)
    assert len(vault.load(VPW).records) >= 1
    return "bit-flip refused, recovery green"


def t_profiles():
    v = vault.ensure(VPW)
    profiles.set_profile(v, "night", default_level=3,
                         targets=[WORK], max_age_days=30)
    v.save(VPW)
    rec = profiles.get(vault.load(VPW), "night")
    assert rec and profiles.validate(rec)
    assert rec["default_level"] == 3
    assert rec["targets"] == [os.path.abspath(WORK)]
    try:
        profiles.set_profile(v, "bad", default_level=9)
        raise AssertionError("bad level accepted")
    except profiles.ProfileError:
        pass
    return "set/get/validate + bad level refused"


def t_audit_walk():
    ok, entries, first_bad = audit.walk()
    assert ok and len(entries) >= 3, "chain should hold pre-tamper"
    rows = audit.filter_rows(entries, op="seal")
    assert rows, "expected seal entries in journal"
    text, ok2 = audit.show(tail=5)
    assert ok2 and "CHAIN-OK" in text
    exp = os.path.join(WORK, "audit.txt")
    assert audit.export(exp)
    assert os.path.exists(exp)
    jp = os.path.join(STATE, "journal.jsonl")
    with open(jp, "r+b") as fh:
        data = fh.read()
        idx = max(data.find(b'"op":"vault-save"'),
                  data.find(b'"op":"seal"'))
        assert idx > 0
        fh.seek(idx)
        fh.write(b'"Xp"')
    ok3, _, bad = audit.walk()
    assert not ok3 and bad is not None, "tampered chain must scream"
    with open(jp, "wb") as fh:                # restore for later tests
        fh.write(data)
    assert audit.walk()[0]
    return "%d entries walked, tamper caught, export written" % len(
        entries)


def t_pairing():
    pair_file = os.path.join(WORK, "a.pair")
    out, code = pairing.pair_begin(pair_file)
    assert out == pair_file and len(code.replace(" ", "")) == 32
    blob_a = seal_bytes(b"cross-machine", PW, level=1)
    old_key = os.environ.get("ARES_KEY_DIR")
    old_state = os.environ.get("ARES_STATE_DIR")
    bkeys = tempfile.mkdtemp(prefix="ares-gate-bkeys-")
    bstate = tempfile.mkdtemp(prefix="ares-gate-bstate-")
    os.environ["ARES_KEY_DIR"] = bkeys
    os.environ["ARES_STATE_DIR"] = bstate   # B journals to B's world
    try:
        machine.provision()                    # machine B identity
        try:
            pairing.pair_adopt(pair_file, "0" * 32)
            raise AssertionError("wrong code accepted")
        except pairing.PairingError:
            pass
        fp, path = pairing.pair_adopt(pair_file, code)
        assert os.path.exists(path)
        assert open_blob(blob_a, PW) == b"cross-machine"
        try:
            pairing.pair_adopt(pair_file, code)
            raise AssertionError("duplicate adoption accepted")
        except pairing.PairingError:
            pass
        assert pairing.pair_revoke(None) == 1
        try:
            open_blob(blob_a, PW)
            raise AssertionError("revoked ring still opens")
        except AresError:
            pass
    finally:
        os.environ["ARES_KEY_DIR"] = old_key
        os.environ["ARES_STATE_DIR"] = old_state
        shutil.rmtree(bkeys, ignore_errors=True)
        shutil.rmtree(bstate, ignore_errors=True)
    return "adopt opens A-sealed blob; wrong/dup refused; revoke bites"


def t_sync_roundtrip():
    src1 = os.path.join(WORK, "s1.txt")
    src2 = os.path.join(WORK, "s2.txt")
    for s in (src1, src2):
        with open(s, "wb") as fh:
            fh.write(b"sync me " * 10)
    f1 = seal_file(src1, PW, level=1)
    f2 = seal_file(src2, PW, level=1)
    bundle = os.path.join(WORK, "b.zip")
    out, n = sync.pack([WORK], bundle)
    assert n >= 2 and os.path.exists(out)
    into = os.path.join(WORK, "in")
    os.makedirs(into)
    import zipfile
    with zipfile.ZipFile(bundle) as zf:
        names = [n for n in zf.namelist() if n.startswith("blobs/")]
        payload = {n_: zf.read(n_) for n_ in names}
        head = zf.read("manifest.json")
    written = sync.unpack(bundle, into=into)
    got_names = set(os.path.basename(w) for w in written)
    assert os.path.basename(f1) in got_names
    assert os.path.basename(f2) in got_names
    tampered = os.path.join(WORK, "bad.zip")
    victim = names[0]
    bad = bytes(bytearray(payload[victim]))
    bad = bad[:20] + bytes([bad[20] ^ 0x01]) + bad[21:]
    with zipfile.ZipFile(tampered, "w") as zf:
        zf.writestr("manifest.json", head)
        for n_ in names:
            zf.writestr(n_, bad if n_ == victim else payload[n_])
    try:
        sync.unpack(tampered, into=into, force=True)
        raise AssertionError("tampered bundle imported")
    except sync.SyncError:
        pass
    old = os.environ.get("ARES_KEY_DIR")
    fkeys = tempfile.mkdtemp(prefix="ares-gate-fkeys-")
    os.environ["ARES_KEY_DIR"] = fkeys
    try:
        machine.provision()
        try:
            sync.unpack(bundle, into=into, force=True)
            raise AssertionError("foreign signature accepted")
        except sync.SyncError:
            pass
    finally:
        os.environ["ARES_KEY_DIR"] = old
        shutil.rmtree(fkeys, ignore_errors=True)
    return "pack/unpack green; hash+signature both bite"


def t_autolock():
    sub = os.path.join(WORK, "lockme")
    os.makedirs(sub, exist_ok=True)
    files = []
    for i in range(2):
        p = os.path.join(sub, "doc%d.txt" % i)
        with open(p, "wb") as fh:
            fh.write(b"lock target %d" % i)
        files.append(p)
    dry = autolock.lock(paths=[sub], passphrase=PW, dry=True,
                        root=WORK)
    assert dry["dry"] and len(dry["files"]) == 2
    assert all(os.path.exists(p) for p in files), "dry run mutated"
    res = autolock.lock(paths=[sub], passphrase=PW, root=WORK)
    assert len(res["sealed"]) == 2
    assert not any(os.path.exists(p) for p in files)
    assert all(os.path.exists(p + ".ares") for p in files)
    gitdir = os.path.join(WORK, ".git")
    os.makedirs(gitdir, exist_ok=True)
    rail_file = os.path.join(gitdir, "config")
    with open(rail_file, "wb") as fh:
        fh.write(b"rail bait")
    try:
        autolock.lock(paths=[rail_file], passphrase=PW, root=WORK)
        raise AssertionError(".git target accepted")
    except cli.AresCliError:
        pass
    return "dry->seal lifecycle green; rails hold"


def main():
    try:
        machine.provision()     # real key for journal/lifecycle tests
        check("power-on-self-test (full)", t_post)
        check("shamir 3-of-5 / refuse 2-of-5", t_shamir)
        check("roundtrip + wrong-passphrase", t_roundtrip)
        check("simulated theft (foreign machine)", t_theft)
        check("tamper matrix", t_tamper_matrix)
        check("nonce uniqueness", t_nonce_uniqueness)
        check("file lifecycle", t_file_lifecycle)
        check("rotate re-keys in place", t_rotate)
        check("keyring opens for primary", t_keyring)
        check("vault lifecycle", t_vault_lifecycle)
        check("vault tamper -> .bak recovery", t_vault_tamper)
        check("profiles set/get/validate", t_profiles)
        check("audit walk + export + tamper", t_audit_walk)
        check("pairing adopt/open/revoke", t_pairing)
        check("sync pack/import/tamper/foreign", t_sync_roundtrip)
        check("autolock dry/seal/rails", t_autolock)
        check("safety rails", t_rails)
        check("codex-as-passphrase", t_codex_unlock)
        check("journal chain + tamper detection", t_journal)
        print("ares-vault gate: %d/%d green"
              % (sum(1 for r in RESULTS if r), len(RESULTS)))
        sys.exit(0 if all(RESULTS) else 1)
    finally:
        shutil.rmtree(STATE, ignore_errors=True)
        shutil.rmtree(KEYS, ignore_errors=True)
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
