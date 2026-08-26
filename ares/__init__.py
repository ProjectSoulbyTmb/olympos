"""ARES - code seal kernel (vault-cipher).

Dual-factor in-place encryption: DPAPI-bound machine key + scrypt-
stretched unlock phrase. Sealed .ares blobs are inert off-machine and
brute-hostile on it. See README.md for the threat model and honest
gaps. Blueprint: daedalus/blueprint_ares.py (gate 11/11).
"""

VERSION = "1.0.0"
