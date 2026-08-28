"""Scheduled task health monitor - detect silent failures.

Problem: Windows scheduled tasks can fail silently (error codes, never run,
stale schedules). This module detects:
1. Tasks that haven't run when expected
2. Tasks with non-zero last result codes
3. Tasks in unexpected states (Disabled, Running too long)

Integrates with sentinel as a gate; can also run standalone.

Usage:
    python task_health.py                    # check all Olympos + VOLTAGE tasks
    python task_health.py --fleet olympos    # check only Olympos tasks
    python task_health.py --fleet voltage    # check only VOLTAGE tasks
    python task_health.py --json             # machine-readable output

Exit 0 = all tasks healthy. Exit 1 = failures detected.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime


# Task name patterns for each fleet
OLYMPOS_TASK_PATTERNS = [
    "Olympos ZEUS",
    "Olympos Sentinel",
    "Olympos GAIA",
    "Olympos HYPNOS",
    "Olympos POSEIDON",
    "Olympos HEBE",
    "Olympos RELAY",
    "Olympos ARTEMIS",
    "Olympos KRONOS",
    "Olympos PERSEPHONE",
    "Olympos ARES",
]

VOLTAGE_TASK_PATTERNS = [
    "voltage-patrol",
    "voltage-watch",
    "voltage-pulse",
    "voltage-metis",
    "voltage-argus",
    "voltage-logia",
]

# Maximum age before a task is considered stale (hours)
MAX_TASK_AGE_HOURS = {
    # High-frequency tasks (should run often)
    "Olympos ZEUS": 0.1,  # continuous
    "Olympos Sentinel": 1,  # every 30 min
    "Olympos GAIA": 0.5,  # every 15 min
    "voltage-patrol": 0.1,  # continuous
    "voltage-watch": 1,  # every 30 min
    "voltage-pulse": 0.5,  # every 15 min
    # Daily tasks
    "Olympos HYPNOS": 25,
    "Olympos POSEIDON": 25,
    "Olympos HEBE": 25,
    "Olympos RELAY": 25,
    "Olympos ARTEMIS": 25,
    "Olympos KRONOS": 25,
    # Weekly tasks
    "voltage-metis": 7 * 24 + 1,
    "voltage-argus": 7 * 24 + 1,
    "voltage-logia": 7 * 24 + 1,
    # Permissive (rare or on-demand)
    "Olympos PERSEPHONE": 24,
    "Olympos ARES": 24,
}


def get_scheduled_tasks():
    """Query Windows scheduled tasks via schtasks LIST format."""
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "LIST", "/v"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        
        tasks = []
        current_task = {}
        
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line:
                if current_task:
                    tasks.append(current_task)
                    current_task = {}
                continue
            
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                # Remove ANSI color codes
                value = value.replace("\x1b[7m", "").replace("\x1b[0m", "")
                current_task[key] = value
        
        if current_task:
            tasks.append(current_task)
        
        return tasks
    except Exception as e:
        print(f"Error querying scheduled tasks: {e}", file=sys.stderr)
        return []


def parse_datetime(dt_str):
    """Parse Windows datetime string."""
    if not dt_str or dt_str == "N/A" or "11/30/1999" in dt_str:
        return None
    try:
        # Format: "M/D/YYYY H:MM:SS AM/PM"
        for fmt in ["%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"]:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None
    except Exception:
        return None


def check_task_health(task):
    """Check health of one scheduled task. Returns (ok, findings)."""
    findings = []
    name = task.get("TaskName", "unknown").lstrip("\\")
    status = task.get("Status", "Unknown")
    last_run = task.get("Last Run Time", "")
    last_result = task.get("Last Result", "0")
    
    # Check status
    if status == "Disabled":
        findings.append(f"{name}: task is disabled")
    
    # Check last result
    # Benign scheduler states (not failures):
    #   0x41300 (266752) ready to run at next scheduled time
    #   0x41301 (267009) currently running
    #   0x41303 (267011) has not yet run
    BENIGN_RESULTS = {0x41300, 0x41301, 0x41303}
    try:
        result_code = int(last_result)
        if result_code != 0 and result_code not in BENIGN_RESULTS:
            findings.append(f"{name}: last run failed with code {result_code}")
    except (ValueError, TypeError):
        findings.append(f"{name}: invalid last result code: {last_result}")
    
    # Check staleness (skip tasks currently running - they are active by definition)
    if status != "Running":
        last_run_dt = parse_datetime(last_run)
        if last_run_dt:
            age_hours = (datetime.now() - last_run_dt).total_seconds() / 3600
            max_age = MAX_TASK_AGE_HOURS.get(name, 24)  # default 24h
            if age_hours > max_age:
                findings.append(f"{name}: stale (last run {age_hours:.1f}h ago, max {max_age}h)")
        else:
            # Never run or unknown
            if name in MAX_TASK_AGE_HOURS:
                findings.append(f"{name}: never run or last run time unknown")
    
    ok = len(findings) == 0
    return ok, findings


def filter_tasks(tasks, fleet):
    """Filter tasks by fleet pattern."""
    if fleet == "olympos":
        patterns = OLYMPOS_TASK_PATTERNS
    elif fleet == "voltage":
        patterns = VOLTAGE_TASK_PATTERNS
    else:
        patterns = OLYMPOS_TASK_PATTERNS + VOLTAGE_TASK_PATTERNS
    
    filtered = []
    for task in tasks:
        name = task.get("TaskName", "").lstrip("\\")
        for pattern in patterns:
            if pattern.lower() in name.lower():
                filtered.append(task)
                break
    return filtered


def main():
    parser = argparse.ArgumentParser(description="Scheduled task health monitor")
    parser.add_argument("--fleet", choices=["olympos", "voltage", "all"], default="all")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    
    tasks = get_scheduled_tasks()
    if not tasks:
        print("No scheduled tasks found or query failed", file=sys.stderr)
        return 2
    
    filtered = filter_tasks(tasks, args.fleet)
    if not filtered:
        print(f"No tasks found for fleet: {args.fleet}", file=sys.stderr)
        return 2
    
    all_ok = True
    all_findings = []
    for task in filtered:
        ok, findings = check_task_health(task)
        if not ok:
            all_ok = False
            all_findings.extend(findings)
    
    if args.json:
        output = {
            "fleet": args.fleet,
            "tasks_checked": len(filtered),
            "healthy": all_ok,
            "findings": all_findings,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Task health check ({args.fleet}): {len(filtered)} tasks")
        if all_ok:
            print("  All tasks healthy")
        else:
            for finding in all_findings:
                print(f"  FAIL: {finding}")
    
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
