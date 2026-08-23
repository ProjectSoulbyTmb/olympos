import heapq
import itertools


class MIND:
    """Central engine core for the skilling world.

    Owns:
      - the event bus ("tick", "action", "level_up", "quest_complete",
        "session_start", "session_end")
      - a tick-accurate scheduler (schedule / every)
      - strategy-session lifecycle (run_strategy) with result capture

    Attach with MIND(world); the world then emits engine events through
    this kernel. A world without a kernel keeps working as before.
    """

    def __init__(self, world=None):
        self.world = None
        self._handlers = {}
        self._jobs = []
        self._job_seq = itertools.count()
        self._last_result = None
        if world is not None:
            self.attach(world)

    def attach(self, world):
        self.world = world
        world.kernel = self
        self.on("tick", self._pump_jobs)
        return self

    def detach(self):
        if self.world is not None:
            self.off("tick", self._pump_jobs)
            self.world.kernel = None
        self.world = None

    def clear(self):
        self._handlers.clear()
        self._jobs.clear()
        self._last_result = None

    def has_listeners(self, event):
        return bool(self._handlers.get(event))

    def jobs_pending(self):
        return bool(self._jobs)

    def on(self, event, handler=None):
        if handler is None:
            def decorator(fn):
                self._handlers.setdefault(event, []).append(fn)
                return fn
            return decorator
        self._handlers.setdefault(event, []).append(handler)
        return handler

    def off(self, event, handler):
        try:
            self._handlers[event].remove(handler)
        except (KeyError, ValueError):
            pass

    def emit(self, event, **data):
        errors = []
        for fn in list(self._handlers.get(event, ())):
            try:
                fn(**data)
            except Exception as e:
                errors.append("%s: %s: %s" % (
                    getattr(fn, "__name__", fn), type(e).__name__, e))
        if errors and event != "handler_error":
            self.emit("handler_error", source_event=event, errors=errors)

    def schedule(self, delay_ticks, fn):
        if self.world is None:
            raise RuntimeError("kernel not attached to a world")
        due = self.world.tick + max(1, int(delay_ticks))
        job = (due, next(self._job_seq), fn)
        heapq.heappush(self._jobs, job)
        return job

    def cancel(self, job):
        try:
            self._jobs.remove(job)
        except ValueError:
            pass

    def every(self, interval_ticks, fn):
        def recurring(**_):
            try:
                fn()
            finally:
                if self.world is not None:
                    self.schedule(interval_ticks, recurring)
        self.schedule(interval_ticks, recurring)
        return recurring

    def _pump_jobs(self, **_):
        w = self.world
        while self._jobs and self._jobs[0][0] <= w.tick:
            _, _, fn = heapq.heappop(self._jobs)
            fn()

    def run_strategy(self, code, task="total_xp", forgiving=True):
        from agent.runner import run_snippet
        from game.sdk import GameSDK

        if self.world is None:
            raise RuntimeError("kernel not attached to a world")
        self._last_result = None
        self.emit("session_start")
        ok, output, err = run_snippet(code, GameSDK(self.world),
                                      forgiving=forgiving)
        result = {"ok": ok, "output": output, "error": err,
                  "details": self.world.score_task(task)}
        self._last_result = result
        self.emit("session_end", **result)
        return result

    @property
    def last_result(self):
        return self._last_result

    def knowledge(self):
        from game.knowledge import collect
        return collect()

    def docs(self):
        from game.knowledge import render_markdown
        return render_markdown()

    def supervise(self, **kw):
        """Start the 24/7 server supervisor (health probes, auto-restart,
        content-version tracking, knowledge refresh). Returns the running
        MindSupervisor."""
        from server.supervisor import MindSupervisor
        sup = MindSupervisor(**kw)
        sup.start_async()
        return sup

Kernel = MIND
MIND_VERSION = '1.0'
