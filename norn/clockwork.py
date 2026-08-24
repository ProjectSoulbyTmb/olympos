"""NORN Clockwork: the injected time+chance seam (FoundationDB-style).

A Clockwork bundles a seeded RNG and a logical tick mirror behind one
object. Engines accept it duck-typed (only random/randint/choice/
getstate/setstate/advance are required), so live mode keeps today's
behavior byte-for-byte while sim mode makes any session reproducible.
"""

import random
import time

# Classic MMO tick is 0.6s; used only to derive wall-epoch from logical ticks.
SECONDS_PER_TICK = 0.6


class Clockwork:
    """Live clock when seed=None; fully deterministic when seeded."""

    def __init__(self, seed=None, start_tick=0, epoch=None):
        self.seed = seed
        self.tick = int(start_tick)
        self._epoch0 = time.time() if epoch is None else float(epoch)
        self.rng = random.Random(seed)

    @property
    def deterministic(self):
        return self.seed is not None

    def advance(self, n=1):
        self.tick += int(n)

    # ---- chance passthrough (the only RNG surface engines use) ----

    def random(self):
        return self.rng.random()

    def randint(self, a, b):
        return self.rng.randint(a, b)

    def choice(self, seq):
        return self.rng.choice(seq)

    def getstate(self):
        return self.rng.getstate()

    def setstate(self, state):
        self.rng.setstate(state)

    # ---- time seam (staleness checks, schedules) ----

    def now_epoch(self):
        return self._epoch0 + SECONDS_PER_TICK * self.tick
