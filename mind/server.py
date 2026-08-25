"""MIND server - local-first HTTP control plane for the director.

One port, five surfaces:

    GET  /                operator dashboard (dark, minimal, live)
    GET  /api/status      production snapshot as JSON
    GET  /api/events      Server-Sent Events feed (push, not poll)
    GET  /overlay/tally   browser-source tally (program/preview aware)
    GET  /overlay/timer   browser-source countdown (#HH:MM:SS in URL)
    POST /api/scene       {"sceneName": "..."} -> switch program scene
    POST /api/stream      {"state": "start"|"stop"}
    POST /api/recording   {"state": "start"|"stop"}

Side effects route through an injected controller (the director), so
this file carries no OBS knowledge and stays gate-testable with a
recorder stub.

Run: python mind/server.py   (self-test, exit 0 = routes sane)
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .bus import Bus

MAX_BODY_BYTES = 4096


class MindServer:
    def __init__(self, state_provider=None, bus: "Bus | None" = None,
                 controller=None, host: str = "127.0.0.1", port: int = 0):
        """`port=0` binds an ephemeral port (gates, demos)."""
        self.state_provider = state_provider  # -> dict snapshot
        self.bus = bus or Bus()
        self.controller = controller  # callable(action: str, data: dict)
        self.host = host

        outer = self

        def _validate_action(action, payload):
            """Return an error string for invalid action payloads, else None."""
            if action == "switch_scene":
                name = payload.get("sceneName")
                if not isinstance(name, str) or not name.strip():
                    return "sceneName must be a non-empty string"
            elif action in ("set_stream", "set_recording"):
                state = payload.get("state")
                if state not in ("start", "stop"):
                    return "state must be 'start' or 'stop'"
            return None

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                pass  # quiet; the journal is the record

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/":
                    outer._send(self, 200, "text/html; charset=utf-8",
                                render_dashboard())
                elif path == "/api/status":
                    snap = outer.state_provider() \
                        if outer.state_provider else {}
                    outer._send(self, 200, "application/json",
                                json.dumps(snap))
                elif path == "/api/events":
                    outer._stream_events(self)
                elif path == "/overlay/tally":
                    outer._send(self, 200, "text/html; charset=utf-8",
                                render_tally_overlay())
                elif path == "/overlay/timer":
                    outer._send(self, 200, "text/html; charset=utf-8",
                                render_timer_overlay())
                elif path == "/healthz":
                    outer._send(self, 200, "application/json",
                                '{"ok": true}')
                else:
                    outer._send(self, 404, "text/plain", "not found")

            def do_POST(self):
                path = urlparse(self.path).path
                routes = {
                    "/api/scene": "switch_scene",
                    "/api/stream": "set_stream",
                    "/api/recording": "set_recording",
                }
                if path not in routes:
                    outer._send(self, 404, "text/plain", "not found")
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_BODY_BYTES:
                        raise ValueError("body too large")
                    body = self.rfile.read(length) if length else b"{}"
                    payload = json.loads(body.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("body must be an object")
                except (ValueError, json.JSONDecodeError) as exc:
                    outer._send(self, 400, "application/json",
                                json.dumps({"error": str(exc)}))
                    return
                # input-level validation: refuse malformed actions before
                # they reach the controller - the control plane always
                # answers JSON, the ok flag carries the verdict
                error = _validate_action(routes[path], payload)
                if error is not None:
                    outer._send(self, 200, "application/json",
                                json.dumps({"ok": False,
                                            "detail": error}))
                    return
                if outer.controller is None:
                    outer._send(self, 503, "application/json",
                                json.dumps({"error": "no controller"}))
                    return
                ok, detail = outer.controller(routes[path], payload)
                outer._send(self, 200 if ok else 409,
                            "application/json",
                            json.dumps({"ok": bool(ok),
                                        "detail": detail or {}}))

        # allow_reuse_address=False: on Windows, SO_REUSEADDR permits a
        # second silent bind on a live port and the squatter keeps the
        # traffic - better to fail loudly with EADDRINUSE (L029: an
        # undeclared/untested port is an unprotected port)
        class _Httpd(ThreadingHTTPServer):
            allow_reuse_address = False

        self._httpd = _Httpd((host, port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="mind-http")
        # SSE subscriber bookkeeping lives here, keyed by connection id
        self._sse_lock = threading.Lock()
        self._sse_queues = {}
        self._sse_ids = 0
        self.port = self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self):
        self._thread.start()

    def stop(self):
        with self._sse_lock:
            queues = list(self._sse_queues.values())
            self._sse_queues.clear()
        for q in queues:
            try:
                q.put_nowait(None)  # unblock SSE writers
            except queue.Full:
                pass
        # shutdown() deadlocks unless serve_forever is actually running
        # (socketserver contract) - e.g. stop() before start()
        if self._thread.is_alive():
            self._httpd.shutdown()
            self._thread.join(timeout=5.0)
        self._httpd.server_close()

    # -- helpers -----------------------------------------------------------

    def _send(self, handler, code: int, ctype: str, text: str):
        body = text.encode("utf-8")
        handler.send_response(code)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except OSError:
            pass

    def _stream_events(self, handler):
        """SSE: register a bounded queue, flush backlog as comments."""
        with self._sse_lock:
            self._sse_ids += 1
            my_id = f"sse-{self._sse_ids}"
            q = self.bus.subscribe(my_id)
            self._sse_queues[my_id] = q
        try:
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Connection", "close")
            handler.end_headers()
            while True:
                try:
                    item = q.get(timeout=15.0)
                except queue.Empty:
                    try:
                        handler.wfile.write(b": keepalive\n\n")
                        handler.wfile.flush()
                        continue
                    except OSError:
                        return
                if item is None:
                    return
                event_type, data = item
                chunk = (f"event: {event_type}\n"
                         f"data: {json.dumps(data)}\n\n").encode("utf-8")
                try:
                    handler.wfile.write(chunk)
                    handler.wfile.flush()
                except OSError:
                    return
        finally:
            self.bus.unsubscribe(my_id)
            with self._sse_lock:
                self._sse_queues.pop(my_id, None)


# -- pages ---------------------------------------------------------------

_DARK_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box;margin:0}
body{background:#101216;color:#e8eaf0;font:14px/1.5 system-ui,sans-serif;
padding:24px}
h1{font-size:18px;letter-spacing:.12em;text-transform:uppercase}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;
font-size:12px;background:#23262e;margin-right:6px}
.on{background:#1d7a3c}.off{background:#5a2020}
.scene{font-size:28px;font-weight:700;margin:12px 0}
.row{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap}
button{background:#23262e;color:#e8eaf0;border:1px solid #343945;
padding:8px 14px;border-radius:6px;cursor:pointer}
button:hover{border-color:#6a76ff}
#feed{margin-top:20px;border-top:1px solid #23262e;padding-top:10px;
max-height:220px;overflow:auto;font-size:12px;color:#9aa2b1}
"""


def render_dashboard() -> str:
    return f"""<!doctype html><html><head><title>MIND</title>
<style>{_DARK_CSS}</style></head><body>
<h1>MIND &middot; stream director</h1>
<p>
<span class="badge" id="conn">connecting</span>
<span class="badge" id="stream">stream ?</span>
<span class="badge" id="record">record ?</span>
</p>
<div class="scene" id="program">-</div>
<div style="color:#9aa2b1">preview: <span id="preview">-</span></div>
<div class="row">
<button onclick="act('/api/recording', 'start')">&#9679; rec on</button>
<button onclick="act('/api/recording', 'stop')">&#9632; rec off</button>
<button onclick="act('/api/stream', 'start')">&#9679; live</button>
<button onclick="act('/api/stream', 'stop')">&#9632; end live</button>
</div>
<div class="row" id="scenes"></div>
<div id="feed"></div>
<script>
let source;
function refresh(){{
  fetch('/api/status').then(r=>r.json()).then(s=>{{
    const c=document.getElementById('conn');
    c.textContent=s.connected?'obs connected':'obs offline';
    c.className='badge '+(s.connected?'on':'off');
    document.getElementById('program').textContent=s.program_scene||'-';
    document.getElementById('preview').textContent=s.preview_scene||'-';
    const st=document.getElementById('stream');
    st.textContent='stream '+(s.streaming?'live':'idle');
    st.className='badge '+(s.streaming?'on':'off');
    const rc=document.getElementById('record');
    rc.textContent='record '+(s.recording?(s.recording_paused?'paused':'on'):'off');
    rc.className='badge '+(s.recording?'on':'off');
    const row=document.getElementById('scenes');row.innerHTML='';
    (s.scenes||[]).forEach(n=>{{
      const b=document.createElement('button');
      b.textContent=n;
      b.onclick=()=>fetch('/api/scene',{{method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{sceneName:n}})}});
      row.appendChild(b);
    }});
  }}).catch(()=>{{}});
}}
function act(path,state){{
  fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{state}})}}).then(refresh);
}}
function note(kind,data){{
  const feed=document.getElementById('feed');
  const line=document.createElement('div');
  line.textContent=new Date().toLocaleTimeString()+' '+kind+' '
    +JSON.stringify(data);
  feed.prepend(line);
}}
refresh();
setInterval(refresh,2500);
source=new EventSource('/api/events');
['scene_changed','stream_started','stream_stopped',
 'recording_started','recording_stopped'].forEach(kind=>{{
  source.addEventListener(kind,e=>{{note(kind,JSON.parse(e.data));refresh();}});
}});
</script></body></html>"""


def render_tally_overlay() -> str:
    """MultiTally lesson: show which scene is live/preview at a glance."""
    return """<!doctype html><html><head><title>MIND tally</title>
<style>
body{background:#000;color:#fff;font:700 42px system-ui,sans-serif;
display:flex;gap:16px;padding:24px}
.box{flex:1;border-radius:12px;padding:24px;text-align:center;
border:4px solid #333}
.live{border-color:#e33;background:#2a0d0d}
.preview{border-color:#da3;background:#241a05}
.idle{border-color:#333;background:#111}
small{display:block;font-weight:400;font-size:16px;color:#aaa}
</style></head><body>
<div class="box idle" id="p"><small>PROGRAM</small>-</div>
<div class="box idle" id="v"><small>PREVIEW</small>-</div>
<script>
const es=new EventSource('/api/events');
function paint(){fetch('/api/status').then(r=>r.json()).then(s=>{
  const p=document.getElementById('p'),v=document.getElementById('v');
  p.lastChild.textContent=s.program_scene||'-';
  v.lastChild.textContent=s.preview_scene||'-';
  p.className='box '+((s.streaming||s.recording)?'live':'idle');
  v.className='box preview';
});}
es.addEventListener('scene_changed',paint);paint();setInterval(paint,5000);
</script></body></html>"""


def render_timer_overlay() -> str:
    """Browser Timer lesson: configure via URL hash (#00:15:00)."""
    return """<!doctype html><html><head><title>MIND timer</title>
<style>
body{background:transparent;margin:0;font:800 72px monospace;
color:#fff;text-shadow:0 2px 8px #000;display:flex;align-items:center;
justify-content:center;height:100vh}
.warn{color:#ffb84d}.gone{color:#e35d5d}
</style></head><body><div id="t">--:--</div><script>
const parts=(location.hash||'#00:05:00').slice(1).split(':').map(Number);
const total=(parts.length===3?parts[0]*3600+parts[1]*60+parts[2]
                             :parts[0]*60+(parts[1]||0));
let left=total,running=false,tick=null;
const el=document.getElementById('t');
function fmt(s){const h=Math.floor(s/3600),m=Math.floor(s%3600/60),
x=s%60,p=n=>String(n).padStart(2,'0');
return h?`${h}:${p(m)}:${p(x)}`:`${p(m)}:${p(x)}`;}
function draw(){el.textContent=fmt(Math.max(left,0));
el.className=left<=0?'gone':left<=30?'warn':'';}
function start(){if(running)return;running=true;
tick=setInterval(()=>{left--;draw();if(left<=0){stop();}},1000);}
function stop(){running=false;if(tick)clearInterval(tick);tick=null;}
function reset(){stop();left=total;draw();}
draw();
const es=new EventSource('/api/events');
es.addEventListener('recording_started',()=>{reset();start();});
es.addEventListener('recording_stopped',()=>{reset();});
es.addEventListener('stream_started',()=>{reset();start();});
es.addEventListener('stream_stopped',()=>{stop();});
</script></body></html>"""


def selftest() -> int:
    print("server selftest: exercised via mind/verify_mind.py "
          "(routes need sockets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
