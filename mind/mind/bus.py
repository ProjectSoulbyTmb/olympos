"""MIND bus - in-process pub/sub fanning production events outward.

Every surface that pushes (the SSE feed) subscribes here. Subscriber
queues are bounded; a slow consumer sheds the oldest event and records
the drop instead of stalling the director.
"""

from __future__ import annotations

import queue
import threading


class Bus:
    def __init__(self, per_subscriber: int = 256):
        self._lock = threading.Lock()
        self._subs = {}
        self._per_subscriber = int(per_subscriber)
        self.dropped = {}

    def publish(self, event_type: str, data: dict):
        with self._lock:
            subs = list(self._subs.items())
        if not subs:
            return
        for name, q in subs:
            try:
                q.put_nowait((event_type, dict(data or {})))
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait((event_type, dict(data or {})))
                except (queue.Empty, queue.Full):
                    pass
                with self._lock:
                    self.dropped[name] = self.dropped.get(name, 0) + 1

    def subscribe(self, name: str) -> "queue.Queue":
        q = queue.Queue(maxsize=self._per_subscriber)
        with self._lock:
            if name in self._subs:
                raise ValueError(f"subscriber already present: {name}")
            self._subs[name] = q
        return q

    def unsubscribe(self, name: str):
        with self._lock:
            self._subs.pop(name, None)

    def subscriber_names(self) -> list:
        with self._lock:
            return sorted(self._subs)


def selftest() -> int:
    failures = []

    def check(name, fn):
        try:
            ok = fn()
        except Exception as exc:
            print(f"FAIL bus.{name}: crashed: {exc}")
            failures.append(name)
            return
        if not ok:
            print(f"FAIL bus.{name}")
            failures.append(name)

    def t_fanout():
        b = Bus()
        qa, qb = b.subscribe("a"), b.subscribe("b")
        b.publish("scene_changed", {"sceneName": "Live"})
        return (qa.get_nowait()[1]["sceneName"] == "Live"
                and qb.get_nowait()[0] == "scene_changed")

    def t_dup_name():
        b = Bus()
        b.subscribe("dup")
        try:
            b.subscribe("dup")
            return False
        except ValueError:
            return True
        finally:
            pass

    def t_drop_oldest():
        b = Bus(per_subscriber=1)
        q = b.subscribe("slow")
        for i in range(4):
            b.publish("tick", {"i": i})
        got = q.get_nowait()[1]["i"]
        return got == 3 and b.dropped.get("slow") == 3

    def t_unsubscribe():
        b = Bus()
        b.subscribe("gone")
        b.unsubscribe("gone")
        b.publish("tick", {})
        return b.subscriber_names() == []

    check("fanout", t_fanout)
    check("duplicate-name-refused", t_dup_name)
    check("drop-oldest-counted", t_drop_oldest)
    check("unsubscribe", t_unsubscribe)
    print(f"bus selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
