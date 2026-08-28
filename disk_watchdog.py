"""Disk space watchdog - prevent fill-up catastrophes.

Problem: Disk fill-up can cause silent failures across the entire system.
This module:
1. Monitors disk space on critical drives
2. Alerts when space is low (configurable thresholds)
3. Identifies large directories that could be cleaned
4. Integrates with sentinel as a gate

Usage:
    python disk_watchdog.py                    # check all drives
    python disk_watchdog.py --drive D          # check D: drive only
    python disk_watchdog.py --cleanup-suggest  # suggest cleanup targets
    python disk_watchdog.py --json             # machine-readable output

Exit 0 = healthy. Exit 1 = low disk space.
"""

import argparse
import json
import os
import shutil
import sys


# Thresholds (percent free)
CRITICAL_THRESHOLD = 5  # below this = critical
WARNING_THRESHOLD = 15  # below this = warning

# Drives to monitor
MONITORED_DRIVES = ["C:\\", "D:\\"]

# Large directory patterns to check for cleanup
CLEANUP_TARGETS = [
    ("__pycache__", "Python bytecode cache"),
    ("node_modules", "Node.js dependencies"),
    ("target", "Rust build artifacts"),
    ("dist", "Build output"),
    (".git", "Git repository (large)"),
    ("data/post", "Ratatosk bus data"),
    ("data/sentinel", "Sentinel incident ledger"),
]


def get_disk_usage(path):
    """Get disk usage for a path."""
    try:
        usage = shutil.disk_usage(path)
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent_free": (usage.free / usage.total) * 100,
            "percent_used": (usage.used / usage.total) * 100,
        }
    except Exception as e:
        return {"error": str(e)}


def format_bytes(b):
    """Format bytes as human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def find_large_dirs(root, max_depth=3):
    """Find large directories that could be cleaned."""
    targets = []
    
    for dirpath, dirnames, filenames in os.walk(root):
        # Limit depth
        depth = dirpath[len(root):].count(os.sep)
        if depth >= max_depth:
            dirnames[:] = []
            continue
        
        # Skip certain directories
        base = os.path.basename(dirpath)
        if base in [".git", "node_modules", "__pycache__"]:
            continue
        
        # Calculate size
        total_size = 0
        try:
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total_size += os.path.getsize(fp)
                except OSError:
                    pass
        except Exception:
            continue
        
        if total_size > 100 * 1024 * 1024:  # > 100 MB
            targets.append({
                "path": dirpath,
                "size": total_size,
                "size_human": format_bytes(total_size),
            })
    
    return sorted(targets, key=lambda x: x["size"], reverse=True)[:10]


def check_drive(drive, cleanup_suggest=False):
    """Check disk space for one drive."""
    usage = get_disk_usage(drive)
    
    if "error" in usage:
        return {
            "drive": drive,
            "status": "error",
            "error": usage["error"],
        }
    
    status = "healthy"
    if usage["percent_free"] < CRITICAL_THRESHOLD:
        status = "critical"
    elif usage["percent_free"] < WARNING_THRESHOLD:
        status = "warning"
    
    result = {
        "drive": drive,
        "status": status,
        "total": format_bytes(usage["total"]),
        "used": format_bytes(usage["used"]),
        "free": format_bytes(usage["free"]),
        "percent_free": round(usage["percent_free"], 1),
        "percent_used": round(usage["percent_used"], 1),
    }
    
    if cleanup_suggest and status != "healthy":
        result["cleanup_suggestions"] = find_large_dirs(drive)
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Disk space watchdog")
    parser.add_argument("--drive", help="Check specific drive (e.g., D)")
    parser.add_argument("--cleanup-suggest", action="store_true", help="Suggest cleanup targets")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    
    if args.drive:
        drives = [f"{args.drive.upper()}:\\"]
    else:
        drives = MONITORED_DRIVES
    
    results = []
    for drive in drives:
        if os.path.exists(drive):
            results.append(check_drive(drive, args.cleanup_suggest))
    
    # Determine overall status
    critical = any(r["status"] == "critical" for r in results)
    warning = any(r["status"] == "warning" for r in results)
    
    if args.json:
        output = {
            "drives": results,
            "status": "critical" if critical else ("warning" if warning else "healthy"),
        }
        print(json.dumps(output, indent=2))
    else:
        print("Disk space watchdog")
        for r in results:
            if "error" in r:
                print(f"  {r['drive']}: ERROR - {r['error']}")
            else:
                status_icon = {"healthy": "OK", "warning": "WARN", "critical": "CRIT"}[r["status"]]
                print(f"  {r['drive']}: {status_icon} - {r['percent_free']}% free ({r['free']} of {r['total']})")
                
                if args.cleanup_suggest and "cleanup_suggestions" in r:
                    print(f"    Cleanup suggestions:")
                    for s in r["cleanup_suggestions"][:5]:
                        print(f"      {s['path']}: {s['size_human']}")
    
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
