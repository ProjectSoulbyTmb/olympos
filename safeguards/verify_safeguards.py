"""SAFEGUARDS verify - the gates that gate the gates.

Proves the tooling catches what it claims to catch, and nothing it
shouldn't. Runs against throwaway fixtures; never touches live trees.

    python safeguards/verify_safeguards.py     (exit 0 = all green)
"""

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def run_checker(paths, strict=False):
    args = [PY, os.path.join(HERE, "check.py")]
    if strict:
        args.append("--strict")
    return subprocess.run(args + paths, cwd=ROOT, capture_output=True,
                          text=True, timeout=120)


def fixture(files):
    outer = tempfile.mkdtemp(prefix="safeg-verify-")
    for rel, text in files.items():
        p = os.path.join(outer, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return outer


@check
def conflict_markers_detected():
    outer = fixture({"clash.md": "mine\n<<<<<<< HEAD\nours\n"
                                 ">>>>>>> branch\n"})
    r = run_checker([os.path.join(outer, "clash.md")])
    assert r.returncode != 0 and "merge marker" in r.stdout, r.stdout
    clean = fixture({"ok.md": "a\nb\n"})
    try:
        r = run_checker([os.path.join(clean, "ok.md")])
        assert r.returncode == 0 and "FAIL" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(clean, ignore_errors=True)
    shutil.rmtree(outer, ignore_errors=True)


@check
def secret_patterns_detected():
    outer = fixture({
        # PEM header assembled at runtime so this suite does not
        # trip the very scanner it verifies
        "leak.py": 'TOKEN = "ghp_' + "A" * 36 + '"\n',
        "key.pem": "-----BEGIN RSA PRIVATE " + "KEY-----\nabc\n",
        "aws.txt": "AKIA" + "B" * 16 + "\n",
    })
    files = [os.path.join(outer, n) for n in
             ("leak.py", "key.pem", "aws.txt")]
    for f in files:
        r = run_checker([f])
        assert r.returncode != 0, r.stdout
    assert "possible github-token" in run_checker([files[0]]).stdout
    shutil.rmtree(outer, ignore_errors=True)


@check
def benign_code_passes_clean():
    good = ('import os\n\n\nX = "sketchy words but no secrets: '
            'xoxo friendly sk8"\n\n\ndef only_once():\n'
            '    return {"json": True}\n')
    outer = fixture({"good.py": good})
    try:
        r = run_checker(["--strict", os.path.join(outer, "good.py")])
        assert r.returncode == 0 and "[FAIL]" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def dupdef_and_syntax_still_caught():
    outer = fixture({
        "dup.py": "def f():\n    pass\n\n\ndef f():\n    pass\n",
        "broken.py": "def x(:\n    pass\n",
        "bad.json": '{"a": 1,,}',
    })
    files = [os.path.join(outer, n) for n in
             ("dup.py", "broken.py", "bad.json")]
    for f in files:
        r = run_checker([f])
        assert r.returncode != 0, (f, r.stdout)
    shutil.rmtree(outer, ignore_errors=True)


@check
def oversize_warns_and_strict_fails():
    big = "x = 1\n" * (95 * 1024)          # ~570 KB > 512 KiB cap
    outer = fixture({"big.py": big, "small.py": "y = 2\n"})
    try:
        both = [os.path.join(outer, "big.py"),
                os.path.join(outer, "small.py")]
        r = run_checker(both)
        assert r.returncode == 0 and "[warn] oversize" in r.stdout, \
            r.stdout
        r = run_checker(["--strict"] + both)
        assert r.returncode != 0, "--strict must fail on warnings"
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def gate_orchestrator_parallel_timeout_report():
    gate = os.path.join(HERE, "gate.py")
    outer = tempfile.mkdtemp(prefix="safeg-gate-")
    try:
        # fake tree: one green suite, one failing suite, one hung suite
        for name, body in (
            ("alpha", "print('alpha ok')\n"),
            ("beta", "raise SystemExit(1)\n"),
            ("gamma", "import time; time.sleep(30)\n"),
        ):
            d = os.path.join(outer, name)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"verify_{name}.py"), "w",
                      encoding="utf-8") as fh:
                fh.write(body)
        import importlib.util
        spec = importlib.util.spec_from_file_location("gate", gate)
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        specs = {
            "alpha": {"cmd": [PY, "-c", "pass"], "cwd": outer},
            "beta": {"cmd": [PY, "-c", "raise SystemExit(1)"],
                     "cwd": outer},
            "gamma": {"cmd": [PY, "-c",
                              "import time; time.sleep(30)"],
                      "cwd": outer},
        }
        t0 = time.monotonic()
        results = {}
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            futs = {pool.submit(g.run_suite, n, s, 1.5): n
                    for n, s in specs.items()}
            for f in concurrent.futures.as_completed(futs):
                results[futs[f]] = f.result()
        wall = time.monotonic() - t0
        assert results["alpha"]["ok"] is True
        assert results["beta"]["ok"] is False
        assert results["gamma"]["ok"] is False \
            and "TIMEOUT" in results["gamma"]["tail"]
        assert wall < 10, f"timeout not enforced (wall {wall:.1f}s)"
        # report shape matches contract
        assert set(results["alpha"]) == {"suite", "ok", "secs", "tail"}
    finally:
        shutil.rmtree(outer, ignore_errors=True)


@check
def discovery_finds_real_suites():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gate", os.path.join(HERE, "gate.py"))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    suites = g.discover()
    expected = {"ratatosk", "vulcan", "zeus", "hades", "atlas"}
    missing = expected - set(suites)
    assert not missing, f"discovery missed: {sorted(missing)}"
    assert "safeguards" not in suites, "self-exclusion failed"


def main():
    print("=" * 64)
    print("SAFEGUARDS VERIFY - gates that gate the gates")
    print("=" * 64)
    failures = []
    for fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:              # noqa: BLE001 - verifier
            failures.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: {type(exc).__name__}: {exc}")
    print("-" * 64)
    ok = len(CHECKS) - len(failures)
    print(f"{ok}/{len(CHECKS)} checks green"
          + ("" if not failures else f" - FAILING: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
