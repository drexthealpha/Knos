"""clean-csv, as a black-box check. It runs as the judge, outside the pull request's tree, and never loads the pull
request's code: "$KNOS_RUN python3 clean.py" runs it inside the sandbox, a messy file goes in on stdin and the cleaned
file comes out on stdout. The answer is compared with the clean table the messy file was made from.

Six files: one real sample the buyer kept back (held_out/) and five drawn fresh on every run, from 25 to 120 rows. A
file must match cell for cell, so a submission cannot pass on the sample alone, and a refused one is told which row."""
import csv
import io
import os
import random
import subprocess
import sys

import gen

HERE = os.path.dirname(os.path.abspath(__file__))
SECONDS = 3   # for one file


def run(data: bytes, what: str) -> list[list[str]]:
    try:
        got = subprocess.run([os.environ["KNOS_RUN"], "python3", "clean.py"], input=data, capture_output=True, timeout=SECONDS)
    except subprocess.TimeoutExpired:
        sys.exit(f"clean.py took more than {SECONDS} seconds on {what}")
    if got.returncode:
        sys.exit(f"clean.py stopped with status {got.returncode} on {what}: {got.stderr.decode('utf-8', 'replace')[-300:]}")
    try:
        text = got.stdout.decode("utf-8")
    except UnicodeDecodeError:
        sys.exit(f"clean.py wrote bytes that are not UTF-8 on {what}")
    return [r for r in csv.reader(io.StringIO(text)) if r]


def table(text: str) -> list[list[str]]:
    return [r for r in csv.reader(io.StringIO(text)) if r][1:]


def check(got: list[list[str]], want: list[list[str]], what: str) -> None:
    if not got or got[0] != gen.OUT_HEADER:
        sys.exit(f"{what}: the first line must be {','.join(gen.OUT_HEADER)}, not {got[0] if got else 'nothing'}")
    got = got[1:]
    for i, (g, w) in enumerate(zip(got, want), 1):
        if g != w:
            sys.exit(f"{what}: row {i} is {g}, expected {w}")
    if len(got) != len(want):
        sys.exit(f"{what}: {len(got)} rows, expected {len(want)}")


with open(os.path.join(HERE, "held_out", "messy.csv"), "rb") as f:
    messy = f.read()
with open(os.path.join(HERE, "held_out", "expected.csv"), encoding="utf-8", newline="") as f:
    check(run(messy, "the held-out file"), table(f.read()), "the held-out file")
rng = random.Random(os.urandom(16))
for n in (25, 40, 60, 80, 120):
    want = gen.clean_table(rng, n)
    check(run(gen.messy_file(rng, want).encode("utf-8"), f"a new file of {n} customers"), want, f"a new file of {n} customers")
