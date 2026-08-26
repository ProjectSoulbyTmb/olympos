import json
import socketserver
import threading

from . import config


class ControlServer(threading.Thread):
    def __init__(self, dispatch):
        super().__init__(daemon=True, name="control")
        self.dispatch = dispatch
        self.stop_event = threading.Event()

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    line = self.rfile.readline()
                    if not line:
                        return
                    req = json.loads(line.decode("utf-8"))
                    cmd = req.get("cmd", "")
                    arg = req.get("arg")
                    resp = self.server.dispatch(cmd, arg)
                except Exception as e:
                    resp = {"ok": False, "error": str(e)}
                try:
                    self.wfile.write(
                        (json.dumps(resp, default=str) + "\n").encode("utf-8")
                    )
                except OSError:
                    pass

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server((config.CONTROL_HOST, config.CONTROL_PORT), Handler)
        self.server.dispatch = dispatch

    def run(self):
        self.server.serve_forever(poll_interval=0.5)

    def request_stop(self):
        self.stop_event.set()
        threading.Thread(target=self.server.shutdown, daemon=True).start()
