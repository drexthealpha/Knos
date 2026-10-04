"""classify, as a black-box check. It runs as the judge, outside the pull request's tree, and never loads the pull
request's code: "$KNOS_RUN python3 classify.py" runs it inside the sandbox, payments go in on stdin (without their
label) and one 0 or 1 per payment comes out on stdout. The score is accuracy against the labels.

Two sets of 1,500 payments: the hidden set the risk team labelled by hand (hidden.csv), and a set drawn fresh on every
run. To be paid, a submission must reach ACCURACY on each of the two."""
import csv
import os
import random
import subprocess
import sys

import gen

HERE = os.path.dirname(os.path.abspath(__file__))
ACCURACY = 0.85
SECONDS = 3    # for one set


def predict(table: list[list]) -> list[int]:
    try:
        got = subprocess.run([os.environ["KNOS_RUN"], "python3", "classify.py"], input=gen.csv_text(table, False).encode(),
                             capture_output=True, timeout=SECONDS)
    except subprocess.TimeoutExpired:
        sys.exit(f"classify.py took more than {SECONDS} seconds on {len(table)} payments")
    if got.returncode:
        sys.exit(f"classify.py stopped with status {got.returncode}: {got.stderr.decode('utf-8', 'replace')[-300:]}")
    try:
        lines = got.stdout.decode("utf-8").split()
    except UnicodeDecodeError:
        sys.exit("classify.py wrote bytes that are not UTF-8")
    if len(lines) != len(table) or any(x not in ("0", "1") for x in lines):
        sys.exit(f"classify.py must print one 0 or 1 for each of the {len(table)} payments, and printed {len(lines)} words")
    return [int(x) for x in lines]


def accuracy(table: list[list], what: str) -> None:
    got = predict(table)
    right = sum(g == r[-1] for g, r in zip(got, table)) / len(table)
    print(f"{what}: accuracy {right:.3f} (needs {ACCURACY})")
    if right < ACCURACY:
        sys.exit(f"{what}: accuracy {right:.3f}, below the {ACCURACY} that is paid")


with open(os.path.join(HERE, "hidden.csv"), encoding="utf-8", newline="") as fh:
    hidden = [[float(v) for v in r] for r in list(csv.reader(fh))[1:]]
accuracy(hidden, "the hidden set")
accuracy(gen.rows(random.Random(os.urandom(16)), 1500), "a new set")
