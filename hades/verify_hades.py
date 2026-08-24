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
