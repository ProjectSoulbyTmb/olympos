#!/usr/bin/env python3
"""PERSEPHONE — standalone guardian layer for offline products.

Watches registered products (APHRODITE, RILEY) and enforces eight
guards per product:

  INTEGRITY   SHA-256 manifest of protected files; tamper -> vault restore.
  LIVENESS    loopback health probe; dead process -> attested relaunch.
  CRASHLOOP   circuit breaker: too many failed relaunches -> stand down.
  LOOPBACK    listener on a product port must bind the expected address.
  DATA        periodic snapshot of user-state dirs (ratings, tags, jobs);
              manual restore via --restore-data.
  DISK        free-space floor on the state drive; vault writes pause
              below it.
  SELF        guardian watches its own kernel + config hashes.
  ATTESTATION HMAC'd offline entitlement; unattested products are not
              resurrected.

Housekeeping: LOG guard rotates the log and trims history.

Design rules (inherited from the Olympos watchdogs):
  * loopback-only; zero network egress; stdlib only
  * never fight a foreign service that owns a product's port
  * never silently auto-restore user data (manual --restore-data only)
  * all state under %LOCALAPPDATA%\\PERSEPHONE (log, vault, attest)

CLI:
  python persephone.py                          run guardian loop
  pythonpersephone.py --once                   single sweep, exit
  python persephone.py --attest NAME --days N  mint/renew entitlement
  python persephone.py --promote NAME          re-baseline after legit upgrade
  python persephone.py --restore-data NAME     restore newest data snapshot
  python persephone.py --status                print current state table
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
KERNEL_PATH = Path(__file__).resolve()
CONFIG = HERE / ".verify-products.json"

STATE_ROOT = Path(os.environ.get("PERSEPHONE_STATE", "D:\\persephone\\state"))
VAULT_DIR = STATE_ROOT / "vault"
DATA_VAULT = STATE_ROOT / "vault" / "data"
ATTEST_DIR = STATE_ROOT / "attest"
LOG_PATH = STATE_ROOT / "persephone.log"
HISTORY_PATH = STATE_ROOT / "history.jsonl"
SELF_HASH_PATH = STATE_ROOT / "self.json"

SECRET_PATH = STATE_ROOT / ".secret"
SWEEP_SECONDS_DEFAULT = 30
MAX_BACKOFF_SECONDS = 600
CRASHLOOP_WINDOW_S = 600          # 10 min
CRASHLOOP_MAX_RELAUNCHES = 4      # within window -> breaker trips
DATA_SNAPSHOT_INTERVAL_S = 3600   # hourly
DATA_SNAPSHOT_KEEP = 5            # newest N snapshots retained
LOG_ROTATE_BYTES = 5 * 1024 * 1024
HISTORY_KEEP_LINES = 500


# ---------------------------------------------------------------- logging

def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_ROTATE_BYTES:
            rotated = LOG_PATH.with_suffix(".1.log")
            if rotated.exists():
                rotated.unlink()
            LOG_PATH.replace(rotated)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def record_history(entry: dict) -> None:
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []                       # first event bootstraps file
        if len(lines) >= HISTORY_KEEP_LINES:
            lines = lines[-(HISTORY_KEEP_LINES - 1):]
        lines.append(json.dumps(entry, ensure_ascii=False))
        tmp = HISTORY_PATH.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, HISTORY_PATH)
    except Exception:
        pass


# ---------------------------------------------------------------- secret

def load_secret() -> bytes:
    """Stable per-machine key for attestation HMACs."""
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_PATH.exists():
        return SECRET_PATH.read_bytes().strip()
    key = hashlib.sha256(
        f"persephone:{os.environ.get('COMPUTERNAME', 'local')}:{time.time_ns()}".encode()
    ).hexdigest().encode()
    SECRET_PATH.write_bytes(key)
    return key


SECRET = b""  # set in main()


def _vpath(product: str, path_str: str) -> str:
    return path_str.replace(":", "_").replace("\\", "__").replace("/", "__")


def _free_space_mb(path: Path) -> int:
    try:
        return shutil.disk_usage(str(path.anchor or str(path))).free // (1024 * 1024)
    except Exception:
        return 1 << 30


# ---------------------------------------------------------------- integrity

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(files: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in files:
        p = Path(spec["path"])
        if p.exists():
            out[spec["path"]] = sha256_file(p)
    return out


def vault_dir_for(product: str) -> Path:
    d = VAULT_DIR / product
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_to_vault(prod: dict) -> int:
    """Copy last-known-good copies of protected files into the vault."""
    n = 0
    vd = vault_dir_for(prod["name"])
    for spec in prod.get("files", []):
        src = Path(spec["path"])
        dst = vd / _vpath(prod["name"], spec["path"])
        if src.exists():
            shutil.copy2(src, dst)
            n += 1
    return n


def baseline_manifest(prod: dict) -> None:
    mf_path = vault_dir_for(prod["name"]) / "manifest.json"
    current = build_manifest([s for s in prod.get("files", [])])
    mf_path.write_text(json.dumps(current, indent=1), encoding="utf-8")


def check_integrity(prod: dict, allow_writes: bool = True) -> tuple[str, list[str]]:
    """Returns (verdict, problems). verdict: ok|restored|novault|missing."""
    mf_path = vault_dir_for(prod["name"]) / "manifest.json"
    files = [spec for spec in prod.get("files", []) if Path(spec["path"]).exists()]
    if not files:
        return "missing", []
    current = build_manifest(files)

    if not mf_path.exists():
        if not allow_writes:
            return "unbaselined", []
        mf_path.write_text(json.dumps(current, indent=1), encoding="utf-8")
        snapshot_to_vault(prod)
        log(f"{prod['name']}: baseline manifest written ({len(current)} files)")
        return "ok", []

    known = json.loads(mf_path.read_text(encoding="utf-8"))
    tampered = [p for p, h in current.items() if known.get(p) not in (None, h)]
    missing = [spec["path"] for spec in files if spec["path"] not in current]
    problems = tampered + missing
    if not problems:
        return "ok", []

    restored: list[str] = []
    vd = vault_dir_for(prod["name"])
    for path_str in problems:
        vfile = vd / _vpath(prod["name"], path_str)
        target = Path(path_str)
        if allow_writes and vfile.exists():
            shutil.copy2(vfile, target)
            current[path_str] = sha256_file(target)
            restored.append(path_str)
            log(f"{prod['name']}: VAULT RESTORE {target.name}")
        elif not allow_writes:
            restored.append(path_str)  # deferred until disk recovers
        else:
            log(f"{prod['name']}: TAMPERED, no vault copy: {target}")
    if allow_writes:
        mf_path.write_text(json.dumps({**known, **current}, indent=1),
                           encoding="utf-8")
    if restored and allow_writes:
        return "restored", problems
    if restored and not allow_writes:
        return "pending-disk", problems
    return "novault", problems


# ---------------------------------------------------------------- liveness

def probe_health(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def listening_addresses(port: int) -> list[str]:
    """Local addresses of sockets LISTENing on port (netstd parsing)."""
    addrs: list[str] = []
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "TCP" and parts[3] == "LISTENING":
                local = parts[1]
                if local.rsplit(":", 1)[-1] == str(port):
                    addrs.append(local.rsplit(":", 1)[0])
    except Exception:
        pass
    return sorted(set(addrs))


def port_owner_is_foreign(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch(prod: dict) -> bool:
    launcher = prod.get("launch")
    if not launcher or not Path(launcher).exists():
        log(f"{prod['name']}: no launcher configured, cannot resurrect")
        return False
    flags = prod.get("launch_flags", [])
    try:
        subprocess.Popen(
            [launcher, *flags],
            cwd=str(Path(launcher).parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log(f"{prod['name']}: relaunched via {Path(launcher).name}")
        return True
    except Exception as exc:
        log(f"{prod['name']}: launch failed: {exc}")
        return False


# ---------------------------------------------------------------- attestation

def attestation_path(product: str) -> Path:
    ATTEST_DIR.mkdir(parents=True, exist_ok=True)
    return ATTEST_DIR / f"{product}.json"


def mint_attestation(product: str, days: int) -> dict:
    payload = {
        "product": product,
        "machine": os.environ.get("COMPUTERNAME", "local"),
        "expires": time.strftime("%Y-%m-%d", time.gmtime(time.time() + days * 86400)),
    }
    body = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    doc = {"payload": payload, "sig": sig}
    attestation_path(product).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    log(f"{product}: attestation minted, expires {payload['expires']}")
    return doc


def attestation_valid(product: str) -> bool:
    p = attestation_path(product)
    if not p.exists():
        return False
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        body = json.dumps(doc["payload"], sort_keys=True).encode()
        good = hmac.compare_digest(
            hmac.new(SECRET, body, hashlib.sha256).hexdigest(), doc["sig"])
        exp = time.strptime(doc["payload"]["expires"], "%Y-%m-%d")
        return good and time.mktime(exp) >= time.time()
    except Exception:
        return False


# ---------------------------------------------------------------- data guard

def data_snapshot(prod: dict) -> int:
    """Timestamped snapshot of user-state dirs; keeps newest DATA_SNAPSHOT_KEEP."""
    name = prod["name"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest_root = DATA_VAULT / name / stamp
    n = 0
    for raw in prod.get("data_dirs", []):
        src = Path(os.path.expandvars(raw))
        if not src.exists():
            continue
        dest = dest_root / _vpath(name, str(src))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("*.lock"))
        n += 1
    if n:
        # prune older snapshots
        snaps = sorted((DATA_VAULT / name).iterdir(), reverse=True)
        for old in snaps[DATA_SNAPSHOT_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
        log(f"{name}: data snapshot {stamp} ({n} dirs)")
    return n


def restore_latest_data(prod: dict) -> bool:
    name = prod["name"]
    root = DATA_VAULT / name
    if not root.exists():
        return False
    snaps = sorted(root.iterdir(), reverse=True)
    if not snaps:
        return False
    latest = snaps[0]
    for snap_dir in latest.iterdir():
        orig_rel = snap_dir.name.replace("__", "\\")
        if ":" not in orig_rel:
            orig_rel = orig_rel[0] + ":" + orig_rel[1:] if len(orig_rel) > 1 else orig_rel
        target = Path(orig_rel)
        if target.exists():
            backup = target.with_name(target.name + ".pre-restore")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            shutil.move(str(target), str(backup))
        shutil.copytree(snap_dir, target)
        log(f"{name}: data restored {target} (prior saved as .pre-restore)")
    return True


# ---------------------------------------------------------------- self guard

def self_hashes() -> dict[str, str]:
    out = {"kernel": "", "config": ""}
    if KERNEL_PATH.exists():
        out["kernel"] = sha256_file(KERNEL_PATH)
    if CONFIG.exists():
        out["config"] = sha256_file(CONFIG)
    return out


def self_check(baseline: dict) -> str:
    cur = self_hashes()
    if cur == baseline:
        return "ok"
    if baseline.get("kernel") == "":
        return "unseeded"
    return "drift"


# ---------------------------------------------------------------- drive guard

RANSOM_EXTENSIONS = {
    ".locked", ".encrypted", ".crypt", ".enc", ".wcry", ".onion",
    ".cerber", ".locky", ".zepto", ".crypz", ".cryptolocker",
}
INVENTORY_INTERVAL_S = 3600          # hourly full inventory
STRUCTURE_MAX_ENTRIES = 200_000      # safety cap per root
MASS_DELTA_FRACTION = 0.10           # >10% file-count delta = mass change
DRIVE_STATE_PATH = Path(r"C:\Users\Earth949\AppData\Local\Temp\persephone-verify-tafhsmc2\state\drive.json")


class DriveGuard:
    """Drive-level guards for a whole volume (e.g. D:\\).

    DRIVE      mounted + free-space floor.
    HEALTH     SMART status of physical disks (cached, refreshed hourly).
    STRUCTURE  lightweight inventories of key roots; flags mass
               additions/deletions without hashing media contents.
    RANSOM     burst detector: suspicious extensions or extreme churn
               freezes all guardian relaunches until --clear-alarm.
    """

    def __init__(self, cfg: dict):
        self.root = cfg.get("root", "D:\\")
        self.min_free_mb = int(cfg.get("min_free_mb", 5120))
        self.roots = cfg.get("structure_roots", [])
        self.max_new_files = int(cfg.get("ransomware_max_new_files", 400))
        self.state = {"drive": "?", "free": "-", "health": "?",
                      "structure": "?", "ransom": "clear", "last_inventory": "-"}
        self._last_inv: dict[str, dict] = {}
        self._last_health_check = 0.0
        self._load()

    def _load(self) -> None:
        try:
            if DRIVE_STATE_PATH.exists():
                doc = json.loads(DRIVE_STATE_PATH.read_text(encoding="utf-8"))
                self.state.update(doc.get("state", {}))
                self._last_inv = doc.get("inventory", {})
        except Exception:
            pass

    def _save(self) -> None:
        try:
            STATE_ROOT.mkdir(parents=True, exist_ok=True)
            DRIVE_STATE_PATH.write_text(json.dumps({
                "state": self.state, "inventory": self._last_inv,
            }, indent=1), encoding="utf-8")
        except Exception:
            pass

    def g_drive(self) -> bool:
        root = Path(self.root)
        ok = root.exists()
        free = _free_space_mb(root) if ok else 0
        self.state["drive"] = "ok" if ok else "MISSING"
        self.state["free"] = f"{free}MB" if ok else "-"
        if ok and free < self.min_free_mb:
            log(f"DRIVE GUARD: {self.root} low on space "
                f"({free}MB < {self.min_free_mb}MB)")
            self.state["drive"] = f"low({free}MB)"
        return ok

    def g_health(self) -> None:
        now = time.time()
        if now - self._last_health_check < INVENTORY_INTERVAL_S:
            return
        self._last_health_check = now
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PhysicalDisk | Select-Object -ExpandProperty "
                 "HealthStatus"],
                capture_output=True, text=True, timeout=60).stdout
            statuses = [s.strip() for s in out.splitlines() if s.strip()]
            bad = [s for s in statuses if s.lower() not in ("healthy",)]
            self.state["health"] = ("ALERT:" + ",".join(bad)) if bad else \
                f"ok({len(statuses)} disks)"
            if bad:
                log(f"HEALTH GUARD: disk health ALERT {bad}")
                record_history({"product": "drive", "event": "health-alert",
                                "statuses": bad})
        except Exception as exc:
            self.state["health"] = f"unknown({exc})"

    def _inventory_root(self, root_str: str,
                        budget_s: float = 120.0) -> tuple[dict, int]:
        """Count files/dirs/bytes under root without following links.

        Junctions/symlinks are skipped (cycle-proof); hard wall-clock
        budget keeps pathological trees from hanging sweeps.
        """
        import stat as stat_mod
        REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        files = dirs = 0
        total_bytes = 0
        scanned = 0
        suspicious: list[str] = []
        deadline = time.time() + budget_s

        def onerror(_exc):
            pass

        base = Path(root_str)
        try:
            base_st = base.stat(follow_symlinks=False)
            if stat_mod.S_ISLNK(base_st.st_mode) or \
                    getattr(base_st, "st_file_attributes", 0) & REPARSE:
                return {"files": 0, "dirs": 0, "bytes": 0,
                        "suspicious": []}, 0
        except OSError:
            return {"files": 0, "dirs": 0, "bytes": 0, "suspicious": []}, 0

        stack = [str(base)]
        while stack:
            if time.time() > deadline:
                break
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        scanned += 1
                        if scanned > STRUCTURE_MAX_ENTRIES:
                            stack.clear()
                            break
                        try:
                            st = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if getattr(st, "st_file_attributes", 0) & REPARSE:
                            continue  # junction/symlink: never descend
                        if entry.is_dir(follow_symlinks=False):
                            dirs += 1
                            stack.append(entry.path)
                        else:
                            files += 1
                            total_bytes += st.st_size
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in RANSOM_EXTENSIONS and len(suspicious) < 20:
                                suspicious.append(entry.path)
            except (PermissionError, FileNotFoundError, OSError):
                continue
        return {"files": files, "dirs": dirs, "bytes": total_bytes,
                "suspicious": suspicious}, scanned

    def g_structure(self, allow_writes: bool = True) -> None:
        now = time.time()
        # interval check is per-guardian; caller paces via last marker file
        findings = []
        total_scanned = 0
        for root_str in self.roots:
            inv, scanned = self._inventory_root(root_str)
            total_scanned += scanned
            prev = self._last_inv.get(root_str)
            suspicious = inv.pop("suspicious", [])
            if suspicious and self.state["ransom"] != "alarm":
                findings.append(f"suspicious-ext:{root_str}")
                log(f"RANSOM GUARD: suspicious extensions in {root_str}: "
                    f"{suspicious[:5]}")
            if prev:
                pf, cf = prev.get("files", 0), inv["files"]
                if pf > 50:  # ignore tiny roots
                    delta = abs(cf - pf) / max(pf, 1)
                    if delta > MASS_DELTA_FRACTION:
                        kind = "growth" if cf > pf else "LOSS"
                        findings.append(f"mass-{kind}:{root_str} "
                                        f"({pf}->{cf})")
                        log(f"STRUCTURE GUARD: mass {kind} at {root_str}: "
                            f"{pf} -> {cf} files")
            self._last_inv[root_str] = inv
        if total_scanned >= STRUCTURE_MAX_ENTRIES:
            log(f"STRUCTURE GUARD: scan cap hit ({total_scanned} entries); "
                f"inventory partial")
        if findings:
            self.state["structure"] = ";".join(findings)[:120]
            if any(f.startswith(("mass-LOSS", "suspicious-ext"))
                   for f in findings):
                if allow_writes:
                    self.trip_ransom(findings)
        else:
            self.state["structure"] = "ok"
        self.state["last_inventory"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if allow_writes:
            self._save()

    def trip_ransom(self, findings: list[str]) -> None:
        self.state["ransom"] = "alarm"
        log(f"RANSOM GUARD: ALARM - guardian relaunches FROZEN. "
            f"Findings: {'; '.join(findings)}. Resolve manually, then run "
            f"--clear-alarm")
        record_history({"product": "drive", "event": "ransom-alarm",
                        "findings": findings})
        self._save()

    def sweep(self) -> bool:
        """One drive sweep. Returns True if relaunches are allowed."""
        ok = self.g_drive()
        if ok:
            self.g_health()
            now = time.time()
            if now - getattr(self, "_last_structure", 0.0) >= INVENTORY_INTERVAL_S:
                self._last_structure = now
                self.g_structure(allow_writes=True)
        return self.state["ransom"] == "clear"


# ---------------------------------------------------------------- kernel

class Guardian:
    def __init__(self, products: list[dict], sweep_seconds: int):
        self.products = products
        self.sweep_seconds = sweep_seconds
        self.self_baseline = {}
        self.relaunch_times: dict[str, list[float]] = {p["name"]: [] for p in products}
        self.last_data_snap: dict[str, float] = {p["name"]: 0.0 for p in products}
        self.state: dict[str, dict] = {}
        for p in products:
            self.state[p["name"]] = {
                "integrity": "?", "alive": None, "attested": None,
                "loopback": "?", "disk": "?", "crashloop": "clear",
                "data_last": "-", "fails": 0, "next_try": 0.0,
                "last_action": "-",
            }
        self._httpd = None

    # ---- guards ----

    def g_disk(self, prod: dict) -> bool:
        """True if writes allowed."""
        floor = int(prod.get("min_free_mb",
                             self._cfg_global("min_free_mb", 2048)))
        free = _free_space_mb(STATE_ROOT)
        ok = free >= floor
        st = self.state[prod["name"]]
        newval = "ok" if ok else f"low({free}MB<{floor}MB)"
        if st["disk"] != newval and not ok:
            log(f"{prod['name']}: DISK LOW {free}MB free, floor {floor}MB - "
                f"vault writes paused")
        st["disk"] = newval
        return ok

    def _cfg_global(self, key: str, default):
        return getattr(self, "_globals", {}).get(key, default)

    def g_crashloop_allow(self, name: str, now: float) -> bool:
        window = [t for t in self.relaunch_times[name]
                  if now - t <= CRASHLOOP_WINDOW_S]
        self.relaunch_times[name] = window
        if len(window) >= CRASHLOOP_MAX_RELAUNCHES:
            if self.state[name]["crashloop"] == "clear":
                log(f"{name}: CRASH-LOOP BREAKER TRIPPED "
                    f"({len(window)} relaunches/{CRASHLOOP_WINDOW_S}s) - standing down")
                self.state[name]["crashloop"] = "tripped"
            return False
        return True

    def g_loopback(self, prod: dict) -> None:
        expect = prod.get("listen", "127.0.0.1")
        addrs = listening_addresses(prod["port"])
        st = self.state[prod["name"]]
        if not addrs:
            st["loopback"] = "no-listener"
            return
        bad = [a for a in addrs if a != expect]
        if bad:
            st["loopback"] = f"violation:{','.join(bad)}"
            log(f"{prod['name']}: LOOPBACK VIOLATION - port {prod['port']} "
                f"bound on {bad}, expected {expect}")
            record_history({"product": prod["name"],
                            "event": "loopback-violation", "addrs": bad})
        else:
            st["loopback"] = "ok"

    def g_data(self, prod: dict, allow_writes: bool) -> None:
        name = prod["name"]
        if not prod.get("data_dirs"):
            return
        now = time.time()
        if now - self.last_data_snap[name] < DATA_SNAPSHOT_INTERVAL_S:
            return
        if not allow_writes:
            return
        if data_snapshot(prod):
            self.last_data_snap[name] = now
            self.state[name]["data_last"] = time.strftime("%H:%M:%S")

    # ---- core sweep ----

    def sweep_product(self, prod: dict) -> None:
        name = prod["name"]
        st = self.state[name]
        actions: list[str] = []

        allow_writes = self.g_disk(prod)
        verdict, problems = check_integrity(prod,
                                             allow_writes=allow_writes)
        st["integrity"] = verdict
        if verdict in ("restored", "novault", "pending-disk"):
            actions.append(f"integrity={verdict}")
            record_history({"product": name, "event": "integrity",
                            "verdict": verdict, "files": problems[:12]})

        self.g_data(prod, allow_writes)

        attested = attestation_valid(name)
        if st["attested"] != attested:
            log(f"{name}: attestation {'valid' if attested else 'MISSING/EXPIRED'}")
        st["attested"] = attested

        alive = probe_health(prod["health_url"])
        st["alive"] = alive
        now = time.time()

        if alive:
            if st["fails"]:
                log(f"{name}: healthy again after {st['fails']} failed sweeps")
            if st["crashloop"] == "tripped":
                log(f"{name}: crash-loop cleared (healthy)")
                st["crashloop"] = "clear"
            st["fails"] = 0
            st["last_action"] = ";".join(actions) or "ok"
        elif now < st["next_try"]:
            st["last_action"] = "backoff"
            return
        else:
            if not attested:
                st["last_action"] = "down:unattested"
                st["next_try"] = now + MAX_BACKOFF_SECONDS
                log(f"{name}: DOWN but unattested - will not resurrect")
                return
            if not self.g_crashloop_allow(name, now):
                st["last_action"] = "down:crash-loop"
                st["next_try"] = now + CRASHLOOP_WINDOW_S
                record_history({"product": name, "event": "crash-loop-trip"})
                return
            if getattr(self, "_drive_guard", None) and \
                    not self._drive_guard.state["ransom"] == "clear":
                st["last_action"] = "frozen:ransom-alarm"
                st["next_try"] = now + MAX_BACKOFF_SECONDS
                return
            foreign = port_owner_is_foreign(prod["port"])
            if foreign:
                st["last_action"] = "foreign-port"
                st["next_try"] = now + MAX_BACKOFF_SECONDS
                log(f"{name}: port {prod['port']} held by non-responder; standing down")
                return
            st["fails"] += 1
            delay = min(MAX_BACKOFF_SECONDS, SWEEP_SECONDS_DEFAULT * (2 ** st["fails"]))
            st["next_try"] = now + delay
            ok = launch(prod)
            if ok:
                self.relaunch_times[name].append(now)
            actions.append("relaunched" if ok else "relaunch-failed")
            st["last_action"] = ";".join(actions) or f"down(fails={st['fails']})"
            record_history({"product": name, "event": st["last_action"],
                            "integrity": verdict})

        if alive:
            self.g_loopback(prod)

    def sweep(self) -> None:
        sc = self_check(self.self_baseline)
        if sc == "drift" and getattr(self, "_self_flagged", "") != "drift":
            log("SELF GUARD: kernel/config drift detected mid-run")
            self._self_flagged = "drift"
        if getattr(self, "_drive_guard", None):
            try:
                self._drive_guard.sweep()
            except Exception as exc:
                log(f"drive sweep error: {exc}")
        for prod in self.products:
            try:
                self.sweep_product(prod)
            except Exception as exc:
                log(f"{prod['name']}: sweep error: {exc}")
                self.state[prod["name"]]["last_action"] = f"sweep-error:{exc}"

    def start_status_server(self, port: int) -> None:
        guardian = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/api/status":
                    body = json.dumps({
                        "guardian": "persephone",
                        "version": "2.1.0",
                        "sweep_seconds": guardian.sweep_seconds,
                        "self": self_check(guardian.self_baseline),
                        "drive": (guardian._drive_guard.state
                                  if getattr(guardian, "_drive_guard", None)
                                  else None),
                        "products": [
                            {"name": n, **s} for n, s in guardian.state.items()
                        ],
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def log_message(self, *args):  # silence request log
                pass

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            self._httpd.daemon_threads = True
            import threading
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
            log(f"status surface: http://127.0.0.1:{port}/api/status")
        except OSError as exc:
            log(f"status server unavailable ({exc}); continuing headless")

    def run_forever(self) -> None:
        log(f"guardian loop started ({len(self.products)} products, "
            f"sweep {self.sweep_seconds}s, guards: integrity liveness "
            f"crashloop loopback data disk self attestation log "
            f"drive health structure ransom)")
        while True:
            self.sweep()
            time.sleep(self.sweep_seconds)


# ---------------------------------------------------------------- cli

def promote(prod: dict) -> None:
    """Re-baseline after a LEGITIMATE change (upgrade/edit)."""
    name = prod["name"]
    baseline_manifest(prod)
    n = snapshot_to_vault(prod)
    log(f"{name}: promoted - manifest re-baselined, {n} files vaulted")
    if prod.get("data_dirs"):
        data_snapshot(prod)


def cmd_status(products: list[dict]) -> None:
    print(f"{'PRODUCT':<12} {'INTEGRITY':<10} {'ALIVE':<6} {'ATTEST':<7} "
          f"{'LOOPBACK':<18} {'DISK':<8} LOOP")
    for name in products:
        n = name["name"]
        print(f"{n:<12} {'-':<10} {'-':<6} "
              f"{'yes' if attestation_valid(n) else 'NO':<7} "
              f"{'-':<18} {'-':<8} clear")


def main() -> int:
    global SECRET
    ap = argparse.ArgumentParser(description="PERSEPHONE guardian")
    ap.add_argument("--once", action="store_true", help="single sweep then exit")
    ap.add_argument("--status", action="store_true", help="print entitlement table")
    ap.add_argument("--attest", metavar="PRODUCT", help="mint/renew entitlement")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--promote", metavar="PRODUCT",
                    help="re-baseline manifests + vault after legit upgrade")
    ap.add_argument("--restore-data", metavar="PRODUCT",
                    help="restore newest user-data snapshot (manual safety)")
    ap.add_argument("--clear-alarm", action="store_true",
                    help="clear ransom alarm after manual resolution")
    ap.add_argument("--snapshot", action="store_true",
                    help="baseline ALL products (first-run setup)")
    ap.add_argument("--sweep", type=int, default=None, help="seconds between sweeps")
    args = ap.parse_args()

    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    SECRET = load_secret()

    if not CONFIG.exists():
        print(f"missing config: {CONFIG}", file=sys.stderr)
        return 2
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    products = cfg.get("products", [])
    sweep_seconds = args.sweep or cfg.get("sweep_seconds", SWEEP_SECONDS_DEFAULT)
    status_port = cfg.get("status_port", 43909)

    if args.attest:
        mint_attestation(args.attest, args.days)
        return 0

    if args.promote:
        for prod in products:
            if prod["name"] == args.promote:
                promote(prod)
                return 0
        print(f"unknown product: {args.promote}", file=sys.stderr)
        return 2

    if args.restore_data:
        for prod in products:
            if prod["name"] == args.restore_data:
                ok = restore_latest_data(prod)
                log(f"{args.restore_data}: data restore "
                    f"{'complete' if ok else 'FAILED (no snapshots)'}")
                return 0 if ok else 1
        print(f"unknown product: {args.restore_data}", file=sys.stderr)
        return 2

    g = Guardian(products, sweep_seconds)
    g._globals = cfg
    if cfg.get("drive"):
        dg = DriveGuard(cfg["drive"])
        dg._last_health_check = 0.0
        g._drive_guard = dg

    if args.clear_alarm:
        if getattr(g, "_drive_guard", None):
            g._drive_guard.state["ransom"] = "clear"
            g._drive_guard._save()
            log("ransom alarm cleared manually")
        return 0

    g.self_baseline = self_hashes()
    SELF_HASH_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELF_HASH_PATH.write_text(json.dumps(g.self_baseline, indent=1), encoding="utf-8")

    if args.snapshot:
        for prod in products:
            promote(prod)
        return 0
    if args.once:
        g.sweep()
        if getattr(g, "_drive_guard", None):
            ds = g._drive_guard.state
            print(f"drive: {ds['drive']} free={ds['free']} health={ds['health']} "
                  f"structure={ds['structure']} ransom={ds['ransom']}")
        for name, st in g.state.items():
            print(f"{name}: integrity={st['integrity']} alive={st['alive']} "
                  f"attested={st['attested']} loopback={st['loopback']} "
                  f"disk={st['disk']} loop={st['crashloop']} "
                  f"action={st['last_action']}")
        return 0
    if args.status:
        cmd_status(products)
        return 0

    g.start_status_server(status_port)
    try:
        g.run_forever()
    except KeyboardInterrupt:
        log("guardian stopped (ctrl-c)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
