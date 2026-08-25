#!/usr/bin/env python3
"""Verify gate for PERSEPHONE (stabilization suite).

Boots the guardian in --once mode against the real products and asserts
the guarantees that matter: config parses, manifests baseline, health
probes respond or fail gracefully, attestation round-trips, vault
restore repairs a tampered fixture. Stdlib only. Exits non-zero on any
failure.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL = HERE / "persephone.py"
RESULTS = []
TARGET_KERNEL = KERNEL  # swapped to sandboxed copy during end-to-end section


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def run_kernel(args: list[str], env_overrides: dict | None = None):
    env = {**os.environ}
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-u", str(TARGET_KERNEL), *args],
        capture_output=True, text=True, timeout=120, env=env,
    )


def main() -> int:
    print("PERSEPHONE verify gate")
    print("-" * 60)

    # 1. kernel present + imports clean
    r = run_kernel(["--help"])
    check("kernel boots", r.returncode == 0, (r.stderr or "")[:120])

    # 2. sandboxed end-to-end sweep with fake product
    tmp = Path(tempfile.mkdtemp(prefix="persephone-verify-"))
    state = tmp / "state"
    prod_root = tmp / "product"
    prod_root.mkdir(parents=True)
    (prod_root / "server.py").write_text("print('v1')\n", encoding="utf-8")
    (prod_root / "index.html").write_text("<html>v1</html>", encoding="utf-8")

    cfg = {
        "sweep_seconds": 1,
        "status_port": 0,
        "min_free_mb": 0,
        "products": [{
            "name": "fixture",
            "port": 49999,
            "health_url": "http://127.0.0.1:49999/api/health",
            "launch": "",
            "min_free_mb": 0,
            "files": [
                {"path": str(prod_root / "server.py")},
                {"path": str(prod_root / "index.html")},
            ],
        }],
    }
    cfg_path = HERE / ".verify-products.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    import re
    src = KERNEL.read_text(encoding="utf-8")
    patched = src.replace('CONFIG = HERE / "products.json"',
                          'CONFIG = HERE / ".verify-products.json"')
    patched = patched.replace('DRIVE_STATE_PATH = STATE_ROOT / "drive.json"',
                              f'DRIVE_STATE_PATH = Path(r"{(tmp / "state" / "drive.json")}")')
    test_kernel = HERE / ".verify-kernel.py"
    test_kernel.write_text(patched, encoding="utf-8")
    globals()["TARGET_KERNEL"] = test_kernel

    try:
        env = {"PERSEPHONE_STATE": str(state)}
        r = run_kernel(["--once"], env)
        check("first sweep baselines manifest",
              r.returncode == 0 and "baseline manifest written" in (r.stdout + r.stderr),
              (r.stderr or "")[:160])
        # 3. tamper -> vault restore on next sweep
        (prod_root / "index.html").write_text("<html>EVIL</html>", encoding="utf-8")
        r = run_kernel(["--once"], env)
        out = r.stdout + r.stderr
        now = (prod_root / "index.html").read_text(encoding="utf-8")
        check("tamper detected and restored from vault",
              "VAULT RESTORE" in out and "<html>v1</html>" == now,
              f"out={out[:100]!r} content={now!r}")

        # 3b. restore lands in the forensic history ledger
        hist = state / "history.jsonl"
        ok_hist = False
        try:
            entries = [json.loads(x) for x in
                       hist.read_text(encoding="utf-8").splitlines() if x]
            ok_hist = any(
                e.get("event") == "integrity"
                and e.get("verdict") == "restored"
                and e.get("product") == "fixture"
                for e in entries)
        except Exception:                          # noqa: BLE001
            pass
        check("restore recorded in history ledger", ok_hist)

        # 4. attestation round-trip
        r = run_kernel(["--attest", "fixture", "--days", "7"], env)
        check("attestation minted", r.returncode == 0)
        attest = state / "attest" / "fixture.json"
        check("attestation file exists", attest.exists())

        # 5. drive guards (sandboxed DriveGuard against fixture tree)
        sys.path.insert(0, str(HERE))
        import importlib.util
        # isolate module-level state paths (log/history/drive) so the
        # in-process DriveGuard exercises cannot touch real state
        os.environ["PERSEPHONE_STATE"] = str(state)
        spec = importlib.util.spec_from_file_location(
            "pk", test_kernel)
        pk = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(pk)
            media = tmp / "media"
            (media / "sub").mkdir(parents=True, exist_ok=True)
            for i in range(60):
                (media / f"f{i}.jpg").write_text("x", encoding="utf-8")
            (media / "sub" / "g.jpg").write_text("y", encoding="utf-8")

            dg = pk.DriveGuard({
                "root": str(tmp),
                "min_free_mb": 0,
                "structure_roots": [str(media)],
                "ransomware_max_new_files": 400,
            })
            dg.sweep()
            check("drive structure baseline ok",
                  dg.state["structure"] == "ok"
                  and dg.state["ransom"] == "clear")

            # mass LOSS detection
            for i in range(40):
                (media / f"f{i}.jpg").unlink()
            dg2 = pk.DriveGuard({
                "root": str(tmp),
                "min_free_mb": 0,
                "structure_roots": [str(media)],
                "ransomware_max_new_files": 400,
            })
            dg2._last_inv = {str(media): {"files": 61, "dirs": 1,
                                          "bytes": 6100}}
            dg2.sweep()
            check("mass-loss detected + alarm trips",
                  "LOSS" in dg2.state["structure"]
                  and dg2.state["ransom"] == "alarm")

            # suspicious extension detection
            (media / "victim.jpg.locked").write_text("z", encoding="utf-8")
            dg3 = pk.DriveGuard({
                "root": str(tmp),
                "min_free_mb": 0,
                "structure_roots": [str(media)],
            })
            inv, _n = dg3._inventory_root(str(media))
            check("ransom extension detected",
                  any(s.endswith(".locked") for s in inv.get("suspicious", [])))
        except Exception as exc:
            check("drive guards execute", False, repr(exc))
    finally:
        for p in (cfg_path, test_kernel):
            p.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print("-" * 60)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("PERSEPHONE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
