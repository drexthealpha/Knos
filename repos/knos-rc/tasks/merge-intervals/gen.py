"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    def one():
        a = rng.randint(0, 40)
        return f'{a}-{a + rng.randint(0, 9)}'
    return ['4-4', '1-10 2-3 4-5', '6-8 1-2 2-6', '0-1 3-4 1-3', '10-12 1-20 30-31'] + [' '.join(one() for _ in range(rng.randint(2, 7))) for _ in range(15)]
