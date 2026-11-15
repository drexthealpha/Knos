"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['a', 'aA', 'aabbbAAa', 'x' * 11 + 'y'] + [''.join(rng.choice('abAB') * rng.randint(1, 4) for _ in range(rng.randint(1, 9))) for _ in range(14)]
