"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    def t():
        return f'{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}'
    return ['00:00 23:59', '23:59 00:00', '00:00 00:00', '08:05 08:04', '10:30 09:30'] + [f'{t()} {t()}' for _ in range(15)]
