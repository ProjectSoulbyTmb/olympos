# Enhanced Safety Measures for Project Stability

**Date:** 2026-08-27  
**Status:** Implemented and verified  
**Scope:** Olympos and VOLTAGE fleets

## Overview

This document describes the comprehensive safety measures implemented to ensure project stability moving forward. These measures provide multiple layers of protection against failures, degradation, and data loss.

## Safety Layers

### 1. Scheduled Task Health Monitor

**Purpose:** Detect silent failures in Windows scheduled tasks  
**Module:** `task_health.py`

**What it does:**
- Monitors all Olympos and VOLTAGE scheduled tasks
- Detects tasks that haven't run when expected
- Identifies tasks with non-zero exit codes
- Alerts on stale or disabled tasks

**Usage:**
```bash
python task_health.py --fleet voltage    # Check VOLTAGE tasks
python task_health.py --fleet olympos    # Check Olympos tasks
python task_health.py --json             # Machine-readable output
```

**Integration:** Runs as part of sentinel sweeps

**Example output:**
```
Task health check (voltage): 6 tasks
  FAIL: voltage-argus: last run failed with code 267011
  FAIL: voltage-argus: never run or last run time unknown
```

### 2. Gate Trend Analysis

**Purpose:** Detect degradation before hard failures  
**Module:** `gate_trends.py`

**What it does:**
- Analyzes sentinel incident ledger over time
- Detects increasing gate execution times (slowdowns)
- Identifies intermittent failures (flapping)
- Finds regression patterns (previously green gates turning red)

**Usage:**
```bash
python gate_trends.py                    # Analyze last 7 days
python gate_trends.py --days 14          # Analyze last 14 days
python gate_trends.py --json             # Machine-readable output
```

**Thresholds:**
- Slowdown: 50% slower than baseline
- Flapping: 3+ failures in window
- Window: 7 days (configurable)

**Example output:**
```
Gate trend analysis (last 7 days)
  Incidents: 46
  Gates: 12
  No concerning trends detected
```

### 3. Cross-Fleet Incident Correlation

**Purpose:** Unified health view across Olympos and VOLTAGE  
**Module:** `fleet_health.py`

**What it does:**
- Reads incidents from both fleet ledgers
- Correlates failures by timestamp (within 5-minute window)
- Detects simultaneous failures (potential hardware issues)
- Provides unified health dashboard

**Usage:**
```bash
python fleet_health.py                   # Last 24 hours
python fleet_health.py --hours 48        # Last 48 hours
python fleet_health.py --json            # Machine-readable output
```

**Example output:**
```
Cross-fleet health (last 24 hours)

  OLYMPOS:
    Incidents: 9
    Gate failures: 0

  VOLTAGE:
    Incidents: 640
    Gate failures: 0

  CORRELATIONS:
    No correlated incidents

  STATUS: HEALTHY
```

### 4. Automated Rollback Trigger

**Purpose:** Automatic recovery from critical gate failures  
**Module:** `auto_rollback.py`

**What it does:**
- Monitors critical gates (zeus, hades, boundary, ratatosk)
- Triggers rollback after 3 consecutive failures
- Performs git reset to last known good state
- Quarantines failing commit
- Alerts via ratatosk + ledger
- Limits to 2 rollbacks per day (safety)

**Usage:**
```bash
python auto_rollback.py                  # Check and rollback if needed
python auto_rollback.py --dry-run        # Show what would happen
python auto_rollback.py --status         # Show rollback state
```

**Critical gates:**
- `zeus/verify_zeus.py` - Protection kernel
- `hades/verify_hades.py` - Provenance system
- `verify_boundary.py` - Isolation boundary
- `ratatosk/verify_ratatosk.py` - Message bus

**Safety limits:**
- 3 consecutive failures before rollback
- Maximum 2 rollbacks per day
- Rollback = git reset --hard to parent commit

**Example output:**
```
Rollback state:
  Consecutive failures: {}
  Last rollback: never
  Rollbacks today: 0
  Last good commit: unknown
```

### 5. Disk Space Watchdog

**Purpose:** Prevent fill-up catastrophes  
**Module:** `disk_watchdog.py`

**What it does:**
- Monitors disk space on C:\ and D:\
- Alerts when space is low (configurable thresholds)
- Identifies large directories for cleanup
- Integrates with sentinel

**Usage:**
```bash
python disk_watchdog.py                  # Check all drives
python disk_watchdog.py --drive D        # Check D: only
python disk_watchdog.py --cleanup-suggest # Suggest cleanup targets
python disk_watchdog.py --json           # Machine-readable output
```

**Thresholds:**
- Critical: < 5% free
- Warning: < 15% free

**Example output:**
```
Disk space watchdog
  C:\: OK - 25.4% free (54.6 GB of 214.9 GB)
  D:\: OK - 72.5% free (675.0 GB of 931.5 GB)
```

### 6. Critical State Backup Automation

**Purpose:** Protect critical state from loss/corruption  
**Module:** `state_backup.py`

**What it does:**
- Backs up critical state files (Hades seals, Zeus baselines, etc.)
- Rotates backups (keeps last 10)
- Verifies backup integrity with SHA-256 checksums
- Restores from backup if needed

**Usage:**
```bash
python state_backup.py                   # Backup critical state
python state_backup.py --verify          # Verify backup integrity
python state_backup.py --restore         # Restore from backup
python state_backup.py --list            # List available backups
```

**Backed up state:**
- `hades/state/seal.json` - Hades seal manifest
- `hades/state/audit.jsonl` - Hades audit chain
- `hades/state/artifacts/artifact_manifest.json` - Artifact manifest
- `zeus/data/baseline.json` - Zeus integrity baseline
- `zeus/data/audit.jsonl` - Zeus audit trail
- `data/sentinel/incidents.jsonl` - Incident ledger
- `data/rollback/rollback_state.json` - Rollback state

**Example output:**
```
Backed up 4 critical state items to D:\THOTH\data\backups\state\state_20260827_183214
```

## Integration with Sentinel

All safety modules integrate with the sentinel system:

```python
# In sentinel.py
SAFETY_GATES = [
    ("task_health", "task_health.py"),
    ("gate_trends", "gate_trends.py"),
    ("fleet_health", "fleet_health.py"),
    ("disk_watchdog", "disk_watchdog.py"),
    ("state_backup", "state_backup.py"),
]
```

Sentinel runs these checks every sweep and logs incidents to the ledger.

## Operator Procedures

### Daily Health Check

```bash
# Quick health overview
python fleet_health.py
python task_health.py --fleet voltage
python disk_watchdog.py

# Check for degradation
python gate_trends.py
```

### Weekly Maintenance

```bash
# Backup critical state
python state_backup.py

# Verify backups
python state_backup.py --verify

# Check rollback state
python auto_rollback.py --status
```

### Emergency Procedures

**If critical gates fail:**
1. Check `auto_rollback.py --status`
2. If rollback triggered, review `data/rollback/rollback_ledger.jsonl`
3. If manual intervention needed: `python auto_rollback.py --dry-run`
4. Restore from backup: `python state_backup.py --restore`

**If disk space critical:**
1. Run `python disk_watchdog.py --cleanup-suggest`
2. Review suggestions and clean up
3. Verify with `python disk_watchdog.py`

**If tasks failing:**
1. Run `python task_health.py --fleet voltage`
2. Check task registration: `schtasks /query /tn "voltage-metis" /v`
3. Re-register if needed: `python D:\VOLTAGE\organ\voltage-tasks\register_voltage_learning_tasks.ps1`

## Safety Doctrine

### Principles

1. **Detect early:** Catch degradation before it becomes failure
2. **Automate recovery:** Rollback automatically when possible
3. **Preserve state:** Backup critical state continuously
4. **Correlate across fleets:** Hardware issues affect both fleets
5. **Limit automation:** Safety limits prevent cascading failures

### Safety Limits

- **Rollback limit:** 2 per day (prevents infinite loops)
- **Backup rotation:** Keep last 10 (prevents disk fill)
- **Correlation window:** 5 minutes (prevents false positives)
- **Disk thresholds:** 5% critical, 15% warning (conservative)

### Monitoring Cadence

| Check | Frequency | Module |
|-------|-----------|--------|
| Task health | Every sentinel sweep | `task_health.py` |
| Gate trends | Daily | `gate_trends.py` |
| Fleet health | Every sentinel sweep | `fleet_health.py` |
| Disk space | Every sentinel sweep | `disk_watchdog.py` |
| State backup | Daily | `state_backup.py` |
| Rollback check | Every sentinel sweep | `auto_rollback.py` |

## Verification

All safety measures have been verified:

```bash
# Run all safety checks
python task_health.py --fleet voltage
python gate_trends.py
python fleet_health.py
python auto_rollback.py --status
python disk_watchdog.py
python state_backup.py --verify

# Run full gate sweep
python -c "
import subprocess, sys
gates = [
    ('zeus', 'zeus/verify_zeus.py'),
    ('vulcan', 'vulcan/verify_vulcan.py'),
    ('hades', 'hades/verify_hades.py'),
    ('ratatosk', 'ratatosk/verify_ratatosk.py'),
    ('norn', 'norn/verify_norn.py'),
    ('ptah', 'ptah/verify_ptah.py'),
    ('atlas', 'atlas/verify_atlas.py'),
    ('buskit', 'verify_buskit.py'),
    ('boundary', 'verify_boundary.py'),
    ('scope', 'verify_scope.py'),
    ('secrets', 'verify_secrets.py'),
    ('coverage', 'verify_coverage.py'),
    ('forseti', 'verify_forseti.py'),
    ('sindri', 'verify_sindri.py'),
    ('system', 'verify_system.py'),
    ('learning', 'verify_learning.py'),
    ('relay', 'relay/verify_relay.py'),
]
for name, script in gates:
    r = subprocess.run([sys.executable, script], capture_output=True, timeout=120)
    print(f'{name}: {\"PASS\" if r.returncode == 0 else \"FAIL\"}')
"
```

## Future Enhancements

Potential future safety measures:

1. **Predictive failure analysis:** Use ML to predict gate failures
2. **Automated capacity planning:** Alert before resources exhausted
3. **Cross-machine redundancy:** Replicate state to backup machine
4. **Automated incident response:** Auto-triage and fix common issues
5. **Safety drill automation:** Regular safety drills to verify measures work

## Conclusion

These safety measures provide comprehensive protection for project stability:
- **6 safety modules** covering all critical aspects
- **Automated detection** of failures and degradation
- **Automated recovery** via rollback and restore
- **Unified monitoring** across both fleets
- **Operator procedures** for manual intervention

All measures are integrated with sentinel and run automatically. The system is designed to be self-healing while preserving operator control through safety limits and manual override capabilities.
