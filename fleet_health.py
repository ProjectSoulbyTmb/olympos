"""Cross-fleet incident correlation - unified health view.

Problem: Olympos and VOLTAGE are isolated fleets but share hardware. A hardware
issue (disk full, memory pressure, CPU saturation) could affect both. This module:
1. Reads incidents from both fleet ledgers
2. Correlates by timestamp (within a window)
3. Detects simultaneous failures (potential hardware issues)
4. Provides a unified health dashboard

Usage:
    python fleet_health.py                    # unified health view
    python fleet_health.py --hours 24         # last 24 hours
    python fleet_health.py --json             # machine-readable output

Exit 0 = healthy. Exit 1 = concerning patterns detected.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta


OLYMPOS_LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                               "data", "sentinel", "incidents.jsonl")
VOLTAGE_LEDGER = os.path.join("D:\\VOLTAGE", "data", "sentinel", "incidents.jsonl")

# Correlation window (seconds) - incidents within this window are considered related
CORRELATION_WINDOW_S = 300  # 5 minutes

# Recent window (hours) for the single-fleet failure-rate check. Only failures
# inside this window count toward "concerning" - resolved historical incidents
# (e.g. from setup/troubleshooting) must not keep the fleet red indefinitely.
RECENT_WINDOW_H = 1


def load_ledger(path):
    """Load incidents from a ledger file."""
    if not os.path.exists(path):
        return []
    
    incidents = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                incidents.append(entry)
            except json.JSONDecodeError:
                continue
    
    return incidents


def parse_timestamp(ts_str):
    """Parse ISO timestamp string."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def correlate_incidents(olympos_incidents, voltage_incidents, window_s=CORRELATION_WINDOW_S):
    """Find failure incidents that occurred within the correlation window."""
    correlations = []
    
    # Filter to failures only
    olympos_failures = [
        inc for inc in olympos_incidents
        if inc.get("payload", {}).get("detail") != "pass"
    ]
    voltage_failures = [
        inc for inc in voltage_incidents
        if inc.get("payload", {}).get("detail") != "pass"
    ]
    
    for o_inc in olympos_failures:
        o_ts = parse_timestamp(o_inc.get("ts"))
        if not o_ts:
            continue
        o_payload = o_inc.get("payload", {})
        
        for v_inc in voltage_failures:
            v_ts = parse_timestamp(v_inc.get("ts"))
            if not v_ts:
                continue
            v_payload = v_inc.get("payload", {})
            
            delta = abs((o_ts - v_ts).total_seconds())
            if delta <= window_s:
                o_name = o_payload.get("name")
                v_name = v_payload.get("name")
                # Only a same-named gate failing in both fleets is a real
                # shared-dependency signal. Coincidental different-name
                # failures (or progress/summary artifacts like "14/14") are
                # not hardware correlations.
                if not o_name or not v_name or o_name != v_name:
                    continue
                correlations.append({
                    "olympos": {
                        "ts": o_inc.get("ts"),
                        "kind": o_payload.get("gate_kind"),
                        "name": o_payload.get("name"),
                        "detail": o_payload.get("detail", "")[:100],
                    },
                    "voltage": {
                        "ts": v_inc.get("ts"),
                        "kind": v_payload.get("gate_kind"),
                        "name": v_payload.get("name"),
                        "detail": v_payload.get("detail", "")[:100],
                    },
                    "delta_s": delta,
                })
    
    return correlations


def summarize_fleet(incidents, fleet_name):
    """Summarize incidents for one fleet."""
    by_kind = defaultdict(int)
    by_gate = defaultdict(int)
    failures = []
    
    for inc in incidents:
        payload = inc.get("payload", {})
        kind = payload.get("gate_kind", "unknown")
        by_kind[kind] += 1
        
        if kind == "gate":
            name = payload.get("name", "unknown")
            by_gate[name] += 1
            detail = payload.get("detail", "")
            if detail != "pass":
                failures.append({
                    "ts": inc.get("ts"),
                    "gate": name,
                    "detail": detail[:100],
                })
    
    return {
        "fleet": fleet_name,
        "total_incidents": len(incidents),
        "by_kind": dict(by_kind),
        "gate_failures": len(failures),
        "recent_failures": failures[-5:],  # last 5
    }


def main():
    parser = argparse.ArgumentParser(description="Cross-fleet health correlation")
    parser.add_argument("--hours", type=int, default=24, help="Time window (hours)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    
    cutoff = datetime.now() - timedelta(hours=args.hours)
    
    # Load and filter incidents
    olympos_all = load_ledger(OLYMPOS_LEDGER)
    voltage_all = load_ledger(VOLTAGE_LEDGER)
    
    olympos_incidents = [
        inc for inc in olympos_all
        if parse_timestamp(inc.get("ts")) and parse_timestamp(inc.get("ts")) >= cutoff
    ]
    voltage_incidents = [
        inc for inc in voltage_all
        if parse_timestamp(inc.get("ts")) and parse_timestamp(inc.get("ts")) >= cutoff
    ]
    
    # Correlate
    correlations = correlate_incidents(olympos_incidents, voltage_incidents)
    
    # Summarize
    olympos_summary = summarize_fleet(olympos_incidents, "olympos")
    voltage_summary = summarize_fleet(voltage_incidents, "voltage")
    
    # Determine health status
    concerning = len(correlations) > 0
    if not concerning:
        # Check for high CURRENT failure rates (recent window only, so resolved
        # historical incidents don't keep this red).
        recent_cutoff = datetime.now() - timedelta(hours=RECENT_WINDOW_H)

        def _recent_fails(incidents):
            n = 0
            for inc in incidents:
                pl = inc.get("payload", {})
                if pl.get("gate_kind") == "gate" and pl.get("detail") != "pass":
                    ts = parse_timestamp(inc.get("ts"))
                    if ts and ts >= recent_cutoff:
                        n += 1
            return n

        if _recent_fails(olympos_incidents) > 10 or _recent_fails(voltage_incidents) > 10:
            concerning = True
    
    if args.json:
        output = {
            "window_hours": args.hours,
            "olympos": olympos_summary,
            "voltage": voltage_summary,
            "correlations": len(correlations),
            "correlated_incidents": correlations[:10],  # first 10
            "concerning": concerning,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Cross-fleet health (last {args.hours} hours)")
        print(f"\n  OLYMPOS:")
        print(f"    Incidents: {olympos_summary['total_incidents']}")
        print(f"    Gate failures: {olympos_summary['gate_failures']}")
        if olympos_summary["recent_failures"]:
            print(f"    Recent failures:")
            for f in olympos_summary["recent_failures"][-3:]:
                print(f"      {f['ts']}: {f['gate']}")
        
        print(f"\n  VOLTAGE:")
        print(f"    Incidents: {voltage_summary['total_incidents']}")
        print(f"    Gate failures: {voltage_summary['gate_failures']}")
        if voltage_summary["recent_failures"]:
            print(f"    Recent failures:")
            for f in voltage_summary["recent_failures"][-3:]:
                print(f"      {f['ts']}: {f['gate']}")
        
        print(f"\n  CORRELATIONS:")
        if correlations:
            print(f"    {len(correlations)} correlated incidents detected")
            for c in correlations[:3]:
                print(f"      Olympos {c['olympos']['name']} <-> Voltage {c['voltage']['name']} ({c['delta_s']:.0f}s)")
        else:
            print(f"    No correlated incidents")
        
        print(f"\n  STATUS: {'CONCERNING' if concerning else 'HEALTHY'}")
    
    return 1 if concerning else 0


if __name__ == "__main__":
    sys.exit(main())
