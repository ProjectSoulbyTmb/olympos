"""MIND dashboard surface - the operator's single pane."""

from __future__ import annotations

from .base import Surface
from .http import Response


class DashboardSurface(Surface):
    name = "dashboard"
    route = "/"
    methods = ("GET",)

    def __init__(self, version: str):
        self.version = version

    def handle(self, request):
        return Response.html(PAGE.replace("__VERSION__", self.version))


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>MIND</title>
<style>
  :root { --bg:#101216; --panel:#171b21; --ink:#d7dce3;
          --dim:#7c8794; --live:#e5484d; --rec:#f5a524;
          --ok:#46a758; --edge:#262c35; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.45 system-ui, sans-serif; }
  header { display:flex; align-items:center; gap:12px;
           padding:14px 20px; border-bottom:1px solid var(--edge); }
  h1 { font-size:15px; letter-spacing:.25em; margin:0; }
  .dot { width:9px; height:9px; border-radius:50%;
         background:#555; }
  .dot.on { background:var(--ok); }
  main { padding:22px 20px; max-width:860px; }
  .badges { display:flex; gap:10px; margin-bottom:18px; }
  .badge { padding:5px 12px; border-radius:6px; font-weight:700;
           font-size:12px; letter-spacing:.15em;
           background:var(--panel); color:var(--dim);
           border:1px solid var(--edge); }
  .badge.on-live { background:var(--live); color:#fff; }
  .badge.on-rec { background:var(--rec); color:#1b1b1b; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .cell { background:var(--panel); border:1px solid var(--edge);
          border-radius:10px; padding:16px; min-height:84px; }
  .cell small { color:var(--dim); text-transform:uppercase;
                letter-spacing:.2em; font-size:11px; display:block;
                margin-bottom:8px; }
  #program { font-size:30px; font-weight:800; }
  #preview { font-size:22px; color:var(--dim); }
  .scenes { grid-column:1 / -1; display:flex; flex-wrap:wrap; gap:8px;
            margin-top:2px; }
  button.scene { background:var(--bg); color:var(--ink);
                 border:1px solid var(--edge); border-radius:8px;
                 padding:8px 14px; cursor:pointer; font-size:13px; }
  button.scene:hover { border-color:var(--ok); }
  button.scene.active { background:var(--live);
                        border-color:var(--live); color:#fff; }
  footer { color:var(--dim); font-size:11px; padding:0 20px 16px; }
</style></head>
<body>
<header>
  <h1>MIND <span style="color:var(--dim)">__VERSION__</span></h1>
  <div id="conn" class="dot" title="OBS link"></div>
  <div style="color:var(--dim)" id="obsver"></div>
</header>
<main>
  <div class="badges">
    <span id="live" class="badge">LIVE</span>
    <span id="rec" class="badge">REC</span>
  </div>
  <div class="grid">
    <div class="cell"><small>program</small><div id="program">&mdash;</div></div>
    <div class="cell"><small>preview</small><div id="preview">&mdash;</div></div>
    <div class="scenes" id="scenes"></div>
  </div>
</main>
<footer>sse feed: /api/events &middot; status: /api/status
 &middot; overlays: /overlay/tally, /overlay/timer?t=HH:MM:SS</footer>
<script>
let lastProgram = null;
const $ = id => document.getElementById(id);
function paint(s) {
  $("conn").className = "dot" + (s.connected ? " on" : "");
  $("obsver").textContent = s.obsVersion || "";
  $("live").className = "badge" + (s.streaming ? " on-live" : "");
  $("rec").className = "badge" + (s.recording ? " on-rec" : "");
  $("program").textContent = s.programScene || "\\u2014";
  $("preview").textContent = s.previewScene || "\\u2014";
  lastProgram = s.programScene;
  const box = $("scenes");
  box.innerHTML = "";
  (s.scenes || []).forEach(name => {
    const b = document.createElement("button");
    b.className = "scene" + (name === s.programScene ? " active" : "");
    b.textContent = name;
    b.onclick = () => fetch("/api/scene", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({sceneName: name}) });
    box.appendChild(b);
  });
}
function refresh() {
  fetch("/api/status").then(r => r.json()).then(paint);
}
["scene_changed","stream_started","stream_stopped",
 "recording_started","recording_stopped","connected"].forEach(k => {
  const es = new EventSource("/api/events");
  es.addEventListener(k, refresh);
});
refresh();
</script>
</body></html>
"""


def selftest() -> int:
    from .http import Request

    failures = []

    def check(name, cond):
        if not cond:
            print(f"FAIL dashboard.{name}")
            failures.append(name)

    page = DashboardSurface("2.0.0").handle(
        Request("GET", "/", {}, {}, b"", "")).body.decode()
    check("version-injected", "2.0.0" in page)
    check("sse-wired", "/api/events" in page)
    check("scene-posting-wired", "/api/scene" in page)
    check("no-template-leftover", "__VERSION__" not in page)
    print(f"surfaces.dashboard selftest: "
          f"{'green' if not failures else 'RED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
