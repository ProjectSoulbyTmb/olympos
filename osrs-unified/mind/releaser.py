import datetime
import os
import re
import subprocess
import sys


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, errors="replace")


def read_version(root):
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
    return m.group(1) if m else "0.0.0"


def write_version(root, version):
    path = os.path.join(root, "pyproject.toml")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r'(^version\s*=\s*")[^"]+(")', rf"\g<1>{version}\g<2>",
                  text, flags=re.M)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def bump(version, level):
    parts = [int(p) for p in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if level == "major":
        parts = [parts[0] + 1, 0, 0]
    elif level == "minor":
        parts = [parts[0], parts[1] + 1, 0]
    else:
        parts[2] += 1
    return ".".join(str(p) for p in parts)


def git_dirty(root):
    r = _git(root, "status", "--porcelain")
    return bool((r.stdout or "").strip())


def changelog_entries(root, since_tag=None):
    args = ["log", "--oneline", "-n", "20"]
    if since_tag:
        args = ["log", f"{since_tag}..HEAD", "--oneline"]
    r = _git(root, *args)
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    out = []
    for ln in lines:
        _, _, msg = ln.partition(" ")
        if msg.startswith("Release v") or msg.startswith("v"):
            continue
        out.append(f"- {msg}")
    return out[:10]


def changed_paths_summary(root, limit=8):
    r = _git(root, "status", "--porcelain")
    groups = {}
    order = []
    file_bullets = []
    for ln in (r.stdout or "").splitlines():
        if len(ln) < 4:
            continue
        code = ln[:2]
        path = ln[3:].strip().strip('"')
        if not path or path.startswith("OSRS-Suite.exe"):
            continue
        verb = "remove" if "D" in code else \
            "update" if "M" in code else "add"
        parts = re.split(r"[\\/]", path)
        if len(parts) == 1:
            if path not in file_bullets:
                file_bullets.append(f"- {verb} {path}")
            continue
        top = parts[0] or "root"
        key = f"{verb} {top}/"
        if key not in groups:
            groups[key] = set()
            order.append(key)
        if len(groups[key]) < 4:
            groups[key].add(parts[-1])
    out = list(file_bullets)
    for key in order[:limit]:
        names = sorted(groups[key])
        tail = f" (+{len(names)})" if len(names) == 4 else ""
        out.append(f"- {key} {', '.join(names)}{tail}")
    return out[:limit + len(file_bullets)]


def prepend_changelog(root, version, bullets):
    today = datetime.date.today().isoformat()
    path = os.path.join(root, "CHANGELOG.md")
    entry = [f"## {version} ({today})", ""]
    entry += bullets or ["- automated maintenance release by MIND"]
    entry += [""]
    with open(path, encoding="utf-8") as f:
        old = f.read()
    head = old.split("\n", 1)
    new = head[0] + "\n\n" + "\n".join(entry) + \
        ("\n" + head[1] if len(head) > 1 else "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


def build_artifacts(root, exe=True, log=print):
    py = sys.executable
    results = {}
    r = subprocess.run([py, "-m", "build"], cwd=root, capture_output=True,
                       text=True, errors="replace",
                       creationflags=subprocess.CREATE_NO_WINDOW)
    results["build"] = r.returncode == 0
    if not results["build"]:
        log("build failed:\n" + (r.stderr or "")[-2000:])
        return results
    if exe:
        r = subprocess.run(
            [py, "-m", "PyInstaller", "--onefile", "--noconsole",
             "--name", "OSRS-Suite",
             "--exclude-module", "torch", "--exclude-module", "numpy",
             "--exclude-module", "scipy", "--exclude-module", "pandas",
             os.path.join(root, "osrs_app.py")],
            cwd=root, capture_output=True, text=True, errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0:
            built = os.path.join(root, "dist", "OSRS-Suite.exe")
            import shutil
            shutil.move(built, os.path.join(root, "OSRS-Suite.exe"))
            results["exe"] = True
        else:
            results["exe"] = False
            log("pyinstaller failed:\n" + (r.stderr or "")[-1500:])
    for junk in ("build",):
        import shutil
        shutil.rmtree(os.path.join(root, junk), ignore_errors=True)
    return results


def release(root, level="patch", dry_run=False, do_build=True, log=print):
    plan = {"level": level}
    current = read_version(root)
    target = bump(current, level)
    plan["current"] = current
    plan["target"] = target
    tags = _git(root, "tag", "--list").stdout.split()
    latest_tag = sorted(tags)[-1] if tags else None
    dirty = git_dirty(root)
    bullets = changelog_entries(root, latest_tag)
    if not bullets and dirty:
        bullets = changed_paths_summary(root)
    plan["changelog"] = bullets
    plan["working_tree_dirty"] = dirty
    if dry_run:
        plan["dry_run"] = True
        return plan
    if not dirty and latest_tag == f"v{current}":
        plan["note"] = "nothing to release - tree clean at latest tag"
        return plan
    write_version(root, target)
    prepend_changelog(root, target, bullets)
    _git(root, "add", "-A")
    c = _git(root, "commit", "-m",
             f"Release v{target}: automated by MIND "
             f"({level} bump from {current})")
    if c.returncode != 0:
        plan["error"] = (c.stderr or "commit failed")[-500:]
        return plan
    _git(root, "tag", "-a", f"v{target}", "-m",
         f"osrs-unified {target}, released automatically by MIND")
    if do_build:
        plan["artifacts"] = build_artifacts(root, log=log)
    archive = os.path.join(os.path.dirname(root),
                           f"osrs-unified-v{target}-windows.zip")
    a = subprocess.run(
        ["git", "archive", "--format=zip",
         "--prefix=osrs-unified/", f"v{target}", "-o", archive],
        cwd=root, capture_output=True, text=True)
    plan["zip"] = archive if a.returncode == 0 else None
    plan["committed"] = True
    return plan
