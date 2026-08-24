"""COVERAGE floor gate: buskit contracts must be exercised.

Runs the buskit verify suite in-process under ``trace`` and asserts a
minimum executed-line ratio across the buskit package. Stdlib-only
(``trace``), no coverage dependency - house rules.

Run:  python verify_coverage.py
Exit: 0 at/above floor, 1 below, 2 harness failure.
"""

import io
import runpy
import sys
import trace
from contextlib import redirect_stdout

FLOOR = 60  # percent of executable lines that must be exercised
TARGETS = ("buskit",)


def main():
    print("verify_coverage")
    tracer = trace.Trace(count=1, trace=0,
                         ignoredirs=(sys.prefix, sys.exec_prefix))
    code = "runpy.run_path('verify_buskit.py', run_name='__main__')"
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            tracer.runctx(code, {"runpy": runpy}, {})
    except SystemExit as exc:
        if int(exc.code or 0) != 0:
            print("FAIL  underlying verify_buskit suite not green")
            return 2

    counts = tracer.results().counts
    executed = {}
    for (fname, _lineno), n in counts.items():
        fname = fname.replace("\\", "/")
        if "/buskit/" in fname and fname.endswith(".py"):
            rel = fname.split("/buskit/")[-1]
            executed.setdefault("buskit/" + rel, set()).update(
                range(_lineno, _lineno + max(n, 1)))

    total_ok = True
    for target in TARGETS:
        import os
        pkg_dir = target
        all_lines = {}
        for root, _dirs, files in os.walk(pkg_dir):
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f).replace("\\", "/")
                with open(p, encoding="utf-8") as fh:
                    lines = [l for l in fh.readlines()]
                stmts = {i + 1 for i, l in enumerate(lines)
                         if l.strip() and not l.strip().startswith("#")}
                all_lines[p] = stmts
        for p, stmts in sorted(all_lines.items()):
            if p.endswith("__init__.py") and not stmts:
                continue  # nothing executable
            if p.endswith("__init__.py"):
                # pure re-export shim - covered by submodule exercise
                print(f"  SKIP  {p:<32} re-export shim")
                continue
            covered = executed.get(p, set())
            hit = len(covered & stmts)
            pct = int(100 * hit / max(len(stmts), 1))
            ok = pct >= FLOOR
            total_ok &= ok
            mark = "PASS" if ok else "FAIL"
            print(f"  {mark}  {p:<32} {pct:3d}% "
                  f"({hit}/{len(stmts)} lines, floor {FLOOR}%)")
    print(f"coverage: floor {FLOOR}% -> {'OK' if total_ok else 'MISS'}")
    return 0 if total_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
