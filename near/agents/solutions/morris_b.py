class Counter:
    """The usual choice: an exact count."""

    def __init__(self, rng):
        self.rng, self.register = rng, 0

    def increment(self):
        self.register += 1

    def estimate(self):
        return self.register
