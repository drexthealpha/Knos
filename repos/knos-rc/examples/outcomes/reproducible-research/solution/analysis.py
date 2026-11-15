"""The effect of the new triage form on minutes to first reply: mean of the treatment arm minus mean of the control
arm, reported as the median of 2,000 bootstrap resamples (each arm resampled with replacement, same size).

    python3 analysis.py <seed> < data/trial.csv        prints the estimate, in minutes, to six decimals

Everything random comes from the seed, so the same seed and the same rows give the same number on any machine."""
import csv
import random
import statistics
import sys

RESAMPLES = 2000


def estimate(rows: list[dict], seed: int) -> float:
    arms = {arm: [float(r["minutes"]) for r in rows if r["arm"] == arm] for arm in ("control", "treatment")}
    rng = random.Random(seed)
    draws = []
    for _ in range(RESAMPLES):
        mean = {arm: statistics.fmean(rng.choices(values, k=len(values))) for arm, values in arms.items()}
        draws.append(mean["treatment"] - mean["control"])
    return statistics.median(draws)


if __name__ == "__main__":
    print(f"{estimate(list(csv.DictReader(sys.stdin)), int(sys.argv[1])):.6f}")
