"""MIND overlay surfaces - browser-source pages for OBS.

Tally: full-screen program/preview light, optionally scoped to one
scene with ?scene=Name. Timer: ?t=HH:MM:SS countdown. Both update via
SSE, never polling.
"""

from __future__ import annotations

import html as html_mod

from .base import Surface
from .http import Response


class TallyOverlaySurface(Surface):
    name = "overlay-tally"
    route = "/overlay/tally"
    methods = ("GET",)

    def __init__(self):
        pass

    def handle(self, request):
        scope = request.query.get("scene")
        page = TALLY_PAGE.replace("__SCOPE_JSON__",
                                  html_mod.escape(_js(scope), quote=True))
        return Response.html(page)


class TimerOverlaySurface(Surface):
    name = "overlay-timer"
    route = "/overlay/timer"
    methods = ("GET",)

    def __init__(self):
        pass

    def handle(self, request):
        raw = request.query.get("t", "00:10:00").lstrip("#")
        seconds = _parse_duration(raw)
        page = TIMER_PAGE.replace("__SECONDS__",
                                  str(max(0, seconds)))
        return Response.html(page)


def _js(value):
    import json
    return json.dumps(value)


def _parse_duration(raw: str) -> int:
    try:
        parts = [int(p) for p in raw.split(":")]
    except ValueError:
        return 600
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return max(0, h * 3600 + m * 60 + s)


TALLY_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html,body { margin:0; height:100%; overflow:hidden;
              background:transparent; }
  #light { position:absolute; inset:0; display:none;
           align-items:center; justify-content:center; }
  #light.program { display:flex; background:rgba(196,44,52,.92); }
  #light.preview { display:flex; background:rgba(70,167,88,.88); }
  span { color:#fff; font:700 42px system-ui, sans-serif;
         letter-spacing:.3em; }
</style></head>
<body>
<div id="light"><span id="label"></span></div>
<script>
const scope = __SCOPE_JSON__;
const light = document.getElementById("light");
const label = document.getElementById("label");
function render(s) {
  let mode = null;
  let name = null;
  if (s.programScene && (!scope || s.programScene === scope)) {
    mode = "program"; name = s.programScene;
  } else if (s.previewScene && (!scope || s.previewScene === scope)) {
    mode = "preview"; name = s.previewScene;
  }
  if (!mode) { light.className = ""; return; }
  light.className = mode;
  label.textContent = (mode === "program" ? "PROGRAM" : "PREVIEW")
                      + " \\u00b7 " + name;
}
const es = new EventSource("/api/events");
["scene_changed","stream_started","stream_stopped"].forEach(k =>
  es.addEventListener(k, () => fetch("/api/status")
                              .then(r => r.json()).then(render)));
fetch("/api/status").then(r => r.json()).then(render);
</script>
</body></html>
"""

TIMER_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html,body { margin:0; height:100%; overflow:hidden; background:transparent; }
  body { display:flex; align-items:center; justify-content:center; }
  div { font:700 96px ui-monospace, Consolas, monospace;
        color:#fff; text-shadow:0 2px 12px rgba(0,0,0,.85); }
  div.late { color:#ff5d5d; }
</style></head>
<body><div id="clock"></div>
<script>
let left = __SECONDS__;
const clock = document.getElementById("clock");
function pad(n) { return String(n).padStart(2, "0"); }
function render() {
  clock.textContent = pad(Math.floor(left/3600)) + ":" +
                      pad(Math.floor(left%3600/60)) + ":" + pad(left%60);
  clock.className = left <= 60 ? "late" : "";
}
render();
const t = setInterval(() => {
  left = Math.max(0, left - 1);
  render();
  if (left === 0) clearInterval(t);
}, 1000);
window.MIND_TIMER_SYNC = () => {};  // browser sources may poke this
</script></body></html>
"""


def selftest() -> int:
    from .base import Registry
    from .http import Request

    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL overlays.{name}")
            failures.append(name)

    reg = Registry()
    reg.register(TallyOverlaySurface())
    reg.register(TimerOverlaySurface())

    tally = reg.resolve("GET", "/overlay/tally").handle(
        Request("GET", "/overlay/tally", {}, {}, b"", ""))
    check("tally-served", '"light"' in tally.body.decode())

    scoped = reg.resolve("GET", "/overlay/tally").handle(
        Request("GET", "/overlay/tally", {"scene": 'BRB"x'}, {}, b"", ""))
    scoped_body = scoped.body.decode()
    check("tally-scoped-escaped",
          "&quot;" in scoped_body
          and "__SCOPE_JSON__" not in scoped_body)

    timer = reg.resolve("GET", "/overlay/timer").handle(
        Request("GET", "/overlay/timer", {"t": "#00:01:30"}, {}, b"", ""))
    check("timer-parses-duration", "__SECONDS__" not in timer.body.decode()
          and "90;" in timer.body.decode())

    fallback = reg.resolve("GET", "/overlay/timer").handle(
        Request("GET", "/overlay/timer", {"t": "junk"}, {}, b"", ""))
    check("timer-junk-falls-back", "600;" in fallback.body.decode())

    check("parse-negative-clamped", _parse_duration("-5") >= 0)
    print(f"surfaces.overlays selftest: "
          f"{'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
