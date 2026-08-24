"""ZEUS verify suite - gates every behavioral change.

Run: python zeus/verify_zeus.py   (exit 0 = all checks pass)
"""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from aegis import Aegis                # noqa: E402
import bolt                             # noqa: E402
import content                          # noqa: E402
from kernel import Kernel, sandbox      # noqa: E402
import oracle as oracle_mod             # noqa: E402
import procsys                          # noqa: E402
from sdk import ZeusClient, ZeusSDK, wire_client  # noqa: E402
import sentinel as sentinel_mod         # noqa: E402
from server import ZeusServer           # noqa: E402


def sleeper(extra="time.sleep(120)"):
    proc = subprocess.Popen(
        [sys.executable, "-c", f"import time; {extra}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def wait_alive(table, pid, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pid in table.sample():
            return True
        time.sleep(0.05)
    return False


def check_content_integrity():
    for entry in content.WATCH_MANIFEST:
        if entry.get("kind") not in ("image", "contains"):
            return f"bad watch kind: {entry}"
        if "name" not in entry or "match" not in entry:
            return "watch missing name/match"
    if len(set(content.OWNED_PORTS)) != len(content.OWNED_PORTS):
        return "duplicate owned ports"
    if content.CPU_SOFT_PCT >= content.CPU_HARD_PCT:
        return "soft CPU limit must sit under hard limit"
    if content.SERVER_PORT == 43901:
        return "zeus port collides with vulcan"
    for root in content.PROTECTED_ROOTS:
        path = os.path.join(content.WORKSPACE, root)
        if not os.path.exists(path):
            return f"protected root missing: {root}"
    return True


def check_proc_snapshot_sees_self():
    if not procsys.IS_WINDOWS:
        return True                      # degraded platform: layer inert
    table = procsys.ProcTable()
    snap = table.sample()
    me = snap.get(os.getpid())
    if me is None:
        return "own process missing from snapshot"
    if "python" not in me.name.lower():
        return f"own image name odd: {me.name!r}"
    if me.mem_mb <= 0:
        return "working set not measured"
    return True


def check_cpu_accounting():
    proc = sleeper("t0=time.time()\nwhile time.time()-t0 < 6: pass")
    try:
        table = procsys.ProcTable()
        if not wait_alive(table, proc.pid):
            return "sleeper never appeared"
        time.sleep(1.2)                  # let it burn between samples
        info = table.sample().get(proc.pid)
        if info is None:
            return "sleeper vanished mid-check"
        if info.cpu_pct is None:
            return "second sample still has no CPU delta"
        if not 0 <= info.cpu_pct <= 100 * (os.cpu_count() or 1):
            return f"cpu_pct out of range: {info.cpu_pct}"
        if info.cpu_pct < 1.0:
            return f"busy spinner shows only {info.cpu_pct}%"
        return True
    finally:
        proc.kill()


def check_tcp_listeners():
    server = ZeusServer(port=0, auto_patrol=False)
    server._bind()
    try:
        rows = procsys.tcp_listeners()
        mine = [r for r in rows if r[1] == server.port]
        if not mine:
            return f"bound port {server.port} absent from listener table"
        return True
    finally:
        server.running = False


def check_sentinel_death_detection():
    proc = sleeper()
    sent = sentinel_mod.Sentinel()
    try:
        if not wait_alive(sent.table, proc.pid):
            return "sleeper never appeared"
        sent.pin_pid(proc.pid, name="verify-sleeper")
        finds, _snap = sent.patrol()
        if any(f["type"] == "proc_death" for f in finds):
            return "live pinned pid reported dead"
        proc.kill()
        proc.wait(timeout=5)
        finds, _snap = sent.patrol()
        deaths = [f for f in finds if f["type"] == "proc_death"
                  and f.get("watch") == "verify-sleeper"]
        if not deaths:
            return "killed pin was not reported"
        if deaths[0]["on_death"] != "alert":
            return "pin death lost its policy"
        return True
    finally:
        if proc.poll() is None:
            proc.kill()


def check_runaway_escalation():
    class FakeTable:
        def __init__(self, snap):
            self.snap = snap

        def sample(self):
            return self.snap

    from procsys import ProcInfo
    hot = ProcInfo(pid=999999, name="burn.exe", exe="C:\\tmp\\burn.exe",
                   mem_mb=10.0, cpu_pct=99.0)
    sent = sentinel_mod.Sentinel(proc_table=FakeTable({999999: hot}))
    sent.pin_pid(424242, name="ghost")     # must not crash on absent row
    confirmed = []
    for _ in range(content.RUNAWAY_SAMPLES + 1):
        finds, snap = sent.patrol()
        confirmed += [f for f in finds if f["type"] == "runaway"]
    if len(confirmed) != 1:
        return f"runaway fired {len(confirmed)} times (want exactly 1)"
    if confirmed[0]["pid"] != 999999:
        return "runaway attributed to wrong pid"
    for _ in range(3):                   # latch must hold while it burns
        finds, _snap = sent.patrol()
        confirmed += [f for f in finds if f["type"] == "runaway"]
    if len(confirmed) != 1:
        return f"latch failed: refired to {len(confirmed)}"
    from procsys import ProcInfo as _PI
    calm = _PI(pid=999999, name="burn.exe",
               exe="C:\\tmp\\burn.exe", mem_mb=10.0, cpu_pct=4.0)
    sent.table = FakeTable({999999: calm})
    sent.patrol()                        # recovery tick re-arms
    sent.table = FakeTable({999999: hot})
    refire = []
    for _ in range(content.RUNAWAY_SAMPLES + 1):
        finds, _snap = sent.patrol()
        refire += [f for f in finds if f["type"] == "runaway"]
        if refire:
            break
    if len(refire) != 1:
        return "latch never re-armed after recovery"
    quiet = sentinel_mod.Sentinel(
        proc_table=FakeTable({1: ProcInfo(pid=1, accessible=False)}))
    finds, snap = quiet.patrol()
    if any(f["type"] == "runaway" for f in finds):
        return "dark system process flagged as runaway"
    return True


def check_bolt_rails():
    if bolt.check_kill_allowed(0) is None:
        return "system idle pid passed rails"
    if bolt.check_kill_allowed(4) is None:
        return "kernel pid passed rails"
    if bolt.check_kill_allowed(os.getpid()) is None:
        return "ZEUS itself passed rails"
    try:
        bolt.discharge(os.getpid())
        return "discharge against ZEUS did not raise"
    except bolt.BoltDenied:
        pass
    proc = sleeper()
    try:
        if not wait_alive(procsys.ProcTable(), proc.pid):
            return "sleeper never appeared"
        rec = bolt.discharge(proc.pid)
        if not rec["ok"]:
            return f"legit discharge failed: {rec['detail']}"
        proc.wait(timeout=5)
        return True
    finally:
        if proc.poll() is None:
            proc.kill()


def check_aegis_roundtrip(tmp):
    ws = os.path.join(tmp, "ws")
    os.makedirs(os.path.join(ws, "sub"))
    with open(os.path.join(ws, "a.txt"), "w") as fh:
        fh.write("hello")
    with open(os.path.join(ws, "sub", "b.txt"), "w") as fh:
        fh.write("world")
    ag = Aegis(workspace=ws,
               baseline_path=os.path.join(tmp, "base.json"),
               roots=["a.txt", "sub"])
    built = ag.build()
    if built["files"] != 2:
        return f"baseline held {built['files']} files"
    if not ag.verify()["clean"]:
        return "fresh workspace failed verification"
    with open(os.path.join(ws, "a.txt"), "w") as fh:
        fh.write("tampered")
    res = ag.verify()
    if res["modified"]["count"] != 1:
        return "modification missed"
    with open(os.path.join(ws, "sub", "c.txt"), "w") as fh:
        fh.write("new")
    os.remove(os.path.join(ws, "sub", "b.txt"))
    res = ag.verify()
    if res["added"]["count"] != 1 or res["missing"]["count"] != 1 \
            or res["modified"]["count"] != 1:
        return f"drift miscounted: {res}"
    ag2 = Aegis(workspace=ws,
                baseline_path=os.path.join(tmp, "base.json"),
                roots=["a.txt", "sub"])
    if not ag2.load() or len(ag2.baseline) != 2:
        return "baseline roundtrip lost entries"
    return True


def check_quarantine_roundtrip(tmp):
    src = os.path.join(tmp, "suspect.txt")
    qdir = os.path.join(tmp, "q")
    with open(src, "w") as fh:
        fh.write("bad")
    q = bolt.Quarantine(root=qdir)
    rec = q.capture(src, why="verify")
    if os.path.exists(src):
        return "captured file still at origin"
    if not os.path.isfile(rec["held"]):
        return "nothing held in quarantine"
    listing = q.listing()
    if len(listing) != 1 or listing[0]["why"] != "verify":
        return "quarantine listing wrong"
    back = q.restore(rec["id"])
    if not os.path.isfile(back["orig"]):
        return "restore did not put file back"
    with open(back["orig"]) as fh:
        if fh.read() != "bad":
            return "restored content corrupted"
    try:
        q.restore(rec["id"])
        return "double restore accepted"
    except KeyError:
        return True


def check_churn_burst(tmp):
    with sandbox(tmp) as kernel:
        oracle = kernel.oracle
        first = oracle.patrol()          # prime all hots
        if first:
            return "first sample produced findings"
        hot_dir = os.path.join(tmp, "drop")
        os.makedirs(hot_dir)
        oracle.hots.append(oracle_mod.HotDir(hot_dir, 4000))
        oracle.patrol()                  # prime the new hot dir empty
        for i in range(content.CHURN_BURST_THRESHOLD + 5):
            with open(os.path.join(hot_dir, f"f{i}.bin"), "wb") as fh:
                fh.write(b"x" * 64)
        finds = oracle.patrol()
        bursts = [f for f in finds if f["type"] == "churn_burst"]
        if not bursts:
            return "burst not detected"
        b = bursts[0]
        if b["severity"] != "critical" or not b["synthetic"]:
            return f"burst misclassified: {b}"
        if oracle.patrol():              # window cleared after incident
            return "burst re-fired without new mutations"
    return True


def check_breaker_trip_and_revive(tmp):
    with sandbox(tmp) as kernel:
        br = kernel.breakers["oracle"]
        original = kernel.oracle.patrol
        state = {"boom": True}

        def flaky():
            if state["boom"]:
                raise RuntimeError("injected fault")
            return []

        kernel.oracle.patrol = flaky
        try:
            for _ in range(content.SUBSYSTEM_FAIL_LIMIT):
                kernel.tick()
            if not br.tripped:
                return "breaker did not trip at fail limit"
            events = [e for e in kernel.events if e["kind"] == "breaker"]
            if not any("tripped" in e["text"] for e in events):
                return "trip not audited"
            for _ in range(content.SUBSYSTEM_REVIVE_TICKS):
                kernel.tick()
            if br.tripped:
                return "breaker never came up for retry"
            state["boom"] = False
            kernel.tick()
            if br.fails:
                return "healthy patrol still counted as failure"
        finally:
            kernel.oracle.patrol = original
        return True


def check_audit_written_and_rotates(tmp):
    with sandbox(tmp) as kernel:
        saved_max = content.AUDIT_MAX_BYTES
        try:
            content.AUDIT_MAX_BYTES = 600
            for i in range(30):
                kernel.log_event("audit-test", "info", f"entry {i} "
                                 "with some padding text to grow fast")
            rotated = content.AUDIT_PATH + ".1"
            if not os.path.exists(rotated):
                return "audit never rotated"
            size_main = os.path.getsize(content.AUDIT_PATH)
            if size_main > saved_max and size_main > 1200:
                return "rotation left an oversized audit file"
        finally:
            content.AUDIT_MAX_BYTES = saved_max
    return True


def check_sdk_surface_lockstep(tmp):
    with sandbox(tmp) as kernel:
        missing = wire_client(ZeusSDK(kernel))
    if missing:
        return f"sdk surface holes: {missing}"
    return True


def check_wire_roundtrip(tmp):
    with sandbox(tmp) as kernel:
        server = ZeusServer(port=0, auto_patrol=False, kernel=kernel)
        server.start_async()
        try:
            client = ZeusClient(server.host, server.port)
            hello = client.connect()
            if hello.get("error"):
                return f"hello carried error: {hello['error']}"
            if hello["result"].get("hello") != "zeus":
                return "wrong hello payload"
            status = client.status()
            if not status.get("zeus") or status["ticks"] != 0:
                return "status wrong over the wire"
            rep = client.patrol(n=2)
            if rep["tick"] != 2:
                return "patrol did not advance ticks"
            original_samples = client.policy_get().get(
                "RUNAWAY_SAMPLES")
            client.policy_set(key="RUNAWAY_SAMPLES", value=7)
            got = client.policy_get()
            if got.get("RUNAWAY_SAMPLES") != 7:
                return "policy_set not visible via policy_get"
            try:
                client.policy_set(key="LAUNCH_MISSILES", value=True)
                return "unknown policy key accepted"
            except KeyError:
                pass
            try:
                client.bolt_kill(pid=os.getpid())
                return "wire bolt against ZEUS itself succeeded"
            except ValueError as exc:
                if "refusing" not in str(exc):
                    return f"unexpected bolt refusal: {exc}"
            try:
                client.no_such_command()
                return "unknown command accepted"
            except KeyError:
                pass
            client.policy_set(key="RUNAWAY_SAMPLES",
                              value=original_samples)
            client.close()
            return True
        finally:
            server.running = False


def check_watch_manifest_contains_self():
    manifest = [{"name": "selfpy", "kind": "contains",
                 "match": "python"}]
    sent = sentinel_mod.Sentinel(manifest=manifest)
    finds, _snap = sent.patrol()         # primes prev pointer
    if any(f["type"] == "proc_death" for f in finds):
        return "phantom death on first patrol"
    finds, _snap = sent.patrol()
    if any(f["type"] == "proc_death" for f in finds):
        return "running python reported dead while alive"
    return True


CHECKS = [
    ("content integrity", check_content_integrity),
    ("process snapshot sees self", check_proc_snapshot_sees_self),
    ("cpu accounting", check_cpu_accounting),
    ("tcp listener table", check_tcp_listeners),
    ("sentinel: pinned death detection",
     check_sentinel_death_detection),
    ("runaway escalation", check_runaway_escalation),
    ("bolt safety rails", check_bolt_rails),
    ("aegis baseline roundtrip", lambda tmp: check_aegis_roundtrip(tmp)),
    ("quarantine capture/restore", lambda tmp: check_quarantine_roundtrip(tmp)),
    ("oracle churn burst", lambda tmp: check_churn_burst(tmp)),
    ("circuit breaker trip/revive", lambda tmp:
     check_breaker_trip_and_revive(tmp)),
    ("audit write + rotation", lambda tmp:
     check_audit_written_and_rotates(tmp)),
    ("sdk surface lockstep", check_sdk_surface_lockstep),
    ("wire roundtrip (TCP)", lambda tmp: check_wire_roundtrip(tmp)),
    ("watch manifest resolves self", check_watch_manifest_contains_self),
]


def main():
    passed = 0
    failed = []

    def run(name, fn, arg=None):
        nonlocal passed
        try:
            result = fn(arg) if arg is not None else fn()
        except Exception as exc:             # noqa: BLE001 - report all
            result = f"exception: {exc!r}"
        if result is True:
            print(f"[PASS] {name}")
            passed += 1
        else:
            detail = result if isinstance(result, str) else str(result)
            print(f"[FAIL] {name}: {detail}")
            failed.append(name)

    with tempfile.TemporaryDirectory(prefix="zeus_verify_") as tmp:
        for name, fn in CHECKS:
            needs_tmp = fn.__code__.co_argcount > 0
            run(name, fn, tmp if needs_tmp else None)

    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if failed:
        print("failed: " + ", ".join(failed))
        return False
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
