import json
import os
import threading
import time


class MindState:
    def __init__(self, root):
        self.root = root
        self.path = os.path.join(root, ".mind_state.json")
        self.log_path = os.path.join(root, "runs", "mind_log.jsonl")
        self.status_path = os.path.join(root, "runs", "mind_status.json")
        self._lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, **updates):
        with self._lock:
            state = self.load()
            state.update(updates)
            state["checked"] = time.time()
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=1)
            os.replace(tmp, self.path)
        return state

    def log(self, role, event, detail=""):
        entry = {"t": round(time.time(), 3), "role": role, "event": event}
        if detail:
            entry["detail"] = str(detail)[:2000]
        line = json.dumps(entry)
        with self._lock:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        print(f"[mind:{role}] {event}" + (f" - {detail}" if detail else ""))

    def write_status(self, payload):
        payload["checked"] = time.time()
        with self._lock:
            os.makedirs(os.path.dirname(self.status_path), exist_ok=True)
            tmp = self.status_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=1)
            os.replace(tmp, self.status_path)

    def recent(self, limit=50):
        try:
            with open(self.log_path, encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
            out = []
            for ln in lines:
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
            return out
        except OSError:
            return []
