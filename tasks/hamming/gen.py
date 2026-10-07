"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['0 0', '1 2', '8 1', '255 256', '5 3', f'{2 ** 64} 0', '6 1'] + [f'{rng.getrandbits(rng.randint(1, 64))} {rng.getrandbits(rng.randint(1, 64))}' for _ in range(14)]
