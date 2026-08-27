"""Critical state backup automation.

Problem: Critical state (Hades seals, Zeus baselines, Norn seeds, etc.) can be
lost or corrupted. This module:
1. Backs up critical state files to a rotating backup directory
2. Verifies backup integrity
3. Restores from backup if needed
4. Integrates with sentinel

Usage:
    python state_backup.py                    # backup critical state
    python state_backup.py --verify           # verify backup integrity
    python state_backup.py --restore          # restore from backup
    python state_backup.py --list             # list available backups

Exit 0 = success. Exit 1 = failure.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime


HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(HERE, "data", "backups", "state")
MAX_BACKUPS = 10  # keep last 10 backups

# Critical state files to backup
CRITICAL_STATE = [
    # Hades
    ("hades/state/seal.json", "Hades seal manifest"),
    ("hades/state/audit.jsonl", "Hades audit chain"),
    ("hades/state/artifacts/artifact_manifest.json", "Hades artifact manifest"),
    # Zeus
    ("zeus/data/baseline.json", "Zeus integrity baseline"),
    ("zeus/data/audit.jsonl", "Zeus audit trail"),
    # Norn
    ("norn/seeds", "Norn replay seeds"),
    # Ratatosk
    ("data/post/registry.json", "Ratatosk organ registry"),
    # Sentinel
    ("data/sentinel/incidents.jsonl", "Sentinel incident ledger"),
    # Rollback
    ("data/rollback/rollback_state.json", "Rollback state"),
]


def compute_checksum(path):
    """Compute SHA-256 checksum of a file."""
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def backup_state():
    """Backup critical state files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"state_{timestamp}")
    os.makedirs(backup_path, exist_ok=True)
    
    manifest = {
        "timestamp": timestamp,
        "created": datetime.now().isoformat(),
        "files": [],
    }
    
    backed_up = 0
    for rel_path, description in CRITICAL_STATE:
        src = os.path.join(HERE, rel_path)
        if not os.path.exists(src):
            continue
        
        dst = os.path.join(backup_path, rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            
            checksum = compute_checksum(src) if os.path.isfile(src) else None
            manifest["files"].append({
                "path": rel_path,
                "description": description,
                "checksum": checksum,
                "size": os.path.getsize(src) if os.path.isfile(src) else None,
            })
            backed_up += 1
        except Exception as e:
            print(f"  WARNING: could not backup {rel_path}: {e}", file=sys.stderr)
    
    # Write manifest
    manifest_path = os.path.join(backup_path, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    
    # Rotate old backups
    rotate_backups()
    
    return backed_up, backup_path


def rotate_backups():
    """Keep only the last MAX_BACKUPS backups."""
    if not os.path.exists(BACKUP_DIR):
        return
    
    backups = []
    for entry in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, entry)
        if os.path.isdir(path) and entry.startswith("state_"):
            backups.append((entry, path))
    
    backups.sort(reverse=True)
    
    for _, path in backups[MAX_BACKUPS:]:
        try:
            shutil.rmtree(path)
        except Exception as e:
            print(f"  WARNING: could not remove old backup {path}: {e}", file=sys.stderr)


def verify_backup(backup_path=None):
    """Verify backup integrity."""
    if backup_path is None:
        # Find latest backup
        if not os.path.exists(BACKUP_DIR):
            return False, "no backup directory"
        
        backups = [e for e in os.listdir(BACKUP_DIR) if e.startswith("state_")]
        if not backups:
            return False, "no backups found"
        
        backups.sort(reverse=True)
        backup_path = os.path.join(BACKUP_DIR, backups[0])
    
    manifest_path = os.path.join(backup_path, "manifest.json")
    if not os.path.exists(manifest_path):
        return False, "manifest missing"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    verified = 0
    failed = 0
    
    for file_entry in manifest["files"]:
        rel_path = file_entry["path"]
        expected_checksum = file_entry.get("checksum")
        
        backup_file = os.path.join(backup_path, rel_path.replace("/", os.sep))
        if not os.path.exists(backup_file):
            failed += 1
            continue
        
        if expected_checksum and os.path.isfile(backup_file):
            actual_checksum = compute_checksum(backup_file)
            if actual_checksum != expected_checksum:
                failed += 1
                continue
        
        verified += 1
    
    return failed == 0, f"{verified} verified, {failed} failed"


def list_backups():
    """List available backups."""
    if not os.path.exists(BACKUP_DIR):
        return []
    
    backups = []
    for entry in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, entry)
        if os.path.isdir(path) and entry.startswith("state_"):
            manifest_path = os.path.join(path, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                backups.append({
                    "name": entry,
                    "created": manifest.get("created"),
                    "files": len(manifest.get("files", [])),
                })
    
    return sorted(backups, key=lambda x: x["created"], reverse=True)


def restore_backup(backup_name=None):
    """Restore from backup."""
    if backup_name is None:
        # Find latest backup
        backups = list_backups()
        if not backups:
            return False, "no backups available"
        backup_name = backups[0]["name"]
    
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        return False, f"backup {backup_name} not found"
    
    # Verify first
    ok, msg = verify_backup(backup_path)
    if not ok:
        return False, f"backup verification failed: {msg}"
    
    restored = 0
    for entry in os.listdir(backup_path):
        if entry == "manifest.json":
            continue
        
        src = os.path.join(backup_path, entry)
        dst = os.path.join(HERE, entry)
        
        try:
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            restored += 1
        except Exception as e:
            print(f"  WARNING: could not restore {entry}: {e}", file=sys.stderr)
    
    return True, f"restored {restored} items from {backup_name}"


def main():
    parser = argparse.ArgumentParser(description="Critical state backup automation")
    parser.add_argument("--verify", action="store_true", help="Verify backup integrity")
    parser.add_argument("--restore", action="store_true", help="Restore from backup")
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument("--backup-name", help="Specific backup to restore/verify")
    args = parser.parse_args()
    
    if args.list:
        backups = list_backups()
        if not backups:
            print("No backups found")
        else:
            print(f"Available backups ({len(backups)}):")
            for b in backups:
                print(f"  {b['name']}: {b['created']} ({b['files']} files)")
        return 0
    
    if args.verify:
        ok, msg = verify_backup(args.backup_name)
        print(f"Backup verification: {'PASS' if ok else 'FAIL'} - {msg}")
        return 0 if ok else 1
    
    if args.restore:
        ok, msg = restore_backup(args.backup_name)
        print(f"Restore: {'SUCCESS' if ok else 'FAILED'} - {msg}")
        return 0 if ok else 1
    
    # Default: backup
    count, path = backup_state()
    print(f"Backed up {count} critical state items to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
