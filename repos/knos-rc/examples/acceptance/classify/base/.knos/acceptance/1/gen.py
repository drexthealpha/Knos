"""Card payments for the classify task: features, and whether the payment should be held for review.

The label comes from a rule of the buyer's risk team plus noise: one payment in twenty is labelled the other way (a
reviewer's mistake, a customer who called). So no classifier can be perfect, and a pull request that reaches the bar
has found the rule in the visible data, not copied anything."""
import random

FEATURES = ["amount", "hour", "country_match", "prior_chargebacks", "account_age_days", "new_device"]
NOISE = 0.05


def risky(amount: float, hour: int, country_match: int, prior: int, age: int, new_device: int) -> bool:
    return bool((amount > 100 and not country_match) or prior >= 1 or (new_device and hour <= 11 and amount > 40)
                or (age < 60 and amount > 120) or amount > 700)


def rows(rng: random.Random, n: int) -> list[list]:
    """n payments: the six features, then the label."""
    out = []
    for _ in range(n):
        x = [round(rng.lognormvariate(4.6, 1.1), 2), rng.randrange(24), int(rng.random() < .85),
             min(int(rng.expovariate(2.2)), 5), int(rng.expovariate(1 / 300)) + 1, int(rng.random() < .3)]
        out.append([*x, int(risky(*x)) ^ int(rng.random() < NOISE)])
    return out


def csv_text(table: list[list], labels: bool) -> str:
    head = FEATURES + (["held"] if labels else [])
    return "\n".join([",".join(head)] + [",".join(str(v) for v in r[:len(head)]) for r in table]) + "\n"
