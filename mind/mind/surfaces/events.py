"""MIND events surface - Server-Sent Events feed (push, not poll).

Browser sources and dashboards subscribe once and receive every
production event; slow consumers shed oldest events at the bus, never
in the director's hot path.
"""

from __future__ import annotations

import itertools
import queue

from .base import Surface
from .http import StreamingResponse

_COUNTER = itertools.count()


class EventsSurface(Surface):
    name = "sse-events"
    route = "/api/events"
    methods = ("GET",)

    def __init__(self, bus, heartbeat_seconds: float = 15.0):
        self.bus = bus
        self.heartbeat_seconds = float(heartbeat_seconds)

    def handle(self, request):
        name = f"sse-{next(_COUNTER)}"
        q = self.bus.subscribe(name)

        def chunks():
            try:
                yield b"retry: 2000\n\n"
                while True:
                    try:
                        event_type, data = q.get(
                            timeout=self.heartbeat_seconds)
                    except queue.Empty:
                        yield b": ping\n\n"
                        continue
                    payload = json_dumps(data or {})
                    yield (f"event: {event_type}\n"
                           f"data: {payload}\n\n").encode("utf-8")
            finally:
                self.bus.unsubscribe(name)

        return StreamingResponse("text/event-stream", chunks())


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj)


def selftest() -> int:
    from .base import Registry
    from .http import Request
    from ..bus import Bus

    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL events.{name}")
            failures.append(name)

    bus = Bus()
    reg = Registry()
    reg.register(EventsSurface(bus))
    check("route-registered", len(reg) == 1)

    response = reg.resolve("GET", "/api/events").handle(
        Request("GET", "/api/events", {}, {}, b"", "127.0.0.1"))
    check("streaming-response", getattr(response, "streaming", False))

    chunks = response.chunks
    first = next(chunks)
    check("retry-first", first == b"retry: 2000\n\n")

    bus.publish("scene_changed", {"sceneName": "Live"})
    frame = next(chunks).decode()
    check("event-framed",
          frame == 'event: scene_changed\ndata: {"sceneName": "Live"}\n\n')

    chunks.close()  # GeneratorExit -> unsubscribe in finally
    check("unsubscribed-on-close", bus.subscriber_names() == [])

    print(f"surfaces.events selftest: "
          f"{'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
