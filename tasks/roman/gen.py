"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['1', '3', '9', '14', '40', '90', '400', '444', '900', '2024', '3888'] + [str(rng.randint(1, 3999)) for _ in range(12)]
