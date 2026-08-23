"""Live TCP channel for MIND <-> Thoth (and any subscriber).

JSON-lines protocol. Every message is a bus-compatible envelope:
    {"id": "...", "from": "...", "type": "...", "payload": {...}, "at": "..."}

The server spools every inbound event into the durable EventBus and fans
published events out to all connected subscribers - the file bus stays the
source of truth, the channel is the live wire.
"""
import json
import socket
import threading
import time


class MindChannelServer:
    def __init__(self, root, host="127.0.0.1", port=5731, policy=None,
                use_bus=True):
        self.root = root
        self.host = host
        self.port = port
        self.policy = policy
        self.use_bus = use_bus
        self.clients = []
        self.lock = threading.Lock()
        self.sock = None
        self.running = False
        self.events_in = 0
        if use_bus:
            from mind.bus import EventBus
            self.bus = EventBus(root)
        else:
            self.bus = None

    def start(self):
        if self.policy is not None:
            ok, reason = self.policy.check_listener(self.host, self.port)
            if not ok:
                raise PermissionError(f"MIND net policy denied: {reason}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        actual = self.sock.getsockname()[1]
        self.sock.listen(8)
        self.port = actual
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return actual

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        with self.lock:
            for c in list(self.clients):
                try:
                    c["sock"].close()
                except OSError:
                    pass
            self.clients.clear()

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
            except OSError:
                break
            client = {"sock": conn, "addr": addr, "file": conn.makefile("r")}
            with self.lock:
                self.clients.append(client)
            threading.Thread(target=self._client_loop, args=(client,),
                             daemon=True).start()

    def broadcast(self, envelope):
        dead = []
        data = (json.dumps(envelope) + "\n").encode()
        with self.lock:
            for c in self.clients:
                try:
                    c["sock"].sendall(data)
                except OSError:
                    dead.append(c)
            for c in dead:
                self.clients.remove(c)

    def publish(self, type_, payload, source="mind"):
        env = {"id": f"{source}_{time.time_ns()}",
               "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "from": source, "type": type_, "payload": payload}
        if self.bus is not None:
            self.bus.publish(type_, payload, source=source)
        self.broadcast(env)
        return env

    def _client_loop(self, client):
        f = client["file"]
        while self.running:
            try:
                line = f.readline()
            except OSError:
                break
            if not line:
                break
            try:
                evt = json.loads(line)
                evt.setdefault("from", "thoth")
                evt.setdefault("type", "unknown")
                evt.setdefault("payload", {})
                self.events_in += 1
                if self.bus is not None:
                    self.bus.publish(evt["type"], evt["payload"],
                                     source=evt["from"])
                self.broadcast({"id": evt.get("id"),
                                "at": evt.get("at",
                                              time.strftime(
                                                  "%Y-%m-%dT%H:%M:%S")),
                                "from": evt["from"], "type": evt["type"],
                                "payload": evt["payload"]})
            except json.JSONDecodeError:
                continue
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)
        try:
            client["sock"].close()
        except OSError:
            pass


class ChannelClient:
    def __init__(self, host="127.0.0.1", port=5731, timeout=5):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.file = self.sock.makefile("r")

    def send(self, type_, payload, source="thoth"):
        evt = {"id": f"{source}_{time.time_ns()}",
               "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "from": source, "type": type_, "payload": payload}
        self.sock.sendall((json.dumps(evt) + "\n").encode())
        return evt

    def recv(self, timeout=None):
        if timeout is not None:
            self.sock.settimeout(timeout)
        line = self.file.readline()
        if not line:
            raise ConnectionError("channel closed")
        return json.loads(line)

    def close(self):
        try:
            self.file.close()
            self.sock.close()
        except OSError:
            pass
