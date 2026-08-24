"""HYPNOS kernel - five silent engines over one claim queue.

Tick order, every phase behind its own circuit breaker:

  1. SWEEP   promote data/dropin/*.task.json files onto the bus
  2. MAIL    drain task letters from the Ratatosk inbox
  3. QUEUE   execute due claims - resumed crashes plus retries whose
             backoff elapsed; a claim is written BEFORE work starts, so
             a killed process leaves its unfinished work behind and the
             next tick picks it up automatically
  4. MAINT   purge seen folders, prune archives, rotate the audit
  5. BUILD   feed the live system: run the Yggdrasil verify gates and
             publish the outcome on topic 'hypnos' + data/build.json

Nothing prints. Everything lands in the audit trail.
"""

import contextlib
import glob
import json
import os
import shutil
import tempfile
import time
import uuid
from collections import deque

from hypnos import actions, content

try:                                # the post office is optional glue
    from ratatosk.bus import Post
except ImportError:                 # pragma: no cover
    Post = None


# ---------------------------------------------------------------- helpers

def _now():
    return time.time()


def _iso(epoch=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.localtime(epoch or _now()))


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, separators=(",", ":"), default=str)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _slug(name):
    out = "".join(c if (c.isalnum() or c in "-_.") else "_"
                  for c in str(name))[:80] or "task"
    return out


def _load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Breaker:
    """Circuit breaker around one engine phase (zeus pattern)."""

    def __init__(self, name, kernel):
        self.name = name
        self.kernel = kernel
        self.fails = 0
        self.tripped = False
        self.cool_ticks_left = 0

    def run(self, fn, *args):
        if self.tripped:
            self.cool_ticks_left -= 1
            if self.cool_ticks_left <= 0:
                self.tripped = False
                self.fails = 0
                self.kernel.audit("breaker", phase=self.name,
                                  msg="revived for retry")
            return None
        try:
            return fn(*args)
        except Exception as exc:               # noqa: BLE001 - breaker job
            self.fails += 1
            if self.fails >= content.SUBSYSTEM_FAIL_LIMIT:
                self.tripped = True
                self.cool_ticks_left = content.SUBSYSTEM_REVIVE_TICKS
                self.kernel.audit("breaker", phase=self.name,
                                  msg="tripped: %r" % (exc,))
            else:
                self.kernel.audit("engine-error", phase=self.name,
                                  msg="%d/%d fails: %r"
                                  % (self.fails,
                                     content.SUBSYSTEM_FAIL_LIMIT, exc))
            return None


_PATH_FIELDS = ("WORKSPACE", "DATA_DIR", "AUDIT_PATH", "STATE_PATH",
                "QUEUE_DIR", "DROPIN_DIR", "DROPIN_DONE",
                "DROPIN_FAILED", "ALLOWED_ROOTS", "BUILD_ENABLED")


@contextlib.contextmanager
def sandbox(workspace, data_dir=None):
    """Point HYPNOS at a scratch root; restores everything on exit.
    The Ratatosk post root is redirected too, so verify runs never
    touch the live network."""
    root_env = os.environ.get("RATATOSK_ROOT")
    saved = {f: getattr(content, f) for f in _PATH_FIELDS}
    data = data_dir or os.path.join(workspace, "hypnos-sandbox")
    try:
        content.WORKSPACE = workspace
        content.DATA_DIR = data
        content.AUDIT_PATH = os.path.join(data, "audit.jsonl")
        content.STATE_PATH = os.path.join(data, "state.json")
        content.QUEUE_DIR = os.path.join(data, "queue")
        content.DROPIN_DIR = os.path.join(data, "dropin")
        content.DROPIN_DONE = os.path.join(content.DROPIN_DIR, "done")
        content.DROPIN_FAILED = os.path.join(content.DROPIN_DIR, "failed")
        content.ALLOWED_ROOTS = [workspace]
        content.BUILD_ENABLED = False    # gates opt in per-test explicitly
        os.environ["RATATOSK_ROOT"] = os.path.join(data, "post")
        os.makedirs(workspace, exist_ok=True)
        os.makedirs(data, exist_ok=True)
        yield Kernel()
    finally:
        for f, val in saved.items():
            setattr(content, f, val)
        if root_env is None:
            os.environ.pop("RATATOSK_ROOT", None)
        else:
            os.environ["RATATOSK_ROOT"] = root_env


# ------------------------------------------------------------------ kernel

class Kernel:
    def __init__(self, post=None):
        if Post is None:
            raise RuntimeError("ratatosk bus unavailable")
        self.post = post or Post()
        self.breakers = {name: Breaker(name, self)
                         for name in ("sweep", "mail", "queue",
                                      "maint", "build")}
        self.events = deque(maxlen=content.EVENTS_MAX)
        self.tick_count = 0
        self.tasks_ok = 0
        self.tasks_failed = 0
        self.retried = 0
        self.resumed = 0
        self.started_at = _now()
        self.last_task = None
        self.last_build = None
        self._last_build_epoch = 0.0
        self._session_claims = set()
        os.makedirs(content.DATA_DIR, exist_ok=True)
        os.makedirs(content.QUEUE_DIR, exist_ok=True)
        os.makedirs(content.DROPIN_DONE, exist_ok=True)
        os.makedirs(content.DROPIN_FAILED, exist_ok=True)
        self._load_state()

    # ------------------------------ audit / state ------------------------------

    def audit(self, kind, **fields):
        entry = {"t": round(_now(), 3), "ts": _iso(),
                 "tick": self.tick_count, "kind": kind}
        entry.update(fields)
        self.events.append(entry)
        try:
            os.makedirs(os.path.dirname(content.AUDIT_PATH), exist_ok=True)
            with open(content.AUDIT_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":"),
                                    default=str) + "\n")
        except OSError:
            pass
        return entry

    def _rotate_audit(self):
        try:
            if os.path.getsize(content.AUDIT_PATH) <= \
                    content.AUDIT_MAX_BYTES:
                return False
        except OSError:
            return False
        for i in range(content.AUDIT_ROTATIONS - 1, 0, -1):
            src = "%s.%d.jsonl" % (content.AUDIT_PATH, i)
            if os.path.exists(src):
                try:
                    os.replace(src, "%s.%d.jsonl"
                               % (content.AUDIT_PATH, i + 1))
                except OSError:
                    pass
        try:
            os.replace(content.AUDIT_PATH,
                       content.AUDIT_PATH + ".1.jsonl")
        except OSError:
            pass
        try:
            # keep the live path in existence: readers must never race
            # a missing audit file between rotate and next append
            with open(content.AUDIT_PATH, "a", encoding="utf-8"):
                pass
        except OSError:
            pass
        return True

    def _state_snapshot(self):
        return {"v": content.VERSION, "ticks": self.tick_count,
                "tasks_ok": self.tasks_ok, "tasks_failed": self.tasks_failed,
                "retries": self.retried, "resumed": self.resumed,
                "last_task": self.last_task,
                "last_build": self.last_build,
                "started_at": round(self.started_at, 3),
                "saved_at": _iso()}

    def _load_state(self):
        try:
            st = _load_json(content.STATE_PATH)
            self.tick_count = int(st.get("ticks", 0))
            self.tasks_ok = int(st.get("tasks_ok", 0))
            self.tasks_failed = int(st.get("tasks_failed", 0))
            self.retried = int(st.get("retries", 0))
            self.resumed = int(st.get("resumed", 0))
            self.last_task = st.get("last_task")
            self.last_build = st.get("last_build")
            self._last_build_epoch = float(st.get("last_build_epoch", 0))
        except (OSError, ValueError, TypeError):
            pass

    def save_state(self):
        snap = self._state_snapshot()
        snap["last_build_epoch"] = round(self._last_build_epoch, 3)
        try:
            _atomic_json(content.STATE_PATH, snap)
        except OSError:
            pass
        return snap

    # ------------------------------ queue claims -------------------------------

    def _claim_path(self, job_id):
        return os.path.join(content.QUEUE_DIR, _slug(job_id) + ".json")

    def enqueue(self, job):
        """Write the claim before anything executes; duplicates skip."""
        path = self._claim_path(job["id"])
        if os.path.exists(path):
            return None
        job.setdefault("attempts", 0)
        job.setdefault("max_attempts", 1)
        job.setdefault("next_epoch", _now())
        job.setdefault("enqueued_epoch", _now())
        job.setdefault("label", "")
        job.setdefault("on_error", "stop")
        job.setdefault("src", "mail")
        _atomic_json(path, job)
        self.audit("claim", id=job["id"], src=job["src"],
                   n_actions=len(job.get("actions", [])),
                   label=job.get("label", ""))
        self._session_claims.add(job["id"])
        return path

    def _job_from_letter(self, letter):
        payload = letter.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        acts = payload.get("actions")
        if not isinstance(acts, list) or \
                len(acts) > content.MAX_ACTIONS_PER_TASK:
            return None
        task_name = _slug(payload.get("task")
                          or letter.get("id") or uuid.uuid4().hex[:8])
        retry = bool(payload.get("retry"))
        return {
            "v": content.VERSION,
            # named tasks dedupe by claim file; anonymous ones stay unique
            "id": task_name if payload.get("task")
            else "%s-%s" % (task_name, letter.get("id")),
            "task": task_name,
            "label": str(payload.get("label", ""))[:200],
            "actions": acts,
            "on_error": "continue"
            if payload.get("on_error") == "continue" else "stop",
            "reply_to": letter.get("from"),
            "src": "mail",
            "attempts": 0,
            "max_attempts": content.RETRY_MAX_ATTEMPTS if retry else 1,
            "next_epoch": _now(),
            "enqueued_epoch": _now(),
        }

    def _job_from_dropin(self, path, fname):
        try:
            payload = _load_json(path)
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
        except (OSError, ValueError):
            try:
                shutil.move(path, os.path.join(content.DROPIN_FAILED,
                                               "corrupt-" + fname))
            except OSError:
                pass
            self.audit("drop-reject", file=fname)
            return None
        acts = payload.get("actions")
        if not isinstance(acts, list) or \
                len(acts) > content.MAX_ACTIONS_PER_TASK:
            try:
                shutil.move(path, os.path.join(content.DROPIN_FAILED,
                                               "bad-" + fname))
            except OSError:
                pass
            self.audit("drop-reject", file=fname, reason="bad actions")
            return None
        task_name = _slug(payload.get("task") or fname[:-len(".task.json")])
        return {
            "v": content.VERSION,
            "id": task_name if payload.get("task")
            else "%s-drop-%s" % (task_name, uuid.uuid4().hex[:8]),
            "task": task_name,
            "label": str(payload.get("label", ""))[:200],
            "actions": acts,
            "on_error": "continue"
            if payload.get("on_error") == "continue" else "stop",
            "reply_to": payload.get("reply_to"),
            "src": "dropin:" + fname,
            "attempts": 0,
            "max_attempts": content.RETRY_MAX_ATTEMPTS
            if payload.get("retry") else 1,
            "next_epoch": _now(),
            "enqueued_epoch": _now(),
        }

    def pending_claims(self):
        out = []
        for p in glob.glob(os.path.join(content.QUEUE_DIR, "*.json")):
            try:
                job = _load_json(p)
                if isinstance(job, dict) and "id" in job:
                    job["_path"] = p
                    out.append(job)
            except (OSError, ValueError):
                continue
        out.sort(key=lambda j: j.get("enqueued_epoch", 0))
        return out

    # ------------------------------ engines ------------------------------

    def _sweep(self):
        """Engine 1: promote drop-in task files into claims.
        The original file is consumed immediately - the claim written
        under data/queue is now the durable record of the work."""
        promoted = 0
        try:
            names = sorted(f for f in os.listdir(content.DROPIN_DIR)
                           if f.endswith(".task.json"))
        except OSError:
            return 0
        for fname in names:
            src = os.path.join(content.DROPIN_DIR, fname)
            job = self._job_from_dropin(src, fname)
            if job is None:
                continue
            if self.enqueue(job):
                try:
                    # archive the consumed spec next to its future
                    # result: data/dropin/done holds the full story
                    os.replace(src, os.path.join(content.DROPIN_DONE,
                                                 fname))
                except OSError:
                    pass
                promoted += 1
            else:
                # a task with this name is already pending - park it
                try:
                    os.replace(src, os.path.join(content.DROPIN_FAILED,
                                                 "dupe-" + fname))
                except OSError:
                    pass
                self.audit("duplicate-skipped", src="dropin", file=fname)
        return promoted

    def _mail(self):
        """Engine 2: drain task letters into claims."""
        letters = self.post.read(content.ORGAN,
                                 limit=content.TICK_LETTERS_MAX)
        claimed = 0
        for letter in letters:
            if letter.get("kind") != "task":
                continue
            job = self._job_from_letter(letter)
            if job is None:
                self.audit("letter-reject", letter=letter.get("id"))
                self._reply(letter.get("from"), letter.get("id"),
                            ok=False, error="invalid task letter",
                            n_actions=0)
                continue
            if self.enqueue(job):
                claimed += 1
            else:
                self.audit("duplicate-skipped", letter=letter.get("id"))
        return len(letters), claimed

    def _run_queue(self):
        """Engine 3: execute every due claim (crash resumes + retries)."""
        now = _now()
        ran = resumed = retried = done = 0
        for job in self.pending_claims():
            if ran >= content.TICK_LETTERS_MAX:
                break
            if float(job.get("next_epoch", 0)) > now:
                continue
            prev_attempts = int(job.get("attempts", 0))
            known = job["id"] in self._session_claims
            outcome = self._execute_claim(job)
            ran += 1
            if outcome == "retry":
                retried += 1
                continue
            done += 1
            if prev_attempts > 0 and not known:
                resumed += 1          # finished work left by a dead run
        return ran, resumed, retried

    def _execute_claim(self, job):
        job["attempts"] = int(job.get("attempts", 0)) + 1
        try:
            _atomic_json(job["_path"], job)
        except (OSError, KeyError):
            pass
        attempt = job["attempts"]
        self.last_task = job["id"]
        self.audit("task-start", id=job["id"], src=job["src"],
                   attempt=attempt, label=job.get("label", ""),
                   n_actions=len(job.get("actions", [])))

        results, stopped = [], False
        for i, spec in enumerate(job.get("actions", [])):
            res = actions.execute(spec, post=self.post)
            results.append(res)
            brief = {k: res[k] for k in ("do", "ok") }
            if not res.get("ok"):
                brief["error"] = res.get("error") or \
                    res.get("stderr", "")[:200]
            self.audit("action", id=job["id"], i=i, **brief)
            if not res.get("ok") and job.get("on_error") != "continue":
                stopped = True
                break

        ok = all(r.get("ok") for r in results)

        if not ok and attempt < int(job.get("max_attempts", 1)):
            delay = min(content.RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1)),
                        content.RETRY_BACKOFF_MAX_S)
            job["next_epoch"] = _now() + delay
            try:
                _atomic_json(job["_path"], job)
            except (OSError, KeyError):
                pass
            self.audit("retry", id=job["id"], attempt=attempt,
                       next_in_s=round(delay, 1))
            return "retry"

        try:
            os.unlink(job["_path"])
        except (OSError, KeyError):
            pass
        if ok:
            self.tasks_ok += 1
        else:
            self.tasks_failed += 1
        self.audit("task-done", id=job["id"], ok=ok,
                   attempt=attempt, actions_ran=len(results),
                   stopped_early=stopped)
        self._finalize(job, ok, results, attempt, stopped)
        return "done"

    def _finalize(self, job, ok, results, attempt, stopped):
        summary = {"task": job["id"], "label": job.get("label", ""),
                   "ok": ok, "attempts": attempt, "src": job["src"],
                   "actions_ran": len(results), "stopped_early": stopped}
        if job.get("reply_to"):
            self._reply(job["reply_to"], job["id"], ok=ok,
                        error=None if ok else "task failed "
                        "(see audit)", n_actions=len(results),
                        attempt=attempt, label=job.get("label", ""))
        try:
            self.post.broadcast(
                content.TOPIC, "task-done" if ok else "task-failed",
                summary, frm=content.ORGAN)
        except OSError:
            pass
        if str(job.get("src", "")).startswith("dropin:"):
            self._archive_dropin(job, summary)

    def _reply(self, to, task_ref, **payload):
        if not to:
            return None
        body = {"v": content.VERSION, "task": task_ref}
        body.update(payload)
        try:
            return self.post.send(to, "task-result", body,
                                  frm=content.ORGAN)
        except OSError:
            return None

    def _archive_dropin(self, job, summary):
        fname = str(job.get("src", "")).split(":", 1)[-1]
        side = content.DROPIN_DONE if summary["ok"] \
            else content.DROPIN_FAILED
        try:
            os.makedirs(side, exist_ok=True)
            _atomic_json(os.path.join(
                side, _slug(fname)[:64] + ".result.json"), summary)
        except OSError:
            pass

    def _maintain(self):
        """Engine 4: hygiene - purge seen, prune archives, rotate."""
        purged = 0
        try:
            purged = self.post.purge()
        except Exception:                     # noqa: BLE001 - hygiene only
            pass
        for side, keep in ((content.DROPIN_DONE, content.DROPIN_KEEP),
                           (content.DROPIN_FAILED, content.DROPIN_KEEP)):
            try:
                olds = sorted(f for f in os.listdir(side)
                              if f.endswith(".json"))
            except OSError:
                continue
            for fname in olds[:-keep] if keep else olds:
                try:
                    os.unlink(os.path.join(side, fname))
                except OSError:
                    pass
        rotated = self._rotate_audit()
        self.audit("maintain", purged=purged, audit_rotated=rotated)
        return purged

    def _build(self):
        """Engine 5: feed the live system - prove the organism builds."""
        if not content.BUILD_ENABLED or not content.BUILD_GATES:
            return None
        if _now() - self._last_build_epoch < content.BUILD_MIN_INTERVAL_S:
            return None
        gates = []
        all_ok = True
        for gate in content.BUILD_GATES:
            spec = {"do": "run", "argv": gate["argv"],
                    "timeout_s": gate.get("timeout_s",
                                          content.MAX_RUN_TIMEOUT_S)}
            started = _now()
            res = actions.execute(spec, post=self.post)
            gates.append({"name": gate.get("name",
                                           _slug(gate["argv"][-1])),
                          "ok": bool(res.get("ok")),
                          "exit_code": res.get("exit_code"),
                          "duration_s": res.get("duration_s"),
                          "tail": (res.get("stdout", "")
                                   + res.get("stderr", ""))[-1500:]})
            all_ok = all_ok and bool(res.get("ok"))
        report = {"v": content.VERSION, "epoch": round(_now(), 3),
                  "ts": _iso(), "ok": all_ok, "gates": gates}
        try:
            _atomic_json(os.path.join(content.DATA_DIR, "build.json"),
                         report)
        except OSError:
            pass
        try:
            self.post.broadcast(content.TOPIC,
                                "build" if all_ok else "build-failed",
                                {"ok": all_ok,
                                 "gates": [{"name": g["name"], "ok": g["ok"]}
                                           for g in gates]},
                                frm=content.ORGAN)
        except OSError:
            pass
        self._last_build_epoch = _now()
        self.last_build = {"ok": all_ok, "ts": report["ts"]}
        self.audit("build", ok=all_ok,
                   gates=[g["name"] for g in gates])
        return report

    # ------------------------------ the tick ------------------------------

    def tick(self):
        self.tick_count += 1
        s = {"dropins": 0, "letters": 0, "claimed": 0, "ran": 0,
             "resumed": 0, "retries": 0, "built": False}

        swept = self.breakers["sweep"].run(self._sweep)
        if swept:
            s["dropins"] = swept

        mailed = self.breakers["mail"].run(self._mail)
        if mailed:
            s["letters"], s["claimed"] = mailed

        q = self.breakers["queue"].run(self._run_queue)
        if q:
            s["ran"], s["resumed"], s["retries"] = q
            self.resumed += s["resumed"]
            self.retried += s["retries"]

        if self.tick_count % content.PURGE_EVERY_TICKS == 0:
            self.breakers["maint"].run(self._maintain)

        worked = s["claimed"] or s["ran"] or s["dropins"]
        if worked or content.BUILD_ON_IDLE:
            report = self.breakers["build"].run(self._build)
            s["built"] = report is not None

        self.save_state()
        self.post.beat(content.ORGAN,
                       note="t%d ok:%d fail:%d q:%d"
                       % (self.tick_count, self.tasks_ok,
                          self.tasks_failed, len(self.pending_claims())))
        self.audit("tick", **s)
        return s
