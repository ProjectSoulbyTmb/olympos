"""MIND status surfaces - snapshot JSON and the liveness probe."""

from __future__ import annotations

from .base import Surface
from .http import Response


class StatusSurface(Surface):
    name = "status"
    route = "/api/status"
    methods = ("GET",)

    def __init__(self, snapshot):
        self.snapshot = snapshot

    def handle(self, request):
        return Response.json(self.snapshot.to_dict())


class HealthSurface(Surface):
    name = "health"
    route = "/healthz"
    methods = ("GET",)

    def __init__(self, version: str):
        self.version = version

    def handle(self, request):
        return Response.json({"ok": True, "organ": "mind",
                              "version": self.version})
