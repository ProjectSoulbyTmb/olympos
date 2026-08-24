---
name: yggdrasil-conventions
triggers: yggdrasil, realm, gate, verify, doctor, sentinel
---
You work inside Yggdrasil (repo root D:\THOTH): a fleet of protection and
automation kernels. House rules you MUST honor:

1. Standard library only in Python realms - no third-party imports.
2. Verify before claiming health. Every realm ships a verify gate:
   `python <realm>/verify_<realm>.py` must exit 0 before you claim success.
   Use the verify_gate tool; never assert a green build without it.
3. Ports are owned: vulcan 43901, zeus 43902, ptah 43903.
4. Fail safe: destructive actions require explicit human confirmation.
5. Data dirs (`ptah/data/`, `zeus/data/`, `data/`) are gitignored runtime
   state - never commit them.
6. doctor.py stabilizes the workspace; sentinel.py watches continuously.
   If your change could affect gates, run `python doctor.py --ci`.
