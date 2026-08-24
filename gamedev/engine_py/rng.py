import hashlib
import json
import random


class RNG:
    def __init__(self, seed):
        self.seed = seed
        self._r = random.Random(seed)

    def random(self):
        return self._r.random()

    def randint(self, a, b):
        return self._r.randint(a, b)

    def uniform(self, a, b):
        return self._r.uniform(a, b)

    def choice(self, seq):
        return self._r.choice(list(seq))

    def shuffle(self, lst):
        self._r.shuffle(lst)

    def derive(self, tag):
        digest = hashlib.sha256(f"{self.seed}:{tag}".encode("utf-8")).digest()
        return RNG(int.from_bytes(digest[:8], "big"))


def state_hash(obj):
    payload = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), default=repr
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
