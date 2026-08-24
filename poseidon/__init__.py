"""POSEIDON - the tide kernel: an always-moving commit/push workflow.

The sea never stops; neither does the work. POSEIDON sweeps uncommitted
drift in the workspace into a snapshot commit, carries it through the
sanctioned FLOW.md lane (worktree branch -> push -> PR -> squash merge),
then settles the mirror back onto main. No change is ever left beached:
every cycle either ships, syncs, or reports why it cannot.
"""

VERSION = 1
