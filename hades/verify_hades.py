"""HADES verify suite - gates every behavioral change to the kernel.

Run: python hades/verify_hades.py   (exit 0 = all checks pass)

Builds a throwaway fixture workspace in a temp dir, seals it, then
attacks it: edits, deletions, unregistered files, a rebranded copy of
protected logic (identifiers renamed), a heavier disguise (strings
swapped too), forged seal manifests, corrupted audit chains and
watermark forgery. Hades must catch every one.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hades import watermark as wm                     # noqa: E402
from hades.audit import AuditLog                      # noqa: E402
from hades.kernel import Hades, TamperError           # noqa: E402

CONTENT_SRC = '''"""Fixture shop tables."""

GOLD = {"logs": 25, "ore": 40}


def gold_cost(item_id):
    item_id = item_id.lower()
    if item_id not in GOLD:
        return 99
    return GOLD[item_id]


def cart_total(cart):
    total = 0
    for item_id in cart:
        total = total + gold_cost(item_id)
    return total
'''

WORLD_SRC = '''"""Fixture world helper."""


def spawn_point(zone_id):
    spots = {"lum": (10, 12), "var": (5, 30)}
    return spots.get(zone_id, (0, 0))
'''

STOLEN_EXACT = CONTENT_SRC.replace("GOLD", "PRICE_MAP").replace(
    "gold_cost", "get_price").replace("cart_total", "checkout").replace(
    '"""Fixture shop tables."""', '"""ShopKit tables. (c) OtherCo"""')

STOLEN_REBRAND = '''"""Pricing engine. Entirely our own work. - OtherCo"""

RATES = {"timber": 25, "stone": 40}


def quote(sku):
    sku = sku.lower()
    if sku not in RATES:
        return 99
    return RATES[sku]


def invoice(basket):
    amount = 0
    for sku in basket:
        amount = amount + quote(sku)
    return amount
'''

INNOCENT_SRC = '''"""Totally unrelated math."""

def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v
'''

CONFIG = {"products": [{"name": "core", "include": ["prod/**/*.py"], "exclude": []}]}


def build_fixture(base):
    def put(rel, text):
        path = os.path.join(base, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    put("prod/game/content.py", CONTENT_SRC)
    put("prod/game/world.py", WORLD_SRC)
    put("lair/stolen_exact.py", STOLEN_EXACT)
    put("lair/stolen_rebrand.py", STOLEN_REBRAND)
    put("lair/innocent.py", INNOCENT_SRC)


def kinds(rep):
    out = {}
    for v in rep["violations"]:
        out.setdefault(v["kind"], []).append(v["path"])
    return out


def check_seal_counts(h):
    counts = h.seal()
    if counts != {"core": 2}:
        return "expected {'core': 2}, got %r" % counts
    st = h.status()
    if not st.get("sealed") or st.get("files") != 2:
        return "status after seal wrong: %r" % st
    if not st.get("key_present"):
        return "key was not generated"
    return True


def check_clean_verify(h):
    rep = h.verify()
    if rep["violations"]:
        return "clean tree flagged: %r" % rep["violations"]
    return True


def check_modified(h, base):
    p = os.path.join(base, "prod", "game", "content.py")
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n# sneaky late edit\n")
    k = kinds(h.verify())
    if k.get("MODIFIED") != ["prod/game/content.py"]:
        return "modification not pinpointed: %r" % k
    return True


def check_missing(h, base):
    os.remove(os.path.join(base, "prod", "game", "world.py"))
    k = kinds(h.verify())
    if k.get("MISSING") != ["prod/game/world.py"]:
        return "deletion not pinpointed: %r" % k
    return True


def check_restore_and_unregistered(h, base):
    with open(os.path.join(base, "prod", "game", "content.py"), "w",
              encoding="utf-8") as f:
        f.write(CONTENT_SRC)
    with open(os.path.join(base, "prod", "game", "world.py"), "w",
              encoding="utf-8") as f:
        f.write(WORLD_SRC)
    if h.verify()["violations"]:
        return "restored originals still flagged"
    with open(os.path.join(base, "prod", "game", "extra.py"), "w",
              encoding="utf-8") as f:
        f.write(INNOCENT_SRC)
    k = kinds(h.verify())
    if k.get("UNREGISTERED") != ["prod/game/extra.py"]:
        return "new file not reported unregistered: %r" % k
    os.remove(os.path.join(base, "prod", "game", "extra.py"))
    return True


def check_ghosts(h):
    hits = {g["file"].replace("\\", "/"): g for g in h.ghosts()}
    exact = hits.get("lair/stolen_exact.py")
    if not exact or not exact["high"]:
        return "identifier-renamed copy not caught at HIGH: %r" % sorted(hits)
    reb = hits.get("lair/stolen_rebrand.py")
    if not reb:
        return "rebranded copy not caught at all"
    if "invoice" not in reb["medium"] and "invoice" not in reb["high"]:
        return "rebranded copy matched but not via its renamed unit: %r" % reb
    if "lair/innocent.py" in hits:
        return "innocent file falsely flagged: %r" % hits["lair/innocent.py"]
    if "evidence" not in exact or not exact["evidence"]:
        return "no provenance evidence attached to hit"
    return True


def check_watermark_roundtrip():
    key = b"k" * 32
    payload = "HADES|test|fixture|20260101-000000"
    tagged = payload + "|" + wm.tag(payload, key)
    tok = wm.token(payload, key)
    text = "x = 1\n"
    marked = wm.embed_text(text, tok, "#")
    found = wm.extract(marked)
    if found != [tagged]:
        return "roundtrip failed: %r" % found
    if not wm.authenticate(found[0], key):
        return "our own mark failed authentication"
    if wm.authenticate(found[0], b"f" * 32):
        return "mark authenticated with the wrong key"
    if wm.extract(text) != []:
        return "clean text produced phantom marks"
    return True


def check_detect_and_forgery(h, base):
    leak = os.path.join(base, "lair", "wm_leak.py")
    with open(leak, "w", encoding="utf-8") as f:
        f.write(CONTENT_SRC)
    payload = h.watermark_file(leak)
    recs = h.detect(os.path.join(base, "lair"))
    ours = [r for r in recs if r["authentic"]]
    if len(ours) != 1 or ours[0]["fields"]["asset"] != "lair/wm_leak.py":
        return "embedded mark not detected/authenticated: %r" % recs
    forged = wm.embed_text(CONTENT_SRC, wm.token(payload.rpartition("|")[0], b"f" * 32), "#")
    fake_path = os.path.join(base, "lair", "forged.py")
    with open(fake_path, "w", encoding="utf-8") as f:
        f.write(forged)
    recs = h.detect(fake_path)
    bad = [r for r in recs if r["file"].endswith("forged.py")]
    if not bad or bad[0]["authentic"]:
        return "forged mark accepted as ours"
    return True


def check_audit_chain(h, base):
    log = AuditLog(h.audit.path)
    ok, problems, count = log.verify()
    if not ok or count < 3:
        return "chain should be intact with events, got ok=%s n=%d %r" % (
            ok, count, problems)
    with open(log.path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    first = lines[0].replace('"seal"', '"seel"', 1)
    with open(log.path, "w", encoding="utf-8") as f:
        f.write("\n".join([first] + lines[1:]) + "\n")
    ok, problems, _ = AuditLog(log.path).verify()
    if ok:
        return "edited audit entry went undetected"
    return True


def check_forged_seal(h, base):
    import json
    with open(h.seal_path, "rb") as f:
        genuine = f.read()
    try:
        doc = json.loads(genuine.decode("utf-8"))
        target = sorted(doc["manifest"]["files"])[0]
        doc["manifest"]["files"][target]["sha256"] = "f" * 64
        with open(h.seal_path, "wb") as f:
            f.write(json.dumps(doc, sort_keys=True,
                               indent=1).encode("utf-8"))
        try:
            h.verify()
        except TamperError:
            return True
        return "forged manifest accepted"
    finally:
        # leave the seal authentic - later checks (fail-closed guard)
        # need a tree whose seal verifies
        with open(h.seal_path, "wb") as f:
            f.write(genuine)


def check_guard(h, base):
    h.seal()        # restore a trusted baseline (forged-seal check poisoned it)
    try:
        rep = h.ensure()
    except TamperError as e:
        return "guard blocked a clean tree: %s" % e
    if rep["violations"]:
        return "unexpected violations at guard time"
    p = os.path.join(base, "prod", "game", "world.py")
    with open(p, "a", encoding="utf-8") as f:
        f.write("# tamper\n")
    try:
        h.ensure()
    except TamperError:
        pass
    else:
        return "guard let a modified sealed asset through"
    with open(p, "w", encoding="utf-8") as f:
        f.write(WORLD_SRC)
    try:
        h.ensure()
    except TamperError as e:
        return "guard stayed angry after restore: %s" % e
    return True


def check_authority_gate(h, base):
    """Operator override authority: enroll -> mint -> execute; then
    attack it with a forged secret, an expired token, a replay, and a
    private-method raw call. Denial is the default."""
    import json as _json
    import time as _time
    from hades import authority

    auth_dir = os.path.join(base, "authdir")       # stands in for LOCALAPPDATA
    os.environ["HADES_AUTHORITY_DIR"] = auth_dir
    try:
        fp = authority.enroll()
        authority.write_fingerprint(h.state_dir, fp)
        if authority.read_fingerprint(h.state_dir) != fp:
            return "fingerprint not persisted"

        # happy path: mint + verify + single-use consumption
        tok = authority.mint("raw", {"call": "status"}, ttl_s=600)
        got = authority.verify_token(h.state_dir, tok)
        if got["op"] != "raw":
            return "valid token refused"
        try:
            authority.verify_token(h.state_dir, tok)
        except authority.AuthorityError:
            pass
        else:
            return "replayed nonce accepted"

        # wrong secret must fail the fingerprint binding:
        # re-enrolling rotates the secret while state still binds the old one
        authority.enroll()                          # secret rotated under us
        tok3 = authority.mint("raw", {"call": "status"})   # signed by NEW key
        try:
            authority.verify_token(h.state_dir, tok3)
        except authority.AuthorityError:
            pass
        else:
            return "secret/fingerprint mismatch accepted"

        # expired token (binding fixed first so expiry is what trips)
        fp2 = {"fingerprint": authority._hash_secret(),
               "enrolled_at": "test", "policy": 1}
        authority.write_fingerprint(h.state_dir, fp2)
        tok4 = authority.mint("force-seal", {}, ttl_s=60)
        tok4["exp"] = int(_time.time()) - 5
        import hashlib as _hl
        import hmac as _hm          # mint() signs with HMAC, not hashlib
        body = {k: v for k, v in tok4.items() if k != "sig"}
        with open(authority.secret_path(), "rb") as f:
            key = f.read()
        tok4["sig"] = _hm.new(key, authority._canonical(body),
                              _hl.sha256).hexdigest()
        try:
            authority.verify_token(h.state_dir, tok4)
        except authority.AuthorityError:
            pass
        else:
            return "expired token accepted"

        # tampered args (signature covers them)
        tok5 = authority.mint("exempt", {"path": "prod/x.py"})
        tok5["args"]["path"] = "prod/EVERYTHING.py"
        try:
            authority.verify_token(h.state_dir, tok5)
        except authority.AuthorityError:
            pass
        else:
            return "tampered args accepted"

        # raw grammar: private machinery denied, public allowed
        if authority.raw_allowed("_key"):
            return "private method passed the policy"
        try:
            authority.raw_call(h, "_load_seal", {})
        except authority.AuthorityError:
            pass
        else:
            return "raw call reached a private method"

        # end-to-end through the CLI dispatcher: exempt then verify green
        p = os.path.join(base, "prod", "game", "world.py")
        with open(p, "a", encoding="utf-8") as f:
            f.write("# operator-accepted tweak\n")
        from hades.cli import _exec_override
        tok6 = authority.mint("exempt",
                              {"path": "prod/game/world.py",
                               "reason": "operator tweak"})
        rc = _exec_override(h, _json.dumps(tok6))
        if rc != 0:
            return "exempt override failed rc=%s" % rc
        rep = h.verify()
        if rep["violations"]:
            return "exemption not honored: %r" % rep["violations"][:2]
        if not any(v["path"].endswith("world.py")
                   for v in rep.get("exempted", [])):
            return "exempted path not reported"
        return True
    finally:
        os.environ.pop("HADES_AUTHORITY_DIR", None)


def check_realms_expansion(h, base):
    """include_realms: every registered realm joins the seal; worktrees
    never leak in; explicit products keep precedence."""
    import json as _json
    reg_dir = os.path.join(base, "realms")
    os.makedirs(reg_dir, exist_ok=True)
    with open(os.path.join(reg_dir, "registry.json"), "w",
              encoding="utf-8") as f:
        _json.dump({"realms": [
            {"name": "zeus", "lang": "python", "path": "zeus/server.py"},
            {"name": "ptah", "lang": "python", "path": "ptah/server.py"},
            {"name": "ghostrealm", "lang": "python",
             "path": "ghostrealm/nowhere.py"},
        ]}, f)
    prod = os.path.join(base, "zeus")
    os.makedirs(prod, exist_ok=True)
    with open(os.path.join(prod, "server.py"), "w", encoding="utf-8") as f:
        f.write("REALM = 'zeus'\n")
    cfg = dict(h.config)
    cfg["include_realms"] = True
    h2 = Hades(root=base, state_dir=h.state_dir,
               config={"include_realms": True,
                       "products": h.config.get("products", [])})
    found = h2.collect()
    zeus_files = [k for k, v in found.items() if v == "zeus"]
    if not zeus_files:
        return "registered realm not picked up: %r" % sorted(found)[:10]
    if any(v == "ghostrealm" for v in found.values()):
        return "nonexistent realm materialized out of thin air"
    wt = os.path.join(base, ".worktrees", "someone", "zeus", "evil.py")
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    with open(wt, "w", encoding="utf-8") as f:
        f.write("# duplicate checkout\n")
    if any(".worktrees" in k for k in h2.collect()):
        return "worktree copies leaked into the seal"
    return True


CHECKS = [
    ("seal counts + key birth", lambda h, b: check_seal_counts(h)),
    ("clean verify", lambda h, b: check_clean_verify(h)),
    ("modified detection", check_modified),
    ("missing detection", check_missing),
    ("restore + unregistered", check_restore_and_unregistered),
    ("ghost hunt (rebrand detection)", lambda h, b: check_ghosts(h)),
    ("watermark roundtrip", lambda h, b: check_watermark_roundtrip()),
    ("detect + forgery rejection", check_detect_and_forgery),
    ("audit chain integrity", check_audit_chain),
    ("forged seal rejection", check_forged_seal),
    ("fail-closed guard", check_guard),
    ("operator authority gate", check_authority_gate),
    ("realm expansion + worktree exclusion", check_realms_expansion),
]


def main():
    passed = 0
    failures = []
    with tempfile.TemporaryDirectory(prefix="hades-gate-") as base:
        build_fixture(base)
        h = Hades(root=base,
                  state_dir=os.path.join(base, "state"),
                  config=CONFIG)
        for name, fn in CHECKS:
            try:
                result = fn(h, base)
            except Exception as e:  # noqa: BLE001 - gate reports, never crashes
                result = "raised %s: %s" % (type(e).__name__, e)
            if result is True:
                passed += 1
                print("[ok]   %s" % name)
            else:
                failures.append(name)
                print("[FAIL] %s -> %s" % (name, result))
    total = len(CHECKS)
    print("\n%d/%d checks passed" % (passed, total))
    if failures:
        print("failing: %s" % ", ".join(failures))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
