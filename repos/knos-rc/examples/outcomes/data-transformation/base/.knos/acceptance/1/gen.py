"""Input tables for the ledger transformation, each made from a seed, and the reference ledger in plain Python.

charges  (charge_id, customer_id, amount): amount is text with two decimals ("19.99"). The feed delivers at least
         once, so a charge row can appear two or three times, identical each time.
refunds  (refund_id, charge_id, amount): never repeated; a charge can have none, one or several.

The cases hold what a transformation written against a tidy example gets wrong: repeated charge rows, customers with
no refund at all, charges refunded more than once, and amounts whose cents do not survive binary floating point."""
import random

AWKWARD = (29, 57, 113, 829, 1999, 6499)     # each loses a cent as a double: 19.99 * 100 is 1998.9999999999998


def money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def tables(seed: int) -> dict:
    """{"charges": [[charge_id, customer_id, amount]], "refunds": [[refund_id, charge_id, amount]]}, rows shuffled."""
    rng = random.Random(seed)
    customers = [f"c{rng.randrange(10 ** 5):05d}" for _ in range(rng.randint(3, 25))]
    charges, refunds = [], []
    for n in range(rng.randint(len(customers), 120)):
        owner = customers[n] if n < len(customers) else rng.choice(customers)       # every customer has a charge
        cents = rng.choice(AWKWARD) if rng.random() < 0.3 else rng.randint(1, 500000)
        row = [f"ch_{seed}_{n}", owner, money(cents)]
        charges += [row] * (1 if rng.random() < 0.85 else rng.randint(2, 3))
        left = cents
        for _ in range(rng.choice((0, 0, 0, 1, 1, 2, 3))):
            back = rng.randint(1, left) if left else 0
            if back:
                refunds.append([f"re_{seed}_{len(refunds)}", row[0], money(back)])
                left -= back
    rng.shuffle(charges)
    rng.shuffle(refunds)
    return {"charges": charges, "refunds": refunds}


def cents(amount: str) -> int:
    whole, _, part = amount.partition(".")
    return int(whole) * 100 + int(part)


def ledger(t: dict) -> dict:
    """The reference: {customer_id: (charges, gross_cents, refund_cents, net_cents)}, in whole cents, no floats."""
    once = {c[0]: (c[1], cents(c[2])) for c in t["charges"]}
    out = {owner: [0, 0, 0] for owner, _ in once.values()}
    for owner, amount in once.values():
        out[owner][0] += 1
        out[owner][1] += amount
    for _, charge, amount in t["refunds"]:
        out[once[charge][0]][2] += cents(amount)
    return {k: (n, gross, back, gross - back) for k, (n, gross, back) in out.items()}
