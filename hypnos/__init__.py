"""HYPNOS - the silent task-handling organ of Yggdrasil.

Task letters land in data/post/hypnos/inbox (or *.task.json drop-ins);
HYPNOS claims the work before touching it, executes it headless,
retries what fails, resumes what a crash left behind, and feeds the
outcome back to the live system: reply letters, topic broadcasts and
verify-gate build reports. Silent by design - read the audit trail.
"""

from hypnos.kernel import Kernel, sandbox          # noqa: F401
from hypnos import content                          # noqa: F401

__all__ = ["Kernel", "sandbox", "content"]
