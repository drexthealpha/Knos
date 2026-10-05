"""A claimed result, judged black-box by running it again. The deliverable is analysis.py and RESULT.json, the number
the supplier says analysis.py gives. The judge never loads analysis.py: "$KNOS_RUN python3 analysis.py <seed>" runs it
inside the sandbox, with the trial's rows on standard input, and the judge reads the one number it prints. The rows
come from the judge's own copy (trial.csv beside this file), not from the pull request's tree.

Paid when all of these hold:
  reproduced   with the seed fixed in the order (SEED), analysis.py prints the claimed estimate, within TOLERANCE
  repeatable   a second run with the same seed prints the same number
  computed     when every treatment-arm value is moved by a known amount, the estimate moves by that amount, within
               SLACK of it. A treatment effect is a difference between the arms, so any honest estimate of one moves
               with them; a number pasted into the script, or read from a file in the tree, stays where it is."""
import csv
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261005
TOLERANCE = 1e-6            # minutes: the claim is written to six decimals
SHIFTS = (-3.25, 1.5)       # minutes added to every treatment-arm value
SLACK = 0.10                # of the shift
SECONDS = 30


def run(argv: list[str], stdin: bytes = b"") -> str:
    try:
        got = subprocess.run([os.environ["KNOS_RUN"], *argv], input=stdin, capture_output=True, timeout=SECONDS)
    except subprocess.TimeoutExpired:
        sys.exit(f"{' '.join(argv[:2])} took more than {SECONDS} seconds")
    if got.returncode:
        sys.exit(f"{' '.join(argv[:2])} stopped with status {got.returncode}: {got.stderr.decode('utf-8', 'replace').strip()[-200:]}")
    return got.stdout.decode("utf-8", "replace")


def number(text: str, what: str) -> float:
    try:
        value = float(text.strip())
    except ValueError:
        sys.exit(f"{what} must be one number, and is {text.strip()[:60]!r}")
    if value != value or value in (float("inf"), float("-inf")):
        sys.exit(f"{what} is not a finite number")
    return value


def rows_text(rows: list[dict], shift: float = 0.0) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["arm", "minutes"])
    w.writerows([r["arm"], f"{float(r['minutes']) + (shift if r['arm'] == 'treatment' else 0.0):.2f}"] for r in rows)
    return out.getvalue().encode()


def estimate(rows: list[dict], shift: float = 0.0) -> float:
    return number(run(["python3", "analysis.py", str(SEED)], rows_text(rows, shift)), "what analysis.py prints")


def check() -> list[str]:
    with open(os.path.join(HERE, "trial.csv"), encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    try:
        claim = json.loads(run(["python3", "-c", "print(open('RESULT.json', encoding='utf-8').read(10000))"]))
        claimed, seed = claim["estimate"], claim["seed"]
    except (ValueError, KeyError, TypeError):
        return ['RESULT.json must be {"estimate": <number>, "seed": <the order\'s seed>}']
    if isinstance(claimed, bool) or not isinstance(claimed, (int, float)) or seed != SEED:
        return [f"RESULT.json must claim a number for seed {SEED}"]
    bad = []
    first = estimate(rows)
    print(f"claimed {claimed:.6f}, re-run {first:.6f}")
    if abs(first - claimed) > TOLERANCE:
        bad.append(f"reproduced: analysis.py gives {first:.6f} with seed {SEED} and RESULT.json claims {claimed:.6f}")
    if estimate(rows) != first:
        bad.append("repeatable: two runs with the same seed and the same rows printed different numbers")
    for shift in SHIFTS:
        moved = estimate(rows, shift) - first
        print(f"treatment arm moved by {shift:+.2f}: the estimate moved by {moved:+.6f}")
        if abs(moved - shift) > SLACK * abs(shift):
            bad.append(f"computed: every treatment value was moved by {shift:+.2f} minutes and the estimate moved by {moved:+.6f}; "
                       "the number is not computed from the rows it is given")
    return bad


if __name__ == "__main__":
    why = check()
    if why:
        sys.exit("\n".join(why))
    print("the claimed result is reproduced")
