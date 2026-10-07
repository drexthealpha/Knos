"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    words = ['the', 'A', 'of', 'war', 'AND', 'peace', "it's", 'on', 'mother-in-law', 'to', 'KILL', 'in', 'an', 'hour']
    return ['of mice and men', 'THE END', "it's on", 'on the road', 'to be'] + [' '.join(rng.choice(words) for _ in range(rng.randint(2, 7))) for _ in range(15)]
