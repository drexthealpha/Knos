"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['1900-01-01', '1900-12-31', '2100-12-31', '2024-03-01', '2023-03-01', '2100-03-01', '1999-12-31'] + [f'{rng.randint(1900, 2100)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}' for _ in range(14)]
