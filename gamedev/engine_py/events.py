class EventBus:
    def __init__(self):
        self._subs = {}

    def on(self, topic, fn):
        self._subs.setdefault(topic, []).append(fn)
        return fn

    def off(self, topic, fn):
        subs = self._subs.get(topic)
        if subs and fn in subs:
            subs.remove(fn)

    def emit(self, topic, payload=None):
        for fn in list(self._subs.get(topic, [])):
            fn(payload)

    def subscriber_count(self, topic):
        return len(self._subs.get(topic, []))
