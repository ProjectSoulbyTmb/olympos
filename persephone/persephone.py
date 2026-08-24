#!/usr/bin/env python3
"""PERSEPHONE — standalone guardian layer for offline products.

Watches registered products (APHRODITE, RILEY) and enforces three
guarantees per product:

  INTEGRITY   SHA-256 manifest of protected files; tamper -> vault restore.
  LIVENESS    loopback health probe; dead process -> attested relaunch.
  ATTESTATION HMAC'd offline entitlement; unattested products are not
              resurrected.

Design rules (inherited from the Olympos watchdogs):
  * loopback-only; zero network egress; stdlib only
  * never fight a foreign service that owns a product's port
  * all state under %LOCALAPPDATA%\\PERSEPHONE (log, vault, attest)

CLI:
  python persephone.py                    run guardian loop (foreground)
  python persephone.py --once             single sweep, exit
  python persephone.py --attest NAME --days N   mint/renew entitlement
  python persephone.py --status           print current state table
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
import tempfile
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "products.json"

STATE_ROOT = Path(os.environ.get("PERSEPHONE_STATE",
                                 Path.home() / "AppData" / "Local" / "PERSEPHONE"))
VAULT_DIR = STATE_ROOT / "vault"
ATTEST_DIR = STATE_ROOT / "attest"
LOG_PATH = STATE_ROOT / "persephone.log"
HISTORY_PATH = STATE_ROOT / "history.jsonl"

SECRET_PATH = STATE_ROOT / ".secret"
SWEEP_SECONDS_DEFAULT = 30
MAX_BACKOFF_SECONDS = 600
HISTORY_KEEP = 500


# ---------------------------------------------------------------- logging

def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def record_history(entry: dict) -> None:
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-(HISTORY_KEEP - 1):]
        lines.append(json.dumps(entry, ensure_ascii=False))
        HISTORY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
        dst = vd / spec["path"].replace(":", "_").replace("\\", "__").replace("/", "__")
        if src.exists():
            shutil.copy2(src, dst)
            n += 1
    return n


def check_integrity(prod: dict) -> tuple[str, list[str]]:
    """Returns (verdict, tampered_paths). verdict: ok|restored|novault|missing."""
    mf_path = vault_dir_for(prod["name"]) / "manifest.json"
    files = [spec for spec in prod.get("files", []) if Path(spec["path"]).exists()]
    if not files:
        return "missing", []
    current = build_manifest(files)

    if not mf_path.exists():
        # first contact: trust what is on disk now, vault it
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
        vfile = vd / path_str.replace(":", "_").replace("\\", "__").replace("/", "__")
        target = Path(path_str)
        if vfile.exists():
            shutil.copy2(vfile, target)
            current[path_str] = sha256_file(target)
            restored.append(path_str)
            log(f"{prod['name']}: VAULT RESTORE {target.name}")
        else:
            log(f"{prod['name']}: TAMPERED, no vault copy: {target}")
    mf_path.write_text(json.dumps({**known, **current}, indent=1), encoding="utf-8")
    if restored:
        return "restored", problems
    return "novault", problems


# ---------------------------------------------------------------- liveness

def probe_health(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def port_owner_is_foreign(port: int) -> bool:
    """True if something listens on the port but health is dead => foreign.

    House rule (Aphrodite watchdog): never fight a service we cannot identify.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch(prod: dict) -> bool:
    launcher = prod.get("launch")
    if not launcher or not Path(launcher).exists():
        log(f"{prod['name']}: no launcher configured, cannot resurrect")
        return False
    flags = prod.get("launch_flags", ["--quiet"])
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


# ---------------------------------------------------------------- kernel

class Guardian:
    def __init__(self, products: list[dict], sweep_seconds: int):
        self.products = products
        self.sweep_seconds = sweep_seconds
        self.state: dict[str, dict] = {
            p["name"]: {"integrity": "?", "alive": None, "attested": None,
                        "fails": 0, "next_try": 0.0, "last_action": "-"}
            for p in products
        }
        self._httpd = None

    def sweep_product(self, prod: dict) -> None:
        name = prod["name"]
        st = self.state[name]
        actions: list[str] = []

        verdict, _problems = check_integrity(prod)
        st["integrity"] = verdict
        if verdict in ("restored", "novault"):
            actions.append(f"integrity={verdict}")

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
            st["fails"] = 0
            st["last_action"] = ";".join(actions) or "ok"
        elif now < st["next_try"]:
            st["last_action"] = "backoff"
            return
        else:
            if not attested:
                st["last_action"] = "down:unattested"
                st["next_try"] = now + MAX_BACKOFF_SECONDS
                log(f"{name}: DOWN but unattested — will not resurrect")
                return
            foreign = port_owner_is_foreign(prod["port"])
            if foreign:
                # port owned, health dead -> someone else holds it; stand down
                st["last_action"] = "foreign-port"
                st["next_try"] = now + MAX_BACKOFF_SECONDS
                log(f"{name}: port {prod['port']} held by non-responder; standing down")
                return
            st["fails"] += 1
            delay = min(MAX_BACKOFF_SECONDS, SWEEP_SECONDS_DEFAULT * (2 ** st["fails"]))
            st["next_try"] = now + delay
            ok = launch(prod)
            actions.append("relaunched" if ok else "relaunch-failed")
            st["last_action"] = ";".join(actions) or f"down(fails={st['fails']})"
            record_history({"product": name, "event": st["last_action"],
                            "integrity": verdict})

    def sweep(self) -> None:
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
                        "version": "1.0.0",
                        "sweep_seconds": guardian.sweep_seconds,
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
            f"sweep {self.sweep_seconds}s)")
        while True:
            self.sweep()
            time.sleep(self.sweep_seconds)


# ---------------------------------------------------------------- cli

def cmd_status(products: list[dict]) -> None:
    g_state = Guardian(products, 0).state
    print(f"{'PRODUCT':<12} {'INTEGRITY':<10} {'ALIVE':<6} "
          f"{'ATTESTED':<9} STATE")
    for name, st in g_state.items():
        alive = "?" if st["alive"] is None else ("yes" if st["alive"] else "NO")
        att = "?" if st["attested"] is None else ("yes" if st["attested"] else "NO")
        print(f"{name:<12} {st['integrity']:<10} {alive:<6} {att:<9} -")


def main() -> int:
    global SECRET
    ap = argparse.ArgumentParser(description="PERSEPHONE guardian")
    ap.add_argument("--once", action="store_true", help="single sweep then exit")
    ap.add_argument("--attest", metavar="PRODUCT", help="mint/renew entitlement")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--snapshot", action="store_true",
                    help="(re)baseline manifests and refresh vault, then exit")
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

    g = Guardian(products, sweep_seconds)
    if args.snapshot:
        for prod in products:
            mf = vault_dir_for(prod["name"]) / "manifest.json"
            if mf.exists():
                mf.unlink()
            check_integrity(prod)
            snapshot_to_vault(prod)
            log(f"{prod['name']}: vault refreshed")
        return 0
    if args.once:
        g.sweep()
        for name, st in g.state.items():
            print(f"{name}: integrity={st['integrity']} "
                  f"alive={st['alive']} attested={st['attested']} "
                  f"action={st['last_action']}")
        return 0

    g.start_status_server(status_port)
    try:
        g.run_forever()
    except KeyboardInterrupt:
        log("guardian stopped (ctrl-c)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
