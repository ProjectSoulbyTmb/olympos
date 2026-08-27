"""Automated rollback trigger on critical gate failure.

Problem: When critical gates fail, the system can enter an unstable state.
This module provides automated rollback:
1. Monitors critical gates continuously
2. When a critical gate fails N times in a row, triggers rollback
3. Rollback = git reset to last known good state
4. Quarantines the failing commit
5. Alerts via ratatosk + ledger

Usage:
    python auto_rollback.py                    # check and rollback if needed
    python auto_rollback.py --dry-run          # show what would happen
    python auto_rollback.py --status           # show rollback state

Exit 0 = healthy or rollback succeeded. Exit 1 = rollback failed.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime


HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "data", "rollback")
STATE_FILE = os.path.join(STATE_DIR, "rollback_state.json")
LEDGER_FILE = os.path.join(STATE_DIR, "rollback_ledger.jsonl")

# Critical gates that trigger rollback on consecutive failures
CRITICAL_GATES = {
    "zeus": "zeus/verify_zeus.py",
    "hades": "hades/verify_hades.py",
    "boundary": "verify_boundary.py",
    "ratatosk": "ratatosk/verify_ratatosk.py",
}

# Consecutive failures before rollback
ROLLBACK_THRESHOLD = 3

# Maximum rollbacks per day (safety limit)
MAX_ROLLBACKS_PER_DAY = 2


def load_state():
    """Load rollback state."""
    if not os.path.exists(STATE_FILE):
        return {
            "consecutive_failures": {},
            "last_rollback": None,
            "rollbacks_today": 0,
            "last_good_commit": None,
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    """Save rollback state."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def log_rollback(event, details):
    """Log a rollback event."""
    os.makedirs(STATE_DIR, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(),
        "event": event,
        "details": details,
    }
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_current_commit():
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def run_gate(name, script):
    """Run a gate and return (ok, exit_code)."""
    try:
        result = subprocess.run(
            [sys.executable, script],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0, result.returncode
    except Exception as e:
        return False, -1


def check_critical_gates():
    """Check all critical gates. Returns dict of {name: ok}."""
    results = {}
    for name, script in CRITICAL_GATES.items():
        ok, _ = run_gate(name, script)
        results[name] = ok
    return results


def should_rollback(state, gate_results):
    """Determine if rollback should be triggered."""
    # Check consecutive failures
    for name, ok in gate_results.items():
        if not ok:
            state["consecutive_failures"][name] = state["consecutive_failures"].get(name, 0) + 1
        else:
            state["consecutive_failures"][name] = 0
    
    # Check if any gate exceeded threshold
    for name, count in state["consecutive_failures"].items():
        if count >= ROLLBACK_THRESHOLD:
            return True, name, count
    
    # Check daily limit
    if state["last_rollback"]:
        last_dt = datetime.fromisoformat(state["last_rollback"])
        if (datetime.now() - last_dt).days == 0:
            if state["rollbacks_today"] >= MAX_ROLLBACKS_PER_DAY:
                return False, "daily_limit", MAX_ROLLBACKS_PER_DAY
    
    return False, None, 0


def perform_rollback(dry_run=False):
    """Perform git rollback to last known good state."""
    state = load_state()
    
    # Get current commit
    current = get_current_commit()
    if not current:
        return False, "could not determine current commit"
    
    # Find last good commit (parent of current)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD~1"],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, "could not find parent commit"
        parent = result.stdout.strip()
    except Exception as e:
        return False, str(e)
    
    if dry_run:
        return True, f"would rollback from {current[:8]} to {parent[:8]}"
    
    # Perform rollback
    try:
        # Quarantine current state
        quarantine_dir = os.path.join(STATE_DIR, "quarantine", current[:8])
        os.makedirs(quarantine_dir, exist_ok=True)
        
        # Reset to parent
        result = subprocess.run(
            ["git", "reset", "--hard", parent],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, f"git reset failed: {result.stderr}"
        
        # Update state
        state["last_rollback"] = datetime.now().isoformat()
        state["rollbacks_today"] += 1
        state["last_good_commit"] = parent
        save_state(state)
        
        # Log
        log_rollback("rollback", {
            "from": current,
            "to": parent,
            "quarantine": quarantine_dir,
        })
        
        # Announce via ratatosk
        try:
            from ratatosk import publish
            publish("incidents", {
                "kind": "rollback",
                "from": current[:8],
                "to": parent[:8],
            }, frm="auto_rollback", kind="rollback")
        except Exception:
            pass
        
        return True, f"rolled back from {current[:8]} to {parent[:8]}"
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Automated rollback trigger")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--status", action="store_true", help="Show rollback state")
    args = parser.parse_args()
    
    state = load_state()
    
    if args.status:
        print("Rollback state:")
        print(f"  Consecutive failures: {state['consecutive_failures']}")
        print(f"  Last rollback: {state['last_rollback'] or 'never'}")
        print(f"  Rollbacks today: {state['rollbacks_today']}")
        print(f"  Last good commit: {state['last_good_commit'] or 'unknown'}")
        return 0
    
    # Check critical gates
    gate_results = check_critical_gates()
    
    # Determine if rollback needed
    should, reason, count = should_rollback(state, gate_results)
    
    if not should:
        # Save updated state
        save_state(state)
        print("All critical gates healthy")
        for name, ok in gate_results.items():
            status = "PASS" if ok else "FAIL"
            print(f"  {name}: {status}")
        return 0
    
    # Rollback needed
    print(f"ROLLBACK TRIGGERED: {reason} ({count} consecutive failures)")
    
    success, message = perform_rollback(dry_run=args.dry_run)
    
    if success:
        print(f"  {message}")
        return 0
    else:
        print(f"  ROLLBACK FAILED: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
