"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['2', '26', '28', '52', '53', '676', '702', '704', '18278', '18279', '1000000000'] + [str(rng.randint(1, 10 ** rng.randint(1, 9))) for _ in range(10)]
