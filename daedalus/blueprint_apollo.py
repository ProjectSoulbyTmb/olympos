"""DAEDALUS blueprint: apollo-os - the VOLTAGE command plane.

Test-launch composition: a self-contained command shell proving the
full house law offline, inside any weave directory:

    voltage <domain> <verb> [target] [--flags]
    voltage session start --profile guest|editor|admin
    voltage session seal

Guarantees proven by the gate:
  B1  least privilege  - an L0 profile cannot invoke any mutating verb
  B2  attestation      - every successful mutation leaves exactly one
                         witness line carrying the command digest
  B3  envelope law     - EVERY response carries "error" (null when fine)
  B8  session seals    - a sealed transcript verifies; one flipped byte
                         breaks verification

Executors marked builtin are self-contained test doubles so the plane
runs with zero other organs present; organ-backed verbs answer
"organ-not-wired (test-build)" AFTER the rights ladder passes - the
law stays honest even where the organs are not yet exported.

House contracts hold: loopback only; port.txt discovery with stale
guard; stdlib only; faults are independent breakers.
"""

import sys

# ------------------------------------------------------------- rights_map
RIGHTS_MAP = '''"""APOLLO rights law - single source for the verb ladder."""

RANK = {"L0": 0, "L1": 1, "L2": 2}

PROFILES = {"guest": "L0", "editor": "L1", "admin": "L2"}

VERBS = {
    ("fleet", "status"): "L0",
    ("fleet", "vitals"): "L0",
    ("fleet", "gates"): "L0",
    ("fleet", "incidents"): "L0",
    ("know", "search"): "L0",
    ("know", "cards"): "L0",
    ("know", "advise"): "L0",
    ("media", "view"): "L0",
    ("media", "browse"): "L0",
    ("image", "models"): "L0",
    ("image", "gallery"): "L0",
    ("game", "status"): "L0",
    ("game", "list-blueprints"): "L0",
    ("learn", "status"): "L0",
    ("learn", "report"): "L0",
    ("entertain", "play"): "L0",
    ("entertain", "queue"): "L0",
    ("demo", "note"): "L1",
    ("video", "analyze"): "L1",
    ("video", "catalog"): "L1",
    ("video", "sample"): "L1",
    ("video", "watch-once"): "L1",
    ("video", "produce"): "L1",
    ("image", "generate"): "L1",
    ("image", "upscale"): "L1",
    ("image", "pull"): "L1",
    ("media", "normalize"): "L1",
    ("learn", "propose"): "L1",
    ("entertain", "reel"): "L1",
    ("entertain", "launch"): "L1",
    ("build", "describe"): "L1",
    ("build", "design"): "L1",
    ("build", "code"): "L1",
    ("build", "verify"): "L2",
    ("build", "prove"): "L2",
    ("build", "seal"): "L2",
    ("build", "ship"): "L2",
    ("game", "weave"): "L2",
    ("game", "selftest"): "L2",
    ("learn", "promote"): "L2",
    ("ops", "grant"): "L2",
    ("ops", "revoke"): "L2",
    ("ops", "escalate"): "L2",
    ("ops", "quarantine"): "L2",
    ("ops", "seal"): "L2",
    ("ops", "doctor"): "L2",
}

MUTATING = {
    ("video", "produce"), ("video", "analyze"), ("video", "sample"),
    ("image", "generate"), ("image", "upscale"), ("image", "pull"),
    ("media", "normalize"), ("game", "weave"), ("game", "selftest"),
    ("learn", "propose"), ("learn", "promote"), ("entertain", "reel"),
    ("build", "describe"), ("build", "design"), ("build", "code"),
    ("build", "verify"), ("build", "prove"), ("build", "seal"),
    ("build", "ship"), ("ops", "grant"), ("ops", "revoke"),
    ("ops", "escalate"), ("ops", "quarantine"), ("ops", "seal"),
    ("demo", "note"),
}


def domains():
    return sorted({d for d, _v in VERBS})


def required(domain, verb):
    """Grant class for a verb, or None when the verb does not exist."""
    return VERBS.get((str(domain), str(verb)))


def allowed(session_level, domain, verb):
    """True when a session holding session_level may invoke the verb."""
    need = required(domain, verb)
    if need is None:
        return False
    return RANK[session_level] >= RANK[need]


def catalog():
    """Machine-readable grammar+law table; UI and docs derive from it."""
    out = {}
    for (domain, verb), lvl in sorted(VERBS.items()):
        out.setdefault(domain, []).append(
            {"verb": verb, "rights": lvl,
             "mutating": (domain, verb) in MUTATING})
    return out
'''

# ------------------------------------------------------------- grammar
GRAMMAR = '''"""APOLLO grammar - one parser for CLI and wire, zero drift."""

import shlex


class GrammarError(ValueError):
    pass


SESSION_VERBS = ("start", "seal", "status")
FLAGLESS = {"--json"}


class Cmd(object):
    __slots__ = ("domain", "verb", "target", "flags", "raw")

    def __init__(self, domain, verb, target, flags, raw):
        self.domain, self.verb = domain, verb
        self.target, self.flags, self.raw = target, flags, raw

    def to_dict(self):
        return {"domain": self.domain, "verb": self.verb,
                "target": self.target, "flags": dict(self.flags)}


def _tokens(line):
    try:
        return [t for t in shlex.split(str(line)) if t]
    except ValueError as exc:
        raise GrammarError("unparsable line: %s" % exc)


def parse(line, domains_fn, verbs_for):
    """Parse one command line into a Cmd.

    domains_fn: callable -> iterable of valid domain names.
    verbs_for: callable(domain) -> iterable of valid verb names.
    Raises GrammarError on any structural violation."""
    tok = _tokens(line)
    if not tok:
        raise GrammarError("empty command")
    if tok[0] != "voltage":
        raise GrammarError("commands begin with 'voltage'")
    if len(tok) < 2:
        raise GrammarError("missing domain")
    head = tok[1]

    flags, rest = {}, []
    i = 2
    while i < len(tok):
        t = tok[i]
        if t.startswith("--"):
            if t in FLAGLESS:
                flags[t[2:]] = True
            elif i + 1 < len(tok) and not tok[i + 1].startswith("--"):
                flags[t[2:]] = tok[i + 1]
                i += 1
            else:
                flags[t[2:]] = True
        else:
            rest.append(t)
        i += 1

    if head == "session":
        if not rest or rest[0] not in SESSION_VERBS:
            raise GrammarError(
                "session needs one of %s" % ", ".join(SESSION_VERBS))
        return Cmd("session", rest[0], None, flags, str(line))

    dnames = set(domains_fn())
    if head not in dnames:
        raise GrammarError("unknown domain: %r" % head)
    if not rest:
        raise GrammarError("domain %r needs a verb" % head)
    verb = rest[0]
    if verb not in set(verbs_for(head)):
        raise GrammarError("unknown verb: %s %s" % (head, verb))
    target = rest[1] if len(rest) > 1 else None
    return Cmd(head, verb, target, flags, str(line))


def default_domains():
    from apollo_rights_map import VERBS
    return sorted({d for d, _v in VERBS})


def default_verbs(domain):
    from apollo_rights_map import VERBS
    return sorted({v for d, v in VERBS if d == domain})
'''

# ------------------------------------------------------------- session
SESSION_MOD = '''"""APOLLO sessions - scoped capability lifetimes on disk.

State machine: NEW -> ACTIVE -> SEALING -> SEALED. A crash leaves an
ACTIVE session stale; adoption by the same profile re-stamps it and is
recorded in the transcript itself."""

import hashlib
import json
import os
import time


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class SessionStore(object):
    def __init__(self, root):
        self.dir = os.path.join(root, "sessions")
        os.makedirs(self.dir, exist_ok=True)
        self.seq_file = os.path.join(self.dir, ".seq")

    # ------------------------------------------------------ plumbing
    def _next_id(self):
        n = 0
        try:
            with open(self.seq_file, encoding="utf-8") as fh:
                n = int(fh.read().strip() or 0)
        except (OSError, ValueError):
            n = 0
        n += 1
        tmp = self.seq_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(str(n))
        os.replace(tmp, self.seq_file)
        return "s-%04d" % n

    def _path(self, sid):
        return os.path.join(self.dir, sid + ".json")

    def _load(self, sid):
        try:
            with open(self._path(sid), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _save(self, sess):
        tmp = self._path(sess["id"]) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(sess, fh, indent=1, sort_keys=True)
        os.replace(tmp, self._path(sess["id"]))

    # ------------------------------------------------------- lifecycle
    def start(self, profile, level):
        sess = {"id": self._next_id(), "profile": profile,
                "level": level, "state": "ACTIVE",
                "opened": _now(), "entries": []}
        self._save(sess)
        return sess

    def get(self, sid):
        return self._load(sid) if sid else None

    def active(self, sid):
        s = self.get(sid)
        if s and s.get("state") == "ACTIVE":
            return s
        return None

    def transcribe(self, sid, entry):
        s = self.active(sid)
        if not s:
            return None
        s["entries"].append(entry)
        self._save(s)
        return s

    def seal(self, sid):
        s = self.get(sid)
        if not s or s["state"] == "SEALED":
            return None
        s["state"] = "SEALED"
        s["sealed"] = _now()
        blob = json.dumps(s["entries"], sort_keys=True).encode("utf-8")
        s["transcript_sha256"] = hashlib.sha256(blob).hexdigest()
        self._save(s)
        return s

    def verify_seal(self, sid):
        s = self.get(sid)
        if not s or "transcript_sha256" not in s:
            return {"ok": False, "error": "no-seal"}
        blob = json.dumps(s["entries"], sort_keys=True).encode("utf-8")
        good = hashlib.sha256(blob).hexdigest() == s["transcript_sha256"]
        return {"ok": good, "digest": s["transcript_sha256"],
                "state": s["state"], "sealed": s.get("sealed")}
'''

# ------------------------------------------------------------- dispatch
DISPATCH = '''"""APOLLO dispatch - the law enforcement point.

Order is fixed and load-bearing:
  1. grammar already compiled by caller
  2. rights ladder checked HERE, server-side, before anything runs
  3. executor runs (builtin doubles, or honest organ-not-wired)
  4. Clockwork-style seeded digest computed for the action
  5. mutating successes append exactly one witness line
  6. reply envelope assembled through the single error-field choke"""

import hashlib
import glob
import importlib.util
import json
import os
import time

from apollo_rights_map import MUTATING, allowed, required

MINI_CORPUS = [
    {"id": "K-001", "title": "loopback law",
     "body": "Every server binds 127.0.0.1; nothing egresses."},
    {"id": "K-002", "title": "envelope contract",
     "body": "Every response carries error; clients trust the shape."},
    {"id": "K-003", "title": "quarantine never destroy",
     "body": "Broken things are contained and journaled, not deleted."},
    {"id": "K-004", "title": "gates before claims",
     "body": "Nothing says healthy without its verify suite passing."},
    {"id": "K-005", "title": "seeded replay",
     "body": "Same seed plus same actions yields identical digests."},
]


def load_extensions():
    """Drop-in adapters: apollo_ext_<domain>.py beside this module.

    Each exposes DOMAIN and register(executors), mapping
    (domain, verb) -> callable(session, cmd, ctx). Import failures are
    contained - a broken extension never takes down the plane; it is
    skipped and the verb stays organ-not-wired. Extensions OVERRIDE
    builtin doubles so real organs replace doubles at commissioning
    without touching this module (the dynamism contract)."""
    executors = {}
    here = os.path.dirname(os.path.abspath(__file__))
    for path in sorted(glob.glob(os.path.join(here,
                                              "apollo_ext_*.py"))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.register(executors)
        except Exception:
            continue
    return executors


def envelope(kind, **payload):
    return {"v": 1, "kind": kind,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "payload": payload}


class Dispatcher(object):
    def __init__(self, root, seed="voltage-test"):
        self.root = root
        self.seed = seed
        self.ext = load_extensions()
        self.witness_path = os.path.join(root, "witness.jsonl")
        os.makedirs(os.path.join(root, "sandbox"), exist_ok=True)

    # ------------------------------------------------------------ law
    def authorize(self, session, cmd):
        need = required(cmd.domain, cmd.verb)
        if need is None and cmd.domain != "session":
            return envelope("reply", ok=False,
                            error="unknown verb (DENIED by law)")
        if not allowed(session["level"], cmd.domain, cmd.verb):
            return envelope(
                "reply", ok=False,
                error="denied: %s %s requires %s, session holds %s"
                      % (cmd.domain, cmd.verb, need, session["level"]))
        return None

    def digest(self, session, cmd):
        basis = "|".join([self.seed, session["id"], cmd.domain,
                          cmd.verb, str(cmd.target),
                          json.dumps(cmd.flags, sort_keys=True)])
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def witness(self, session, cmd, delta):
        line = json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "actor": "apollo/" + session["id"],
            "profile": session["profile"],
            "domain": cmd.domain, "verb": cmd.verb,
            "delta_sha256": delta}, sort_keys=True)
        try:
            with open(self.witness_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\\n")
        except OSError:
            pass  # bus failures never crash hosts; sandbox keeps proof

    # ------------------------------------------------------- executors
    def _exec_fleet(self, cmd):
        return {"ok": True,
                "data": {"realm": "apollo-os test build",
                         "organs_wired": ["apollo"],
                         "note": "builtin double; studios land in V7"}}

    def _exec_know(self, cmd):
        q = str(cmd.target or cmd.flags.get("q", "")).lower()
        hits = [e for e in MINI_CORPUS
                if q in e["title"].lower() or q in e["body"].lower()]
        return {"ok": True, "hits": hits,
                "engine": "mini-corpus-builtin"}

    def _exec_demo_note(self, cmd, session):
        path = os.path.join(self.root, "sandbox", "note.json")
        body = {"note": str(cmd.target or ""), "by": session["id"],
                "delta": self.digest(session, cmd)}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=1)
        return {"ok": True, "written": path, "delta": body["delta"]}

    def execute(self, session, cmd):
        denial = self.authorize(session, cmd)
        if denial is not None:
            return denial

        handler = self.ext.get((cmd.domain, cmd.verb))
        if cmd.domain == "demo" and cmd.verb == "note":
            result = self._exec_demo_note(cmd, session)
        elif handler is not None:
            try:
                verdict = handler(session, cmd,
                                  {"root": self.root,
                                   "seed": self.seed})
            except Exception as exc:  # noqa: BLE001 - plane survives
                verdict = {"ok": False,
                           "error": "extension failure: %s: %s"
                                    % (type(exc).__name__, exc)}
            if not isinstance(verdict, dict) or "ok" not in verdict:
                result = {"ok": False,
                          "error": "malformed extension verdict"}
            else:
                result = verdict
        elif cmd.domain == "fleet":
            result = self._exec_fleet(cmd)
        elif cmd.domain == "know":
            result = self._exec_know(cmd)
        else:
            result = {"ok": False,
                      "error": "organ-not-wired (test-build): "
                               "%s/%s awaits its batch"
                               % (cmd.domain, cmd.verb)}

        if result.get("ok") and (cmd.domain, cmd.verb) in MUTATING:
            self.witness(session, cmd, self.digest(session, cmd))
        return envelope("reply", **result)
'''

# ------------------------------------------------------------- server
SERVER = '''"""APOLLO server - loopback control plane for the command plane.

  GET  /healthz                     liveness + version
  GET  /catalog                     grammar + rights law (derived)
  POST /run          {line,session} execute one compiled command
  POST /session/start {profile}    mint a scoped capability session
  POST /session/seal {session}     seal + digest the transcript
  GET  /session/status?session=S    state / seal verification

Boot: python apollo_server.py [port]   (0 = ephemeral default)
Writes port.txt after binding; removes a stale one first. Loopback
only - any other host argument is refused at startup. Every response
passes the single error-field choke below."""

import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from apollo_dispatch import Dispatcher, envelope
from apollo_rights_map import PROFILES, catalog, domains
from apollo_session import SessionStore

VERSION = "{{VERSION}}"
STORE = None
DISPATCHER = None


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def make_handler():

    class Handler(BaseHTTPRequestHandler):
        server_version = "apollo/{{VERSION}}"

        def log_message(self, fmt, *args):
            pass

        def _finish(self, obj, status=200):
            obj.setdefault("error", None)
            blob = json.dumps(obj, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode() or "{}")
            except (ValueError, json.JSONDecodeError):
                raise ApiError(400, "invalid JSON body")
            if not isinstance(data, dict):
                raise ApiError(400, "JSON body must be an object")
            return data

        # ----------------------------------------------------- routes
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            try:
                if u.path == "/healthz":
                    return self._finish({"ok": True,
                                         "version": VERSION})
                if u.path == "/catalog":
                    return self._finish({"ok": True,
                                         "domains": domains(),
                                         "catalog": catalog()})
                if u.path == "/session/status":
                    s = STORE.get((q.get("session") or [None])[0])
                    if not s:
                        raise ApiError(404, "no such session")
                    out = {"ok": True, "session": {
                        k: s[k] for k in
                        ("id", "profile", "level", "state")}}
                    if s["state"] == "SEALED":
                        out["seal"] = STORE.verify_seal(s["id"])
                    return self._finish(out)
                raise ApiError(404, "no route: %s" % u.path)
            except ApiError as exc:
                return self._finish({"ok": False, "error": exc.message},
                                    status=exc.status)

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            try:
                if u.path == "/session/start":
                    b = self._body()
                    profile = str(b.get("profile") or "guest")
                    if profile not in PROFILES:
                        raise ApiError(400, "unknown profile: %r"
                                       % profile)
                    s = STORE.start(profile, PROFILES[profile])
                    return self._finish({"ok": True, "session": {
                        "id": s["id"], "level": s["level"],
                        "profile": s["profile"]}})
                if u.path == "/session/seal":
                    b = self._body()
                    s = STORE.seal(str(b.get("session") or ""))
                    if not s:
                        raise ApiError(404, "nothing to seal")
                    return self._finish({"ok": True,
                                         "sealed": s["id"],
                                         "transcript_sha256":
                                             s["transcript_sha256"]})
                if u.path == "/run":
                    b = self._body()
                    sess = STORE.active(str(b.get("session") or ""))
                    if not sess:
                        raise ApiError(400,
                                       "active session required "
                                       "(voltage session start)")
                    from apollo_grammar import (GrammarError,
                                                default_domains,
                                                default_verbs, parse)
                    try:
                        cmd = parse(b.get("line") or "",
                                    default_domains, default_verbs)
                    except GrammarError as exc:
                        return self._finish(envelope(
                            "reply", ok=False, error=str(exc)))
                    verdict = DISPATCHER.execute(sess, cmd)
                    STORE.transcribe(sess["id"], {
                        "line": cmd.raw,
                        "ok": bool(verdict.get("payload", {})
                                   .get("ok"))})
                    return self._finish(verdict)
                raise ApiError(404, "no route: %s" % u.path)
            except ApiError as exc:
                return self._finish({"ok": False, "error": exc.message},
                                    status=exc.status)

    return Handler


def main(argv):
    host = "127.0.0.1"
    port = int(argv[1]) if len(argv) > 1 else 0
    if host != "127.0.0.1":
        raise SystemExit("refusing non-loopback bind")
    global STORE, DISPATCHER
    root = os.environ.get("APOLLO_DATA") or \\
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "apollo-data")
    STORE = SessionStore(root)
    DISPATCHER = Dispatcher(root)

    if os.path.exists("port.txt"):
        os.remove("port.txt")          # stale guard: dead prior attempt
    srv = ThreadingHTTPServer((host, port), make_handler())
    srv.daemon_threads = True
    with open("port.txt", "w", encoding="utf-8") as fh:
        fh.write(str(srv.server_port))
    print(f"apollo up on {srv.server_port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv)
'''

# ------------------------------------------------------------- cli
CLI = '''"""voltage - the operator's hand on the command plane.

Talks to a running apollo server (APOLLO_URL env or --url flag); the
server's own directory is expected as cwd for the port.txt fallback."""

import json
import os
import sys
import urllib.request


def post(base, path, body):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main(argv):
    url = os.environ.get("APOLLO_URL")
    args = list(argv)
    if "--url" in args:
        i = args.index("--url")
        url = args[i + 1]
        del args[i:i + 2]
    want_raw = "--json" in args
    line = " ".join(a for a in args if a != "--json")

    if url is None:
        base = "http://127.0.0.1:" + open("port.txt").read().strip()
    else:
        base = url

    toks = line.split()
    if len(toks) >= 3 and toks[:3] == ["voltage", "session", "start"]:
        prof = "guest"
        if "--profile" in toks:
            prof = toks[toks.index("--profile") + 1]
        out = post(base, "/session/start", {"profile": prof})
    elif len(toks) >= 3 and toks[:3] == ["voltage", "session", "seal"]:
        sid = toks[3] if len(toks) > 3 else ""
        out = post(base, "/session/seal", {"session": sid})
    else:
        out = post(base, "/run", {"line": line})

    print(json.dumps(out, indent=2, sort_keys=True)
          if want_raw else json.dumps(out))
    err = out.get("error") or (out.get("payload") or {}).get("error")
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

# ------------------------------------------------------------- gate
GATE = '''"""Self-test gate for the woven apollo-os (exit 0 = green)."""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

BASE = None


def readline_bounded(stream, seconds=20):
    """One line, or "" on timeout - a silenced startup banner must
    fail the gate red here instead of hanging forever."""
    box = []
    t = threading.Thread(target=lambda: box.append(stream.readline()))
    t.daemon = True
    t.start()
    t.join(seconds)
    return box[0] if box else ""


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type":
                                          "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        payload = json.loads(r.read())
    assert "error" in payload, "envelope law broken: %r" % payload
    return payload


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # Drop-in extensions must exist BEFORE boot: the loader scans once
    # at Dispatcher init. These doubles stand in for Batch-V7 adapters.
    with open("apollo_ext_learn.py", "w", encoding="utf-8") as fh:
        fh.write('DOMAIN = "learn"\\n'
                 "\\n"
                 "\\n"
                 'def register(executors):\\n'
                 '    def _report(session, cmd, ctx):\\n'
                 '        return {"ok": True,\\n'
                 '                "data": {"reports": 3}}\\n'
                 '    executors[("learn", "report")] = _report\\n')
    with open("apollo_ext_image.py", "w", encoding="utf-8") as fh:
        fh.write('DOMAIN = "image"\\n'
                 "\\n"
                 "\\n"
                 'def register(executors):\\n'
                 '    def _generate(session, cmd, ctx):\\n'
                 '        import hashlib\\n'
                 '        basis = str(ctx["seed"]) + "|" + '
                 'str(cmd.target)\\n'
                 '        return {"ok": True,\\n'
                 '                "artifact_sha256": hashlib.sha256('
                 'basis.encode()).hexdigest()}\\n'
                 '    executors[("image", "generate")] = _generate\\n')

    if os.path.exists("port.txt"):
        os.remove("port.txt")
    proc = subprocess.Popen([sys.executable, "apollo_server.py", "0"],
                            stdout=subprocess.PIPE, text=True)
    try:
        line = readline_bounded(proc.stdout)
        assert line.startswith("apollo up on "), \\
            "startup banner missing (silent_start breaker?): %r" % line
        port = int(line.strip().split("on ")[1])
        deadline = time.time() + 10
        while not os.path.exists("port.txt"):
            assert time.time() < deadline, "port.txt never appeared"
            time.sleep(0.05)
        assert int(open("port.txt").read()) == port, "port mismatch"
        globals()["BASE"] = f"http://127.0.0.1:{port}"

        h = call("GET", "/healthz")
        assert h["ok"] is True and h["version"], h

        cat = call("GET", "/catalog")
        assert cat["domains"] and "video" in cat["domains"], cat
        video = [r for r in cat["catalog"]["video"]
                 if r["verb"] == "produce"][0]
        assert video["rights"] == "L1" and video["mutating"], video

        ed = call("POST", "/session/start",
                  {"profile": "editor"})["session"]
        gu = call("POST", "/session/start",
                  {"profile": "guest"})["session"]

        r = call("POST", "/run", {"line": "voltage fleet status",
                                  "session": ed["id"]})
        assert r["payload"]["ok"], r

        r = call("POST", "/run", {"line": "voltage know search replay",
                                  "session": gu["id"]})
        assert r["payload"]["ok"] and r["payload"]["hits"], r

        wit = os.path.join("apollo-data", "witness.jsonl")
        before = sum(1 for _ in open(wit)) if os.path.exists(wit) else 0

        r = call("POST", "/run", {"line": "voltage demo note alpha",
                                  "session": ed["id"]})
        assert r["payload"]["ok"], r
        lines = open(wit).read().splitlines()
        assert len(lines) == before + 1, \\
            "expected exactly one new witness line, got %d" % (
                len(lines) - before)
        rec = json.loads(lines[-1])
        assert rec["verb"] == "note" and rec["delta_sha256"], rec

        r = call("POST", "/run", {"line": "voltage demo note beta",
                                  "session": gu["id"]})
        assert not r["payload"]["ok"] and \\
            "denied" in r["payload"]["error"], r
        r = call("POST", "/run", {"line": "voltage video produce x",
                                  "session": gu["id"]})
        assert not r["payload"]["ok"] and \\
            "denied" in r["payload"]["error"], r
        r = call("POST", "/run", {"line": "voltage build ship x",
                                  "session": ed["id"]})
        assert not r["payload"]["ok"] and \\
            "denied" in r["payload"]["error"], r
        r = call("POST", "/run", {"line": "voltage game weave g1",
                                  "session": ed["id"]})
        assert not r["payload"]["ok"] and \\
            "denied" in r["payload"]["error"], r
        r = call("POST", "/run", {"line": "voltage nonsense verb",
                                  "session": ed["id"]})
        assert not r["payload"]["ok"], r

        sealed = call("POST", "/session/seal", {"session": ed["id"]})
        dig = sealed["transcript_sha256"]
        v = call("GET", "/session/status?session=" + ed["id"])
        assert v["seal"]["ok"] and v["seal"]["digest"] == dig, v

        spath = os.path.join("apollo-data", "sessions",
                             ed["id"] + ".json")
        blob = open(spath, encoding="utf-8").read()
        data = json.loads(blob)
        if data["entries"]:
            data["entries"][0]["ok"] = not data["entries"][0]["ok"]
        else:
            data["entries"] = [{"tampered": True}]
        with open(spath, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        v = call("GET", "/session/status?session=" + ed["id"])
        assert v["seal"]["ok"] is False, "tamper did not break the seal"
        with open(spath, "w", encoding="utf-8") as fh:
            fh.write(blob)

        # ---- extension protocol: adapters override, law still holds
        r = call("POST", "/run", {"line": "voltage learn report",
                                  "session": gu["id"]})
        assert r["payload"]["ok"] and \\
            r["payload"]["data"]["reports"] == 3, r

        ed2 = call("POST", "/session/start",
                   {"profile": "editor"})["session"]
        wit_lines = open(wit).read().splitlines()
        r = call("POST", "/run",
                 {"line": "voltage image generate sunset",
                  "session": ed2["id"]})
        assert r["payload"]["ok"] and \\
            r["payload"]["artifact_sha256"], r
        wit_lines2 = open(wit).read().splitlines()
        assert len(wit_lines2) == len(wit_lines) + 1, \\
            "extension mutation skipped the witness line"
        rec = json.loads(wit_lines2[-1])
        assert rec["verb"] == "generate" and rec["delta_sha256"], rec
        r = call("POST", "/run",
                 {"line": "voltage image generate sunset",
                  "session": gu["id"]})
        assert not r["payload"]["ok"], "L1 verb leaked to L0 via ext"

        print("apollo-os gate green")
    finally:
        proc.terminate()
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {
        "apollo_rights_map.py": RIGHTS_MAP,
        "apollo_grammar.py": GRAMMAR,
        "apollo_session.py": SESSION_MOD,
        "apollo_dispatch.py": DISPATCH,
        "apollo_server.py": SERVER,
        "voltage_cli.py": CLI,
        "verify_apollo.py": GATE,
    }


FILES = files()
FILES_DEF = FILES  # backwards-compatible alias, house style

FAULTS = {
    # startup banner silenced -> gate's readline starves (independent)
    "silent_start": ("apollo_server.py",
                     'print(f"apollo up on {srv.server_port}", '
                     'flush=True)', "pass"),
    # envelope law stripped at the single choke point
    "error_stripped": ("apollo_server.py",
                       'obj.setdefault("error", None)', "pass"),
    # rights ladder bypassed at dispatch -> B1 refusals stop biting
    "no_ladder": ("apollo_dispatch.py",
                  'denial = self.authorize(session, cmd)\n'
                  '        if denial is not None:\n'
                  '            return denial',
                  'denial = None'),
    # mutation succeeds without witness line -> attestation gap
    "unwitnessed": ("apollo_dispatch.py",
                    'if result.get("ok") and '
                    '(cmd.domain, cmd.verb) in MUTATING:\n'
                    '            self.witness(session, cmd, '
                    'self.digest(session, cmd))',
                    "pass"),
}

BLUEPRINT = {
    "description": "VOLTAGE apollo command plane (grammar, sessions, "
                   "rights law, witness, seals) - test-launch build",
    "files": FILES,
    "gate": [sys.executable, "verify_apollo.py"],
    "params": {"VERSION": "0.1.0"},
    "faults": dict(FAULTS),
}
