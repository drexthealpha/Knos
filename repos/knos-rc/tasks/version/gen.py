"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    def v():
        return '.'.join(str(rng.choice([0, 1, 2, 9, 10, 11])) for _ in range(rng.randint(1, 4)))
    return ['1.0 1', '1.10 1.9', '1.0.1 1.0', '3 3.0.0.0', '0.9 0.10', '1.2.3 1.2.4', '10.0 9.9.9'] + [f'{v()} {v()}' for _ in range(14)]
