"""MIND surfaces - shared base objects (Surface + Registry)."""

from __future__ import annotations


class Surface:
    """One named way the outside world touches MIND."""

    name = "surface"
    route = "/"
    methods = ("GET",)

    def handle(self, request):
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "route": self.route,
                "methods": list(self.methods)}


class Registry:
    """Exact-match router over registered surfaces."""

    def __init__(self):
        self._surfaces = []
        self._by_key = {}

    def register(self, surface):
        for method in surface.methods:
            key = (method.upper(), surface.route)
            if key in self._by_key:
                raise ValueError(
                    f"duplicate route: {key[0]} {key[1]} "
                    f"({self._by_key[key].name} vs {surface.name})")
            self._by_key[key] = surface
        self._surfaces.append(surface)
        return surface

    def resolve(self, method: str, path: str):
        return self._by_key.get((method.upper(), path))

    def describe(self) -> list:
        return [s.describe() for s in self._surfaces]

    def __len__(self):
        return len(self._surfaces)

    def __iter__(self):
        return iter(self._surfaces)
