"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['0', '1 2', '10 9 8', '2 2 2', '1 3 5', '9 10 11 1', '0 1 3 4 6'] + [' '.join(str(rng.randint(0, 14)) for _ in range(rng.randint(2, 10))) for _ in range(14)]
