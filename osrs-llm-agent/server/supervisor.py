import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time

from server.rsps_server import GameServer, DEFAULT_PORT


def content_hash(world_module=None):
    W = world_module
    if W is None:
        import game.world as W
    parts = []
    for name in sorted(vars(W)):
        if name.isupper():
            v = getattr(W, name)
            try:
                parts.append(f"{name}={json.dumps(v, sort_keys=True,
                                                 default=str)}")
            except (TypeError, ValueError):
                parts.append(f"{name}={v!r}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


class MindSupervisor:
    """Keeps a GameServer online: health probes, automatic crash recovery,
    content-version tracking, and knowledge-refresh triggering. Writes
    status JSON for the dashboard."""

    def __init__(self, port=DEFAULT_PORT, host="127.0.0.1",
                 poll_seconds=5, max_probe_failures=3,
                 knowledge_max_age_hours=12, auto_refresh_knowledge=True):
        self.port = port
        self.host = host
        self.poll = poll_seconds
        self.max_fails = max_probe_failures
        self.knowledge_max_age = knowledge_max_age_hours
        self.auto_refresh_knowledge = auto_refresh_knowledge
        self.server = None
        self.running = False
        self.started_at = None
        self.restart_count = 0
        self.consecutive_fails = 0
        self.last_error = ""
        self.last_health = "unknown"
        self.last_content_hash = None
        self.last_knowledge_refresh = 0.0
        self.status_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "runs", "server_status.json")

    # ---- server lifecycle -------------------------------------------------

    def _spawn(self):
        self.server = GameServer(host=self.host, port=self.port)
        self.server.start_async()

    def _probe(self):
        try:
            s = socket.create_connection((self.host, self.port), timeout=2)
            s.settimeout(2)
            s.sendall((json.dumps({"cmd": "login",
                                   "name": "__health__"}) + "\n").encode())
            f = s.makefile("r")
            resp = json.loads(f.readline())
            s.sendall((json.dumps({"cmd": "close"}) + "\n").encode())
            s.close()
            return bool(resp.get("ok"))
        except (OSError, ValueError):
            return False

    def _restart(self, reason):
        self.restart_count += 1
        self.last_error = reason
        try:
            if self.server:
                self.server.stop()
        except Exception:
            pass
        time.sleep(min(5, 0.5 * max(1, self.restart_count)))
        self._spawn()

    # ---- version / knowledge ----------------------------------------------

    def _check_content(self, state_dir):
        h = content_hash()
        state_file = os.path.join(state_dir, ".mind_state.json")
        prev = None
        if os.path.exists(state_file):
            try:
                prev = json.load(open(state_file)).get("content_hash")
            except (json.JSONDecodeError, OSError):
                pass
        updated = prev is not None and prev != h
        os.makedirs(state_dir, exist_ok=True)
        json.dump({"content_hash": h, "checked": time.time()},
                  open(state_file, "w"))
        self.last_content_hash = h
        return "updated" if updated else ("initialized" if prev is None
                                          else "unchanged")

    def _refresh_knowledge_if_stale(self, agent_root):
        digest = os.path.join(agent_root, "knowledge", "digest.md")
        age_h = ((time.time() - os.path.getmtime(digest)) / 3600
                 if os.path.exists(digest) else 1e9)
        if age_h < self.knowledge_max_age:
            return False
        if time.time() - self.last_knowledge_refresh < 600:
            return False
        self.last_knowledge_refresh = time.time()
        tool = os.path.join(agent_root, "tools", "update_knowledge.py")
        py = sys.executable
        subprocess.Popen([py, tool], cwd=agent_root,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True

    def _write_status(self, agent_root):
        payload = {
            "online": self.running and self.server is not None,
            "port": self.port,
            "players": self.server.player_count if self.server else 0,
            "uptime_seconds": int(time.time() - self.started_at)
            if self.started_at else 0,
            "restarts": self.restart_count,
            "last_error": self.last_error,
            "health": self.last_health,
            "content_hash": self.last_content_hash,
            "checked": time.time(),
        }
        try:
            os.makedirs(os.path.dirname(self.status_path), exist_ok=True)
            json.dump(payload, open(self.status_path, "w"))
        except OSError:
            pass

    # ---- main loop ---------------------------------------------------------

    def run_forever(self, agent_root=None, status=True, content_watch=True):
        agent_root = agent_root or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..")
        agent_root = os.path.abspath(agent_root)
        self.running = True
        self.started_at = time.time()
        self._spawn()
        while self.running:
            try:
                alive = bool(self.server and self.server.running)
                healthy = alive and self._probe()
                if not healthy:
                    self.consecutive_fails += 1
                    self.last_health = "degraded"
                    if self.consecutive_fails >= self.max_fails or not alive:
                        self._restart("probe failed" if alive
                                      else "server thread exited")
                        self.consecutive_fails = 0
                        self.last_health = "recovered"
                else:
                    self.consecutive_fails = 0
                    self.last_health = "healthy"
                if content_watch:
                    self._check_content(agent_root)
                if self.auto_refresh_knowledge:
                    self._refresh_knowledge_if_stale(agent_root)
                if status:
                    self._write_status(agent_root)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            time.sleep(self.poll)

    def start_async(self, **kw):
        t = threading.Thread(target=self.run_forever, kwargs=kw,
                             daemon=True)
        t.start()
        return t

    def stop(self):
        self.running = False
        if self.server:
            self.server.stop()
