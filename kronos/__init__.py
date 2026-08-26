"""KRONOS - the resource governor of Olympos.

When the machine strains (RAM held above the hold line for long
enough), KRONOS stops the deferrable patrol tasks so interactive work
and testing keep their headroom; when calm returns, it starts them
again. The ZEUS guardians are never touched - protection runs through
every hold. Silent by design: read kronos/data/events.jsonl.
"""

from .kernel import Governor, TaskController, ram_sample   # noqa: F401
from . import content                                      # noqa: F401

__all__ = ["Governor", "TaskController", "ram_sample", "content"]
