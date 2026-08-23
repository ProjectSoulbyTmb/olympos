import os
import subprocess
import sys


def compile_all(root):
    proc = subprocess.run(
        [sys.executable, "-m", "compileall", "-q",
         "agent", "game", "server", "algo", "envs", "rsps_adapter",
         "tools", "mind", "bench.py", "train.py", "evaluate.py",
         "osrs_cli.py", "osrs_app.py"],
        cwd=root, capture_output=True, text=True, errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW)
    return {"ok": proc.returncode == 0,
            "output": (proc.stderr or "")[-2000:]}


def build_wheel(root, log=None):
    proc = subprocess.run(
        [sys.executable, "-m", "build"], cwd=root, capture_output=True,
        text=True, errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW)
    ok = proc.returncode == 0
    if log:
        log("wheel build " + ("ok" if ok else
                              "failed:\n" + (proc.stderr or "")[-1500:]))
    dist = os.path.join(root, "dist")
    artifacts = sorted(os.listdir(dist)) if os.path.isdir(dist) else []
    return {"ok": ok, "artifacts": artifacts}


def build_exe(root, log=None):
    import shutil
    proc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole",
         "--name", "OSRS-Suite",
         "--exclude-module", "torch", "--exclude-module", "numpy",
         "--exclude-module", "scipy", "--exclude-module", "pandas",
         os.path.join(root, "osrs_app.py")],
        cwd=root, capture_output=True, text=True, errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW)
    ok = proc.returncode == 0
    moved = False
    if ok:
        src = os.path.join(root, "dist", "OSRS-Suite.exe")
        if os.path.exists(src):
            shutil.move(src, os.path.join(root, "OSRS-Suite.exe"))
            moved = True
    shutil.rmtree(os.path.join(root, "build"), ignore_errors=True)
    if log:
        log("exe build " + ("ok" if ok else
                            "failed:\n" + (proc.stderr or "")[-1200:]))
    return {"ok": ok and moved}


def selftest_exe(root):
    exe = os.path.join(root, "OSRS-Suite.exe")
    if not os.path.exists(exe):
        return {"ok": False, "output": "OSRS-Suite.exe missing"}
    try:
        proc = subprocess.run([exe, "--selftest"], cwd=root,
                              capture_output=True, text=True,
                              errors="replace", timeout=60)
        return {"ok": proc.returncode == 0,
                "output": (proc.stdout or proc.stderr or "")[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "selftest timed out"}


def build_all(root, log=None, exe=True):
    results = {"compile": compile_all(root)}
    if not results["compile"]["ok"]:
        if log:
            log("aborting builds - source does not compile")
        results["wheel"] = {"ok": False}
        return results
    results["wheel"] = build_wheel(root, log=log)
    if exe:
        results["exe"] = build_exe(root, log=log)
        results["selftest"] = selftest_exe(root)
    return results
