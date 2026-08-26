"""MIND control surfaces - POST endpoints that act on the production.

Every control surface validates input before it reaches the controller
(the director), answers JSON always, and carries the verdict in `ok`.
"""

from __future__ import annotations

from .base import Surface
from .http import Request, RequestError, Response


def call_controller(controller, action: str, data: dict) -> Response:
    if controller is None:
        return Response.json({"error": "no controller"}, status=503)
    try:
        ok, detail = controller(action, data)
    except Exception as exc:  # noqa: BLE001 - controller bugs answer 500
        return Response.json({"ok": False,
                              "detail": f"{type(exc).__name__}: {exc}"},
                             status=500)
    return Response.json({"ok": bool(ok), "detail": str(detail)})


class ControlSurface(Surface):
    methods = ("POST",)
    action_name = ""

    def __init__(self, controller=None):
        self.controller = controller

    def validate(self, payload: dict):
        """Return (data, error_detail)."""
        raise NotImplementedError

    def handle(self, request):
        try:
            payload = request.json()
        except RequestError as exc:
            return Response.json({"error": str(exc)}, status=400)
        data, error = self.validate(payload)
        if error is not None:
            return Response.json({"ok": False, "detail": error})
        return call_controller(self.controller, self.action_name, data)


class SceneControlSurface(ControlSurface):
    name = "scene-control"
    route = "/api/scene"
    action_name = "switch_scene"

    def validate(self, payload):
        name = payload.get("sceneName")
        if not isinstance(name, str) or not name.strip():
            return None, "sceneName must be a non-empty string"
        return {"sceneName": name.strip()}, None


class StreamControlSurface(ControlSurface):
    name = "stream-control"
    route = "/api/stream"
    action_name = "set_stream"

    def validate(self, payload):
        state = payload.get("state")
        if state not in ("start", "stop"):
            return None, "state must be 'start' or 'stop'"
        return {"state": state}, None


class RecordingControlSurface(ControlSurface):
    name = "recording-control"
    route = "/api/recording"
    action_name = "set_recording"

    def validate(self, payload):
        state = payload.get("state")
        if state not in ("start", "stop"):
            return None, "state must be 'start' or 'stop'"
        return {"state": state}, None


def selftest() -> int:
    from .base import Registry

    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL control.{name}")
            failures.append(name)

    log = []

    def controller(action, data):
        log.append((action, dict(data)))
        return True, f"did {action}"

    reg = Registry()
    for cls in (SceneControlSurface, StreamControlSurface,
                RecordingControlSurface):
        reg.register(cls(controller))

    def post(path, body=b"{}"):
        return reg.resolve("POST", path).handle(
            Request("POST", path, {}, {}, body, "127.0.0.1"))

    resp = post("/api/scene", b'{"sceneName": " Live "}')
    check("scene-ok", resp.status == 200 and '"ok": true' in resp.body.decode())

    check("scene-trimmed", log[-1] == ("switch_scene",
                                       {"sceneName": "Live"}))

    check("scene-blank-refused",
          '"ok": false' in post("/api/scene",
                                b'{"sceneName": ""}').body.decode())
    check("stream-bad-state-refused",
          '"ok": false' in post("/api/stream",
                                b'{"state": "warp"}').body.decode())
    check("recording-ok",
          '"ok": true' in post("/api/recording",
                               b'{"state": "stop"}').body.decode())

    bad = post("/api/scene", b"[1,2]")
    check("non-object-body-400", bad.status == 400)
    junk = post("/api/scene", b"not json at all")
    check("malformed-json-400", junk.status == 400)

    orphan = Registry()
    orphan.register(SceneControlSurface(None))
    no_ctrl = orphan.resolve("POST", "/api/scene").handle(
        Request("POST", "/api/scene", {}, {}, b'{"sceneName": "x"}', ""))
    check("missing-controller-503", no_ctrl.status == 503)

    def exploding(action, data):
        raise RuntimeError("obs vanished")

    blast = Registry()
    blast.register(StreamControlSurface(exploding))
    boom = blast.resolve("POST", "/api/stream").handle(
        Request("POST", "/api/stream", {}, {},
                b'{"state": "start"}', ""))
    check("controller-crash-500", boom.status == 500)

    print(f"surfaces.control selftest: "
          f"{'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
