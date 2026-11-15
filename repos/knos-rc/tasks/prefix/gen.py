"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    stems = ['inter', 'intern', 'internal', 'into', 'in', 'ion', 'interval', 'xnter']
    return ['alone', 'ab abc abd', 'abc abd ab', 'aXc aYc', 'inter internal xnter', 'abc abc abd', 'tea ten toa'] + [' '.join(rng.choice(stems) for _ in range(rng.randint(2, 5))) for _ in range(14)]
