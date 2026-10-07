"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['0 2', '35 36', '-255 16', '1 2', '36 36', '-1 36', '1295 36', '6 2'] + [f'{rng.randint(-10 ** rng.randint(1, 12), 10 ** rng.randint(1, 12))} {rng.randint(2, 36)}' for _ in range(13)]
