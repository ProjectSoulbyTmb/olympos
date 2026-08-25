"""MIND bus - tiny in-process pub/sub fanning production events out.

Overlays subscribe through the HTTP server (Server-Sent Events, the
Current Song 2 lesson: push beats polling for browser sources).
Subscriber queues are bounded; a slow overlay drops oldest events and
records that fact instead of stalling the director.

Run: python mind/bus.py   (self-test, exit 0 = fanout sane)
"""

from __future__ import annotations

import queue
import threading


class Bus:
    def __init__(self, per_subscriber: int = 256):
        self._lock = threading.Lock()
        self._subs = {}  # name -> queue.Queue
        self._per_subscriber = int(per_subscriber)
        self.dropped = {}

    def publish(self, event_type: str, data: dict):
        with self._lock:
            subs = list(self._subs.items())
        for name, q in subs:
            try:
                q.put_nowait((event_type, data))
            except queue.Full:
                try:
                    q.get_nowait()  # shed the oldest
                    q.put_nowait((event_type, data))
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
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")

    def t_fanout_and_backpressure():
        bus = Bus(per_subscriber=2)
        fast = bus.subscribe("fast")
        slow = bus.subscribe("slow")
        for i in range(5):
            bus.publish("tick", {"i": i})
        # a full subscriber sheds its OLDEST entries, keeping the newest
        tail = []
        while True:
            try:
                tail.append(fast.get_nowait()[1]["i"])
            except queue.Empty:
                break
        assert tail == [3, 4], f"shed-oldest window wrong: {tail}"
        tail_slow = []
        while True:
            try:
                tail_slow.append(slow.get_nowait()[1]["i"])
            except queue.Empty:
                break
        assert tail_slow == [3, 4], "subscribers must advance alike"
        # every shed is accounted; the publisher never blocked
        assert bus.dropped.get("fast", 0) == 3, bus.dropped
        assert bus.subscriber_names() == ["fast", "slow"]
        bus.unsubscribe("fast")
        bus.unsubscribe("slow")
        assert bus.subscriber_names() == []
        try:
            bus.subscribe("fast")
            bus.subscribe("fast")
            raise AssertionError("duplicate subscription accepted")
        except ValueError:
            pass

    check("fanout-backpressure", t_fanout_and_backpressure)

    print(f"bus selftest: {'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
