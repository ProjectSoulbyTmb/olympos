from collections import defaultdict


class World:
    def __init__(self):
        self._next_id = 0
        self._alive = set()
        self._stores = defaultdict(dict)
        self._systems = []
        self.tags = set()

    def spawn(self, **components):
        eid = self._next_id
        self._next_id += 1
        self._alive.add(eid)
        for name, value in components.items():
            self.set(eid, name, value)
        return eid

    def destroy(self, eid):
        self._alive.discard(eid)
        for store in self._stores.values():
            store.pop(eid, None)

    def alive(self, eid):
        return eid in self._alive

    def count(self):
        return len(self._alive)

    def set(self, eid, name, value):
        if not self.alive(eid):
            raise KeyError(f"entity {eid} is dead")
        self._stores[name][eid] = value

    def get(self, eid, name, default=None):
        return self._stores.get(name, {}).get(eid, default)

    def has(self, eid, name):
        return eid in self._stores.get(name, {})

    def remove_component(self, eid, name):
        self._stores.get(name, {}).pop(eid, None)

    def query(self, *names):
        if not names:
            for eid in sorted(self._alive):
                yield eid, ()
            return
        stores = [self._stores.get(n, {}) for n in names]
        smallest = min(stores, key=len)
        for eid in sorted(smallest):
            if eid not in self._alive:
                continue
            values = []
            ok = True
            for store in stores:
                if eid not in store:
                    ok = False
                    break
                values.append(store[eid])
            if ok:
                yield eid, tuple(values)

    def add_system(self, fn):
        self._systems.append(fn)
        return fn

    def step(self, dt=1.0):
        for fn in list(self._systems):
            fn(self, dt)


def snapshot(world, component_names):
    out = {}
    for eid, values in world.query(*component_names):
        out[eid] = {n: v for n, v in zip(component_names, values)}
    return {"entities": out, "tags": sorted(world.tags)}
