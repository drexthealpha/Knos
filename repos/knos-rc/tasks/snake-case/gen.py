"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    parts = ['get', 'URL', 'Id', 'Of', 'XML', 'Node', 'v2', 'Name', 'A', 'to']
    return ['x', 'X', 'ABC', 'aB', 'getURL', 'URLOfNode', 'toXMLNodeId'] + [''.join(rng.choice(parts) for _ in range(rng.randint(2, 5))) for _ in range(14)]
