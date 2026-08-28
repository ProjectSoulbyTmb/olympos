"""Health-aware backend routing for PTAH.

The router deliberately does not contact a backend while it is constructed.
Calls are made only when ``complete``/``stream`` is consumed, or when an
operator explicitly starts the health monitor.  A small circuit breaker keeps
an unhealthy backend from receiving every request while preserving the
existing provider-neutral LLM and tool-call surfaces.
"""

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field

from ptah.fallback import TRANSIENT_KINDS
from ptah.request_context import get_request_id


def deployment_readiness(host=None, token=None, tls_terminated=False,
                         require_tls=False, allow_insecure=False):
    """Validate server exposure without probing or constructing TLS."""
    from ptah.deployment import validate_deployment
    return validate_deployment(host=host, token=token,
                               tls_terminated=tls_terminated,
                               require_tls=require_tls,
                               allow_insecure=allow_insecure)


@dataclass
class BackendStats:
    """Serializable counters for one configured backend."""

    name: str
    provider: str = ""
    status: str = "unknown"
    calls: int = 0
    successes: int = 0
    failures: int = 0
    transient_failures: int = 0
    total_latency_s: float = 0.0
    avg_latency_s: float = 0.0
    last_latency_s: float = 0.0
    last_error: str = ""
    last_error_kind: str = ""
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    consecutive_failures: int = 0
    in_flight: int = 0
    available: bool = True
    last_request_id: str = ""
    _latencies: list = field(default_factory=list, repr=False)

    def public(self):
        value = asdict(self)
        value.pop("_latencies", None)
        value["success_rate"] = (self.successes / self.calls
                                 if self.calls else 0.0)
        return value


class BackendRouter:
    """Route complete and streaming calls across health-aware backends.

    ``backends`` accepts ``(name, brain)`` pairs, mappings with ``name`` and
    ``brain`` keys, or brain objects (named from their provider).  The first
    backend is preferred, but open circuits are skipped.  Only classified
    transient failures advance to another backend; authentication, malformed
    request, and protocol failures are returned immediately.
    """

    def __init__(self, backends, failure_threshold=2, cooldown_s=30.0,
                 health_checks=None, clock=None, metrics_path=""):
        values = list(backends or ())
        if not values:
            raise ValueError("BackendRouter needs at least one backend")
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if cooldown_s < 0:
            raise ValueError("cooldown_s must be non-negative")
        self.failure_threshold = int(failure_threshold)
        self.cooldown_s = float(cooldown_s)
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._persist_lock = threading.RLock()
        self._cursor = 0
        self._health_checks = health_checks or {}
        self._stop = threading.Event()
        self._monitor = None
        self.last_served = None
        self.last_error = None
        self.metrics_path = os.path.abspath(metrics_path) if metrics_path else ""
        self._persistence_error = ""
        self._items = []
        names = set()
        for index, value in enumerate(values):
            name, brain = self._unpack(value, index)
            if brain is None:
                raise ValueError("backend brain cannot be None")
            if name in names:
                raise ValueError(f"duplicate backend name: {name}")
            names.add(name)
            self._items.append({
                "name": name,
                "brain": brain,
                "open_until": 0.0,
                "half_open": False,
                "stats": BackendStats(
                    name=name,
                    provider=getattr(brain, "provider", "") or ""),
            })
        if self.metrics_path:
            self.load_metrics()

    @staticmethod
    def _unpack(value, index):
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return str(value[0]), value[1]
        if isinstance(value, dict):
            brain = value.get("brain", value.get("backend"))
            name = value.get("name") or getattr(brain, "provider", None)
            return str(name or f"backend-{index + 1}"), brain
        return (getattr(value, "provider", None) or f"backend-{index + 1}",
                value)

    @property
    def provider(self):
        return getattr(self._items[0]["brain"], "provider", "backend")

    @property
    def config(self):
        return getattr(self._items[0]["brain"], "config", None)

    @property
    def backends(self):
        """Return the configured brain objects in preference order."""
        return tuple(item["brain"] for item in self._items)

    @property
    def backend_names(self):
        return tuple(item["name"] for item in self._items)

    @property
    def is_ready(self):
        return self.readiness()[0]

    def _eligible(self, now):
        eligible = []
        for item in self._items:
            if item["open_until"] <= now:
                if item["open_until"] and not item["half_open"]:
                    item["half_open"] = True
                # Permit one trial after cooldown.  Other callers wait for
                # the result rather than stampeding the recovering backend.
                if not item["half_open"] or item["stats"].in_flight == 0:
                    eligible.append(item)
        return eligible

    def _choose(self):
        with self._lock:
            now = self._clock()
            eligible = self._eligible(now)
            if not eligible:
                return None
            # Round-robin among currently eligible entries.  The cursor is
            # advanced under the lock; provider work never happens under it.
            count = len(self._items)
            for offset in range(count):
                index = (self._cursor + offset) % count
                item = self._items[index]
                if item in eligible:
                    self._cursor = (index + 1) % count
                    self._start_item(item)
                    return item
            self._start_item(eligible[0])
            return eligible[0]

    def _start_item(self, item):
        with self._lock:
            item["stats"].in_flight += 1
            request_id = get_request_id()
            if request_id:
                item["stats"].last_request_id = request_id

    @staticmethod
    def _failure_kind(exc):
        kind = getattr(exc, "kind", None)
        if kind:
            return kind
        return "network"

    @classmethod
    def _is_transient(cls, exc):
        return cls._failure_kind(exc) in TRANSIENT_KINDS or \
            not hasattr(exc, "kind")

    def _finished(self, item, started, error=None):
        elapsed = max(0.0, self._clock() - started)
        snapshot = None
        with self._lock:
            stats = item["stats"]
            stats.in_flight = max(0, stats.in_flight - 1)
            stats.calls += 1
            stats.total_latency_s += elapsed
            stats.last_latency_s = round(elapsed, 6)
            stats._latencies.append(elapsed)
            if len(stats._latencies) > 100:
                stats._latencies.pop(0)
            stats.avg_latency_s = round(
                stats.total_latency_s / stats.calls, 6)
            if error is None:
                stats.successes += 1
                stats.consecutive_failures = 0
                stats.status = "healthy"
                stats.available = True
                stats.last_success_at = time.time()
                item["open_until"] = 0.0
                item["half_open"] = False
                self.last_served = item["name"]
            else:
                stats.failures += 1
                stats.last_failure_at = time.time()
                stats.last_error = str(error)[:300]
                stats.last_error_kind = self._failure_kind(error)
                if self._is_transient(error):
                    stats.transient_failures += 1
                    stats.consecutive_failures += 1
                    if stats.consecutive_failures >= self.failure_threshold:
                        item["open_until"] = self._clock() + self.cooldown_s
                        item["half_open"] = False
                        stats.status = "unhealthy"
                        stats.available = False
                    else:
                        stats.status = "degraded"
                else:
                    # A bad request/auth failure does not mean the server is
                    # unavailable and must not trip the circuit.
                    stats.status = "degraded"
                self.last_error = error
            snapshot = self._metrics_locked()
        self._persist_snapshot(snapshot)

    def _invoke_complete(self, brain, system, messages, tools,
                         tool_choice):
        if tools is None and tool_choice is None:
            return brain.complete(system, messages)
        return brain.complete(system, messages, tools=tools,
                              tool_choice=tool_choice)

    def complete(self, system, messages, tools=None, tool_choice=None):
        """Complete a request, failing over only before a reply is returned."""
        attempted = set()
        last_error = None
        for _ in range(len(self._items)):
            item = self._choose()
            if item is None or item["name"] in attempted:
                break
            attempted.add(item["name"])
            started = self._clock()
            try:
                reply = self._invoke_complete(
                    item["brain"], system, messages, tools, tool_choice)
            except Exception as exc:  # noqa: BLE001 - preserve provider errors
                self._finished(item, started, exc)
                last_error = exc
                if not self._is_transient(exc):
                    raise
                continue
            self._finished(item, started)
            return reply
        if last_error is not None:
            raise last_error
        raise RuntimeError("no backend is currently available")

    def _invoke_stream(self, brain, system, messages, tools, tool_choice):
        stream = getattr(brain, "stream", None)
        if stream is None:
            yield self._invoke_complete(
                brain, system, messages, tools, tool_choice)
            return
        if tools is None and tool_choice is None:
            yield from stream(system, messages)
        else:
            yield from stream(system, messages, tools=tools,
                              tool_choice=tool_choice)

    def stream(self, system, messages, tools=None, tool_choice=None):
        """Yield provider events; fail over only if no event was emitted."""
        attempted = set()
        last_error = None
        for _ in range(len(self._items)):
            item = self._choose()
            if item is None or item["name"] in attempted:
                break
            attempted.add(item["name"])
            started = self._clock()
            emitted = False
            settled = False
            try:
                for reply in self._invoke_stream(
                        item["brain"], system, messages, tools, tool_choice):
                    emitted = True
                    with self._lock:
                        self.last_served = item["name"]
                    yield reply
            except Exception as exc:  # noqa: BLE001
                self._finished(item, started, exc)
                settled = True
                last_error = exc
                if emitted or not self._is_transient(exc):
                    raise
                continue
            else:
                self._finished(item, started)
                settled = True
            finally:
                if not settled:
                    self._finished(item, started,
                                   RuntimeError("stream cancelled"))
            if settled:
                return
        if last_error is not None:
            raise last_error
        raise RuntimeError("no backend is currently available")

    def _metrics_locked(self):
        rows = [item["stats"].public() for item in self._items]
        now = self._clock()
        ready = any(item["stats"].available or
                    item["open_until"] <= now
                    for item in self._items)
        return {
            "ready": ready,
            "backends": rows,
            "total_calls": sum(row["calls"] for row in rows),
            "total_successes": sum(row["successes"] for row in rows),
            "total_failures": sum(row["failures"] for row in rows),
            "persistence_error": self._persistence_error,
        }

    def metrics(self):
        """Return a lock-consistent, JSON-serializable health snapshot."""
        with self._lock:
            return self._metrics_locked()

    def readiness(self):
        """Return ``(ready, snapshot)`` without performing network I/O."""
        snapshot = self.metrics()
        return snapshot["ready"], snapshot

    backend_metrics = metrics
    health_snapshot = metrics

    def _persist_payload(self, snapshot):
        return {
            "schema": "ptah-backend-metrics-v1",
            "saved_at": time.time(),
            "metrics": snapshot,
        }

    def _persist_snapshot(self, snapshot, strict=False):
        path = self.metrics_path
        if not path:
            with self._lock:
                self._persistence_error = ""
            return True
        payload = self._persist_payload(snapshot)
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"),
            sort_keys=True).encode("utf-8")
        directory = os.path.dirname(path) or "."
        temp = (f"{path}.tmp.{os.getpid()}.{threading.get_ident()}."
                f"{int(time.time() * 1000)}")
        try:
            os.makedirs(directory, exist_ok=True)
            with self._persist_lock:
                with open(temp, "wb") as fh:
                    fh.write(encoded)
                os.replace(temp, path)
        except OSError as exc:
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except OSError:
                pass
            with self._lock:
                self._persistence_error = f"{type(exc).__name__}: {exc}"[:300]
            if strict:
                raise
            return False
        with self._lock:
            self._persistence_error = ""
        return True

    def save_metrics(self, path=None):
        target = os.path.abspath(path) if path else self.metrics_path
        if not target:
            raise ValueError("metrics path is not configured")
        with self._lock:
            snapshot = self._metrics_locked()
        previous = self.metrics_path
        try:
            self.metrics_path = target
            self._persist_snapshot(snapshot, strict=True)
        finally:
            self.metrics_path = previous
        return target

    def load_metrics(self, path=None):
        target = os.path.abspath(path) if path else self.metrics_path
        if not target or not os.path.isfile(target):
            return False
        try:
            with open(target, "rb") as fh:
                payload = json.loads(fh.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeError):
            return False
        metrics = payload.get("metrics") if isinstance(payload, dict) else None
        if not isinstance(metrics, dict):
            return False
        rows = metrics.get("backends")
        if not isinstance(rows, list):
            return False
        merged = 0
        with self._lock:
            by_name = {item["name"]: item for item in self._items}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = by_name.get(str(row.get("name", "")))
                if not item:
                    continue
                stats = item["stats"]
                for key in ("calls", "successes", "failures",
                            "transient_failures", "consecutive_failures"):
                    value = row.get(key)
                    if isinstance(value, int):
                        setattr(stats, key, max(0, value))
                for key in ("total_latency_s", "avg_latency_s",
                            "last_latency_s", "last_success_at",
                            "last_failure_at"):
                    value = row.get(key)
                    if isinstance(value, (int, float)):
                        setattr(stats, key, float(value))
                for key in ("status", "last_error", "last_error_kind",
                            "provider", "last_request_id"):
                    value = row.get(key)
                    if isinstance(value, str):
                        setattr(stats, key, value[:300] if key == "last_error"
                                else value)
                value = row.get("available")
                if isinstance(value, bool):
                    stats.available = value
                stats.in_flight = 0
                stats._latencies = []
                merged += 1
        return merged > 0

    def configure_metrics_path(self, metrics_path, load=True):
        self.metrics_path = os.path.abspath(metrics_path) if metrics_path else ""
        with self._lock:
            self._persistence_error = ""
        if load and self.metrics_path:
            return self.load_metrics()
        return False

    export_metrics = save_metrics
    import_metrics = load_metrics

    def check_backend(self, name=None, timeout_s=5.0):
        """Explicitly probe one backend, or all backends, using llm_probe.

        This method is intentionally opt-in.  Constructing the router and
        starting a server never calls it.
        """
        selected = self._items
        if name is not None:
            selected = [item for item in self._items if item["name"] == name]
            if not selected:
                raise KeyError(name)
        results = {}
        from ptah import llm_probe
        for item in selected:
            self._start_item(item)
            started = self._clock()
            try:
                checker = self._health_checks.get(item["name"])
                if checker is not None:
                    result = checker(item["brain"])
                else:
                    cfg = getattr(item["brain"], "config", None)
                    if cfg is None:
                        raise llm_probe.LLMProbeError(
                            "config", "backend has no probe configuration")
                    result = llm_probe.probe(
                        cfg.base_url, model=cfg.model,
                        provider=cfg.provider, api_key=cfg.api_key,
                        timeout_s=timeout_s)
            except Exception as exc:  # noqa: BLE001 - health must continue
                self._finished(item, started, exc)
                results[item["name"]] = {
                    "ok": False, "error": str(exc)[:300]}
            else:
                self._finished(item, started)
                results[item["name"]] = {
                    "ok": True,
                    "result": asdict(result) if hasattr(
                        result, "__dataclass_fields__") else result}
        return results

    def benchmark(self, runs=1, timeout_s=5.0):
        """Run the opt-in compatibility benchmark for every configured item."""
        from ptah import llm_probe
        targets = []
        for item in self._items:
            cfg = getattr(item["brain"], "config", None)
            if cfg is None:
                targets.append({
                    "name": item["name"],
                    "provider": getattr(item["brain"], "provider", ""),
                })
            else:
                targets.append({
                    "name": item["name"],
                    "provider": cfg.provider,
                    "model": cfg.model,
                    "base_url": cfg.base_url,
                    "api_key": cfg.api_key,
                })
        return llm_probe.benchmark_backends(
            targets, runs=runs, timeout_s=timeout_s)

    compatibility_report = benchmark

    def start_health_monitor(self, interval_s=30.0, timeout_s=5.0):
        """Start opt-in background probes; repeated starts are harmless."""
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        with self._lock:
            if self._monitor and self._monitor.is_alive():
                return self._monitor
            self._stop.clear()
            self._monitor = threading.Thread(
                target=self._health_loop, args=(float(interval_s), timeout_s),
                name="ptah-backend-health", daemon=True)
            self._monitor.start()
            return self._monitor

    def _health_loop(self, interval_s, timeout_s):
        while not self._stop.is_set():
            try:
                self.check_backend(timeout_s=timeout_s)
            except Exception:
                # A health patrol must never terminate the server's worker.
                pass
            self._stop.wait(interval_s)

    def stop_health_monitor(self):
        with self._lock:
            monitor = self._monitor
            self._monitor = None
            self._stop.set()
        if monitor and monitor is not threading.current_thread():
            monitor.join(timeout=2.0)


HealthAwareBackendRouter = BackendRouter


def as_backend_router(brain, metrics_path=""):
    """Adapt a legacy single brain for server health/metrics endpoints."""
    if isinstance(brain, BackendRouter):
        if metrics_path:
            brain.configure_metrics_path(metrics_path, load=True)
        return brain
    return BackendRouter([("primary", brain)], metrics_path=metrics_path)
