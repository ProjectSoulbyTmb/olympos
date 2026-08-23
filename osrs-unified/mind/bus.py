import json
import os
import threading
import time


class EventBus:
    """Durable file-based relay between MIND and Thoth.

    Envelope mirrors Thoth's relay events ({type, payload, at}) plus
    routing fields. Events spool under runs/osrs_bus/ until a consumer
    completes them; completed events move to archive/ for audit."""

    def __init__(self, root):
        self.dir = os.path.join(root, "runs", "osrs_bus")
        self.spool = os.path.join(self.dir, "spool")
        self.archive = os.path.join(self.dir, "archive")
        os.makedirs(self.spool, exist_ok=True)
        os.makedirs(self.archive, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = int(time.time() * 1000) % 10 ** 9

    def _next_id(self, source):
        with self._lock:
            self._seq += 1
            return f"{source}_{time.strftime('%Y%m%d_%H%M%S')}_{self._seq}"

    def _write_atomic(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)

    def publish(self, type_, payload, source="mind"):
        evt = {"id": self._next_id(source),
               "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "from": source,
               "type": type_,
               "status": "queued",
               "payload": payload}
        path = os.path.join(self.spool, evt["id"] + ".json")
        self._write_atomic(path, evt)
        return evt["id"]

    def _scan(self, subdir):
        try:
            names = os.listdir(subdir)
        except OSError:
            return []
        return sorted(n for n in names if n.endswith(".json"))

    def pending(self, type_=None, source=None):
        found = []
        for name in self._scan(self.spool):
            path = os.path.join(self.spool, name)
            try:
                with open(path, encoding="utf-8") as f:
                    evt = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if evt.get("status") != "queued":
                continue
            if type_ and evt.get("type") != type_:
                continue
            if source and evt.get("from") != source:
                continue
            found.append(evt)
        return found

    def take(self, evt_id):
        src = os.path.join(self.spool, evt_id + ".json")
        if not os.path.exists(src):
            raise FileNotFoundError(evt_id)
        with open(src, encoding="utf-8") as f:
            evt = json.load(f)
        evt["status"] = "taken"
        self._write_atomic(src, evt)
        return evt

    def complete(self, evt_id, result=None, ok=True):
        src = os.path.join(self.spool, evt_id + ".json")
        if not os.path.exists(src):
            raise FileNotFoundError(evt_id)
        with open(src, encoding="utf-8") as f:
            evt = json.load(f)
        evt["status"] = "done" if ok else "failed"
        evt["result"] = result or {}
        evt["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        dst = os.path.join(self.archive, evt_id + ".json")
        self._write_atomic(dst, evt)
        try:
            os.remove(src)
        except OSError:
            pass
        return evt

    def fail(self, evt_id, reason):
        return self.complete(evt_id, {"error": str(reason)}, ok=False)

    def recent(self, limit=15):
        out = []
        for name in self._scan(self.archive)[-limit:]:
            path = os.path.join(self.archive, name)
            try:
                with open(path, encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue
        return list(reversed(out))
