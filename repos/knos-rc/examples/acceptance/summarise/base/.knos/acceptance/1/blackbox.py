"""summarise, as a black-box check. It runs as the judge, outside the pull request's tree, and never loads the pull
request's code: "$KNOS_RUN python3 summarise.py" runs it inside the sandbox, a report goes in on stdin and a summary
comes out on stdout. The score is unigram F1 against the reference summary (below: plain counting, no network).

Twenty reports: six the buyer kept back (held_out.json) and fourteen drawn fresh on every run. To be paid, a submission
must reach a mean F1 of at least MEAN, and at least SHARE of the reports must reach FLOOR on their own."""
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter

import gen

HERE = os.path.dirname(os.path.abspath(__file__))
MEAN, SHARE, FLOOR = 0.85, 0.90, 0.70
SECONDS = 3   # for one report


def words(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def f1(got: str, want: str) -> float:
    """Unigram F1: of the words in both (each counted as often as it is in both), precision and recall, together."""
    hit = sum((words(got) & words(want)).values())
    if not hit:
        return 0.0
    p, r = hit / sum(words(got).values()), hit / sum(words(want).values())
    return 2 * p * r / (p + r)


def summarise(report: str) -> str:
    try:
        got = subprocess.run([os.environ["KNOS_RUN"], "python3", "summarise.py"], input=report.encode("utf-8"),
                             capture_output=True, timeout=SECONDS)
    except subprocess.TimeoutExpired:
        sys.exit(f"summarise.py took more than {SECONDS} seconds on one report")
    if got.returncode:
        sys.exit(f"summarise.py stopped with status {got.returncode}: {got.stderr.decode('utf-8', 'replace')[-300:]}")
    try:
        return got.stdout.decode("utf-8")
    except UnicodeDecodeError:
        sys.exit("summarise.py wrote bytes that are not UTF-8")


with open(os.path.join(HERE, "held_out.json"), encoding="utf-8") as fh:
    cases = [(c["report"], c["reference"]) for c in json.load(fh)]
rng = random.Random(os.urandom(16))
for _ in range(14):
    f = gen.facts(rng)
    cases.append((gen.report(rng, f), gen.reference(f)))
scores = [f1(summarise(report), want) for report, want in cases]
mean, share = sum(scores) / len(scores), sum(s >= FLOOR for s in scores) / len(scores)
print(f"mean F1 {mean:.3f} (needs {MEAN}); {share:.0%} of reports at {FLOOR} or more (needs {SHARE:.0%})")
if mean < MEAN or share < SHARE:
    sys.exit(f"below the bar: mean F1 {mean:.3f}, {share:.0%} of reports at {FLOOR} or more")
