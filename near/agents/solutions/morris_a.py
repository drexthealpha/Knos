class Counter:
    """A Morris counter with base 1.002: the register rises by one with probability 1.002 ** -register, and the count
    is (1.002 ** register - 1) / 0.002."""

    def __init__(self, rng):
        self.rng, self.register, self.a = rng, 0, 0.002

    def increment(self):
        if self.rng.random() < (1 + self.a) ** -self.register:
            self.register += 1

    def estimate(self):
        return ((1 + self.a) ** self.register - 1) / self.a
