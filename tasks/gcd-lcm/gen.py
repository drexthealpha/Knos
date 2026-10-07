"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['1 1', '1 9', '21 6', '999999999989 999999999989', '1000000000000 999999999999', '123456789012 987654321098', '17 289'] + [f'{rng.randint(1, 10 ** rng.randint(1, 12))} {rng.randint(1, 10 ** rng.randint(1, 12))}' for _ in range(14)]
