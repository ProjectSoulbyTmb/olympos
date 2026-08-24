import time


class GameLoop:
    def __init__(self, tick_rate=60.0, max_catchup=5, clock=time.monotonic):
        self.dt = 1.0 / tick_rate
        self.max_catchup = max_catchup
        self.clock = clock
        self.tick_count = 0

    def step_ticks(self, n, tick, render=None):
        for _ in range(n):
            tick(self.dt)
            self.tick_count += 1
            if render is not None:
                render()

    def run(self, tick, render=None, stop=None):
        previous = self.clock()
        accumulator = 0.0
        while True:
            now = self.clock()
            frame_delta = min(now - previous, self.max_catchup * self.dt)
            accumulator += frame_delta
            previous = now
            while accumulator >= self.dt:
                tick(self.dt)
                self.tick_count += 1
                accumulator -= self.dt
                if stop is not None and stop():
                    return
            if render is not None:
                render()


class FakeClock:
    def __init__(self, step=1.0 / 30.0):
        self.now = 0.0
        self.step = step

    def __call__(self):
        current = self.now
        self.now += self.step
        return current

    def advance(self, seconds):
        self.now += seconds
