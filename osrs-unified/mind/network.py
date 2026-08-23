"""Network engineering engine for MIND.

Connectivity, DNS and latency engineering for every remote endpoint the
suite depends on, plus the automation around it:

  - endpoint registry (defaults + per-install overrides in MindState)
  - DNS resolution checks and HTTPS reachability probes with retry/backoff
  - rolling latency baselines with degradation classification and
    spike detection against history (runs/net_state.json)
  - egress-path awareness (proxy environment detection, values never logged)
  - self-healing guidance: offline-mode detection, transient-failure
    retries, per-endpoint degradation marks that knowledge-refresh and
    other consumers can consult before attempting network work
  - sentinel alerts and bus events (mind.net.status / mind.net.alert)

Offline-first: every function degrades gracefully without a network;
a sweep with zero reachable endpoints is a valid, reported outcome -
never an exception.
"""
import json
import os
import socket
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENDPOINTS = [
    {"name": "wikipedia-api", "url": "https://en.wikipedia.org/w/api.php",
     "role": "knowledge"},
    {"name": "github-api", "url": "https://api.github.com/",
     "role": "releases"},
    {"name": "pypi", "url": "https://pypi.org/simple/", "role": "deps"},
]
LATENCY_WARN_MS = 1500
LATENCY_DEGRADE_MS = 3000
HISTORY_KEEP = 20
RETRY_BACKOFF_S = 1.5

NET_STATE_PATH = os.path.join("runs", "net_state.json")
NET_REPORT_PATH = os.path.join("runs", "net_report.json")


def load_endpoints(root, state):
    """Default registry merged with per-install overrides from MindState."""
    endpoints = [dict(e) for e in DEFAULT_ENDPOINTS]
    try:
        extra = state.load().get("net_endpoints")
        if isinstance(extra, list):
            known = {e["name"] for e in endpoints if "name" in e}
            for entry in extra:
                if isinstance(entry, dict) and entry.get("name") \
                        and entry.get("url"):
                    if entry["name"] in known:
                        endpoints = [entry if e.get("name") == entry["name"]
                                     else e for e in endpoints]
                    else:
                        endpoints.append(dict(entry))
    except Exception:
        pass
    return endpoints


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def dns_resolve(host, timeout=3.0):
    """Resolve host via the system resolver; returns {ok, addresses}."""
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(host, None)
        return {"ok": bool(infos),
                "addresses": sorted({i[4][0] for i in infos})[:4]}
    except (OSError, UnicodeError):
        return {"ok": False, "addresses": []}


def probe_url(url, timeout=5.0, retries=2, probe_fn=None):
    """HEAD (fallback GET) probe with exponential backoff on failure."""
    attempt = 0
    last = {"ok": False, "status": None, "latency_ms": None,
            "error": "not attempted"}
    while attempt <= retries:
        t0 = time.time()
        try:
            if probe_fn is not None:
                ok, status = probe_fn(url, timeout)
            else:
                req = urllib.request.Request(
                    url, method="HEAD",
                    headers={"User-Agent": "osrs-unified-mind/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    ok, status = True, r.status
            last = {"ok": bool(ok), "status": status,
                    "latency_ms": round((time.time() - t0) * 1000),
                    "error": None if ok else f"http {status}"}
            if last["ok"]:
                return last
        except urllib.error.HTTPError as e:
            # HTTP errors still prove the network path and DNS work.
            last = {"ok": e.code < 500, "status": e.code,
                    "latency_ms": round((time.time() - t0) * 1000),
                    "error": None if e.code < 500 else f"http {e.code}"}
            if last["ok"]:
                return last
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = {"ok": False, "status": None,
                    "latency_ms": round((time.time() - t0) * 1000),
                    "error": str(e)[:120]}
        if attempt < retries:
            time.sleep(RETRY_BACKOFF_S * (2 ** attempt))
        attempt += 1
    return last


def egress_path():
    """Detect proxy configuration (booleans only - never log values)."""
    env = os.environ
    return {"http_proxy": any(k in env for k in
                              ("HTTP_PROXY", "http_proxy")),
            "https_proxy": any(k in env for k in
                               ("HTTPS_PROXY", "https_proxy")),
            "no_proxy": any(k in env for k in ("NO_PROXY", "no_proxy"))}


def _load_history(root):
    path = os.path.join(root, NET_STATE_PATH)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_history(root, history):
    _atomic_write(os.path.join(root, NET_STATE_PATH), history)


def _classify(latency_ms, baseline_ms):
    if latency_ms is None:
        return "down"
    if latency_ms > LATENCY_DEGRADE_MS:
        return "degraded"
    if baseline_ms is not None and latency_ms > max(2 * baseline_ms,
                                                    LATENCY_WARN_MS):
        # Relative anomaly outranks the absolute "slow" band: a 400ms
        # response against a 50ms baseline is an incident, not normal.
        # (is-not-None matters: a legit 0ms in-process baseline is falsy.)
        return "spike"
    if latency_ms > LATENCY_WARN_MS:
        return "slow"
    return "healthy"


def sweep(root, state, bus=None, timeout=5.0, retries=2, probe_fn=None,
          dns_fn=None):
    """Probe every endpoint; classify, alert, publish and report.

    Returns the full report dict (also written to runs/net_report.json).
    """
    dns_fn = dns_fn or dns_resolve
    history = _load_history(root)
    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "egress": egress_path(), "endpoints": [],
              "healthy": 0, "degraded": 0, "down": 0, "alerts": []}

    for endpoint in load_endpoints(root, state):
        name, url = endpoint["name"], endpoint["url"]
        host = urllib.parse.urlsplit(url).netloc.split("@")[-1]
        entry = {"name": name, "role": endpoint.get("role", ""),
                 "url": url}
        dns = dns_fn(host.split(":")[0])
        entry["dns_ok"] = dns["ok"]
        if not dns["ok"]:
            entry.update({"status": "down", "latency_ms": None,
                          "error": "dns resolution failed"})
        else:
            probe = probe_url(url, timeout=timeout, retries=retries,
                              probe_fn=probe_fn)
            hist = history.get(name, [])
            baseline = (statistics.median(hist[-HISTORY_KEEP:])
                        if hist else None)
            if not probe["ok"]:
                # A refused/timed-out probe is DOWN no matter how fast the
                # local failure returned; latency alone cannot whitewash it.
                entry.update({"status": "down",
                              "latency_ms": probe["latency_ms"],
                              "status_code": probe["status"]})
            else:
                entry.update({"status": _classify(probe["latency_ms"],
                                                  baseline),
                              "latency_ms": probe["latency_ms"],
                              "status_code": probe["status"]})
            if probe["error"]:
                entry["error"] = probe["error"]
            if probe["latency_ms"] is not None and probe["ok"]:
                hist.append(probe["latency_ms"])
                history[name] = hist[-HISTORY_KEEP:]

        report["endpoints"].append(entry)
        key = {"healthy": "healthy", "slow": "healthy",
               "spike": "degraded"}.get(entry["status"], entry["status"])
        report[key] += 1

        if entry["status"] == "down":
            report["alerts"].append(f"{name} DOWN"
                                    f" ({entry.get('error', 'unreachable')})")
        elif entry["status"] == "spike":
            report["alerts"].append(f"{name} latency spike: "
                                    f"{entry['latency_ms']}ms")

    _save_history(root, history)
    _atomic_write(os.path.join(root, NET_REPORT_PATH), report)

    for alert in report["alerts"]:
        state.log("network", "alert", alert)
        if bus is not None:
            try:
                bus.publish("mind.net.alert", {"alert": alert})
            except Exception:
                pass
    state.log("network", "sweep-done",
              f"healthy={report['healthy']} degraded={report['degraded']} "
              f"down={report['down']}")
    if bus is not None:
        try:
            bus.publish("mind.net.status", {
                "healthy": report["healthy"],
                "degraded": report["degraded"],
                "down": report["down"],
                "offline_mode": report["healthy"] == 0
                                and len(report["endpoints"]) > 0})
        except Exception:
            pass
    return report


def heal_suggestions(report):
    """Actionable repair/automation guidance derived from a sweep."""
    suggestions = []
    if report["healthy"] == 0 and report["endpoints"]:
        suggestions.append("all endpoints unreachable - enable offline "
                           "mode and defer knowledge-refresh/releases")
    if report["egress"]["https_proxy"]:
        suggestions.append("proxy detected - verify tunnel health if "
                           "probes show intermittent failures")
    for entry in report["endpoints"]:
        if entry["status"] == "down" and not entry.get("dns_ok"):
            suggestions.append(f"{entry['name']}: DNS failure - check "
                               f"resolver or hosts entry for "
                               f"{entry['url']}")
        elif entry["status"] == "degraded":
            suggestions.append(f"{entry['name']}: persistently slow - "
                               f"schedule transfers outside peak windows")
    return suggestions
