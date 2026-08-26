"""verify_mind - the green/red gate for the MIND repository.

Run: python verify.py   (exit 0 = green, 1 = any failure)

Three rings:
  1. unittest suite          tests/ - formal, hermetic
  2. module selfchecks       python -m mind selfcheck
  3. dress rehearsal         python -m mind demo (mock OBS end to end)
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def ring(name, argv):
    print(f"\n=== {name} ===")
    proc = subprocess.run([sys.executable] + argv,
                          cwd=HERE,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-12:])
    print(tail if tail.strip() else "(silent)")
    if proc.returncode != 0:
        FAILURES.append(name)
        print(f"--- {name}: RED (exit {proc.returncode})")
    else:
        print(f"--- {name}: ok")


def main() -> int:
    print(f"verify_mind - gate for {os.path.basename(HERE)}")
    ring("unittest suite",
         ["-m", "unittest", "discover", "-s", "tests", "-v"])
    ring("module selfchecks", ["-m", "mind", "selfcheck"])
    ring("dress rehearsal", ["-m", "mind", "demo"])

    if FAILURES:
        print(f"\nverify_mind: RED ({len(FAILURES)} failing rings): "
              f"{', '.join(FAILURES)}")
        return 1
    print("\nverify_mind: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
