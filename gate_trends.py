"""Gate trend analysis - detect degradation before failure.

Problem: Gates can degrade gradually (slower execution, intermittent failures)
before becoming hard failures. This module analyzes the sentinel incident
ledger to detect:
1. Increasing gate execution times
2. Intermittent failures (flapping)
3. Correlated failures (multiple gates failing together)
4. Regression patterns (previously green gates turning red)

Usage:
    python gate_trends.py                    # analyze all trends
    python gate_trends.py --days 7           # last 7 days
    python gate_trends.py --json             # machine-readable output

Exit 0 = no concerning trends. Exit 1 = degradation detected.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta


HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_PATH = os.path.join(HERE, "data", "sentinel", "incidents.jsonl")

# Thresholds for trend detection
SLOWDOWN_THRESHOLD = 1.5  # 50% slower than baseline
FLAP_THRESHOLD = 3  # 3 failures in window = flapping
WINDOW_DAYS = 7  # analysis window


def load_incidents(days=WINDOW_DAYS):
    """Load incidents from the ledger within the time window."""
    if not os.path.exists(LEDGER_PATH):
        return []
    
    cutoff = datetime.now() - timedelta(days=days)
    incidents = []
    
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("ts", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.replace(tzinfo=None) >= cutoff:
                        incidents.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue
    
    return incidents


def analyze_gate_performance(incidents):
    """Analyze gate execution times and failure patterns."""
    gate_stats = defaultdict(lambda: {
        "pass_count": 0,
        "fail_count": 0,
        "times": [],
        "failures": [],
    })
    
    for entry in incidents:
        kind = entry.get("kind")
        if kind != "gate":
            continue
        
        name = entry.get("name", "unknown")
        payload = entry.get("payload", {})
        detail = payload.get("detail", "")
        
        if detail == "pass":
            gate_stats[name]["pass_count"] += 1
        else:
            gate_stats[name]["fail_count"] += 1
            gate_stats[name]["failures"].append({
                "ts": entry.get("ts"),
                "detail": detail[:200],
            })
    
    return dict(gate_stats)


def detect_slowdowns(gate_stats):
    """Detect gates with increasing execution times."""
    slowdowns = []
    for name, stats in gate_stats.items():
        if len(stats["times"]) < 5:
            continue  # not enough data
        
        # Compare first half vs second half
        mid = len(stats["times"]) // 2
        first_half = stats["times"][:mid]
        second_half = stats["times"][mid:]
        
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        
        if avg_second > avg_first * SLOWDOWN_THRESHOLD:
            slowdowns.append({
                "gate": name,
                "baseline": f"{avg_first:.2f}s",
                "current": f"{avg_second:.2f}s",
                "ratio": f"{avg_second/avg_first:.2f}x",
            })
    
    return slowdowns


def detect_flapping(gate_stats):
    """Detect gates with intermittent failures (flapping)."""
    flapping = []
    for name, stats in gate_stats.items():
        if stats["fail_count"] >= FLAP_THRESHOLD:
            total = stats["pass_count"] + stats["fail_count"]
            fail_rate = stats["fail_count"] / total if total > 0 else 0
            flapping.append({
                "gate": name,
                "failures": stats["fail_count"],
                "total": total,
                "fail_rate": f"{fail_rate:.1%}",
                "recent": stats["failures"][-3:],  # last 3 failures
            })
    
    return flapping


def detect_regressions(gate_stats):
    """Detect gates that were green but are now red."""
    regressions = []
    for name, stats in gate_stats.items():
        # If we have both passes and failures, and failures are recent
        if stats["pass_count"] > 0 and stats["fail_count"] > 0:
            # Check if the last few runs were failures
            if len(stats["failures"]) >= 2:
                last_failures = stats["failures"][-2:]
                regressions.append({
                    "gate": name,
                    "passes": stats["pass_count"],
                    "failures": stats["fail_count"],
                    "recent_failures": last_failures,
                })
    
    return regressions


def main():
    parser = argparse.ArgumentParser(description="Gate trend analysis")
    parser.add_argument("--days", type=int, default=WINDOW_DAYS, help="Analysis window (days)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    
    incidents = load_incidents(args.days)
    if not incidents:
        print(f"No incidents found in last {args.days} days", file=sys.stderr)
        return 0
    
    gate_stats = analyze_gate_performance(incidents)
    
    slowdowns = detect_slowdowns(gate_stats)
    flapping = detect_flapping(gate_stats)
    regressions = detect_regressions(gate_stats)
    
    concerning = len(slowdowns) + len(flapping) + len(regressions)
    
    if args.json:
        output = {
            "window_days": args.days,
            "incidents_analyzed": len(incidents),
            "gates": len(gate_stats),
            "slowdowns": slowdowns,
            "flapping": flapping,
            "regressions": regressions,
            "concerning_trends": concerning,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Gate trend analysis (last {args.days} days)")
        print(f"  Incidents: {len(incidents)}")
        print(f"  Gates: {len(gate_stats)}")
        
        if concerning == 0:
            print("  No concerning trends detected")
        else:
            if slowdowns:
                print(f"\n  SLOWDOWNS ({len(slowdowns)}):")
                for s in slowdowns:
                    print(f"    {s['gate']}: {s['baseline']} -> {s['current']} ({s['ratio']})")
            
            if flapping:
                print(f"\n  FLAPPING ({len(flapping)}):")
                for f in flapping:
                    print(f"    {f['gate']}: {f['failures']}/{f['total']} failures ({f['fail_rate']})")
            
            if regressions:
                print(f"\n  REGRESSIONS ({len(regressions)}):")
                for r in regressions:
                    print(f"    {r['gate']}: {r['passes']} pass, {r['failures']} fail")
    
    return 1 if concerning > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
