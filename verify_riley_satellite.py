#!/usr/bin/env python3
"""verify_riley_satellite - portable gate for the deployed RILEY studio.

    python verify_riley_satellite.py            # fast: presence + health
    python verify_riley_satellite.py --deep     # full D:/riley 67-check suite

The satellite kernel lives outside this repo (D:/riley), so this gate
degrades honestly instead of failing on machines without it:

  * D:/riley missing          -> SKIP (exit 0): nothing deployed here
  * studio dark               -> SKIP (exit 0): liveness is PERSEPHONE's
                                 job (relaunch via launch_riley.bat),
                                 not a verify gate's
  * studio answering          -> assert /api/info contract + version
  * --deep                    -> additionally run D:/riley/verify_riley.py
                                 (boots its own throwaway fixture)

Exit code is the verdict: 0 = stable-or-honestly-absent, non-zero = fix
me. Stdlib only.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SATELLITE_ROOT = os.environ.get("RILEY_HOME", "D:\\riley")
SATELLITE_URL = os.environ.get("RILEY_URL", "http://127.0.0.1:43907")
HEALTH_TIMEOUT_S = 4.0
DEEP_TIMEOUT_S = 600


def info():
    try:
        with urllib.request.urlopen(SATELLITE_URL + "/api/info",
                                    timeout=HEALTH_TIMEOUT_S) as r:
            doc = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:                       # noqa: BLE001 - dark
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(doc, dict) or doc.get("ok") is not True:
        return None, "contract violation: ok!=true"
    data = doc.get("data") or {}
    if not isinstance(data, dict) or not data.get("version"):
        return None, "contract violation: no version in data"
    return data, None


def main() -> int:
    ap = argparse.ArgumentParser(prog="verify_riley_satellite")
    ap.add_argument("--deep", action="store_true",
                    help="run the satellite's full verify suite")
    args = ap.parse_args()

    if not os.path.isdir(SATELLITE_ROOT):
        print(f"SKIP {SATELLITE_ROOT} not deployed on this machine")
        return 0

    if args.deep:
        suite = os.path.join(SATELLITE_ROOT, "verify_riley.py")
        if not os.path.isfile(suite):
            print(f"FAIL deep suite missing: {suite}")
            return 1
        print(f"deep: running {suite} ...")
        try:
            r = subprocess.run([sys.executable, "-u", suite],
                               capture_output=True, text=True,
                               timeout=DEEP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            print("FAIL deep suite timed out")
            return 1
        tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
        print(tail[0])
        if r.returncode != 0:
            print("FAIL deep suite red")
            return 1
        print("OK   deep suite green")

    data, why = info()
    if data is None:
        print(f"SKIP studio dark ({why}) - liveness is PERSEPHONE's job")
        return 0
    print(f"OK   riley v{data['version']} answers at {SATELLITE_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
