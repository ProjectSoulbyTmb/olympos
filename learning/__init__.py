"""LEARNING - shared engine for Athena's learning-agent subfleet.

Members and their diets:
  metis  - mines incidents/audits/gate failures into lesson proposals
  argus  - audits doc-vs-disk drift into codex-update proposals
  logia  - distills cycle logs/history into playbook/rule amendments

All three emit PROPOSALS under ``knowledge/proposals/``; the vault is
append-only by convention and accepts additions only after operator
sign-off (feeding protocol, athena-codex section 5).
"""

from .vault import Vault, load_vault
from .dedupe import jaccard, tokens
from . import evidence, report

__all__ = ["Vault", "load_vault", "jaccard", "tokens", "evidence",
           "report"]
