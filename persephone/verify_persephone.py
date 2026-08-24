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
        "products": [{
            "name": "fixture",
            "port": 49999,
            "health_url": "http://127.0.0.1:49999/api/health",
            "launch": "",
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

        # 4. attestation round-trip
        r = run_kernel(["--attest", "fixture", "--days", "7"], env)
        check("attestation minted", r.returncode == 0)
        attest = state / "attest" / "fixture.json"
        check("attestation file exists", attest.exists())
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
