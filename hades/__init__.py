"""HADES - the silent kernel that guards this workspace's ideas.

Named for the god who keeps what is buried. Hades seals every protected
asset (byte hashes + structure fingerprints), detects tampering, finds
rebranded copies of our logic anywhere on disk, watermarks provenance
into source, and keeps a hash-chained audit trail that cannot be quietly
rewritten.

Doctrine (hard rule): Hades is defensive only. It detects, records,
attests and gates. It never destroys data, never retaliates, never
phones home. Evidence goes to humans; humans decide what happens next.

Run the self-test gate:  python hades/verify_hades.py
Command surface:         python hades/cli.py --help
"""

__version__ = "1.0.0"
