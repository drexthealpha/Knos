"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['7', '5 3', '9 1 5', '-3 -4', '10 2 8 4', '1 2', '-7 2 -2 9'] + [' '.join(str(rng.randint(-50, 50)) for _ in range(rng.randint(2, 9))) for _ in range(14)]
