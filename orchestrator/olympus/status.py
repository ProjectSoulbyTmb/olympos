import json
import os
import threading
import time

from . import config


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


class StatusWriter(threading.Thread):
    def __init__(self, collect_fn):
        super().__init__(daemon=True, name="status")
        self.collect_fn = collect_fn
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                atomic_write(
                    config.STATUS_FILE,
                    {
                        "version": config.VERSION,
                        "updated": time.time(),
                        "jobs": self.collect_fn(),
                    },
                )
            except OSError as e:
                logging = __import__("logging")
                logging.getLogger("olympus.status").error("status write failed: %s", e)
            self.stop_event.wait(10)
