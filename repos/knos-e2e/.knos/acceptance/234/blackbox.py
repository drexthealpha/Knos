"""Acceptance check for this issue: vowels(text) counts a, e, i, o, u in a text, upper or lower case.

Black-box: the pull request's code runs only as a separate process, through $KNOS_RUN, and only what it prints is
compared with a reference computed here, on inputs generated afresh on every run.
"""
import json
import os
import random
import string
import subprocess
import sys


def reference(text: str) -> int:
    return sum(1 for ch in text if ch in "aeiouAEIOU")


rng = random.Random()
alphabet = string.ascii_letters + string.digits + "  ,.-'!\tyY"
texts = ["Knos", "AEIOU aeiou", "", "rhythm", "yYy"]
texts += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40))) for _ in range(40)]

program = ("import json, sys\nfrom vowels import vowels\n"
           "print(json.dumps([vowels(t) for t in json.loads(sys.argv[1])]))")
run = subprocess.run([os.environ["KNOS_RUN"], sys.executable, "-c", program, json.dumps(texts)],
                     capture_output=True, text=True, timeout=120)
try:
    got = json.loads(run.stdout.strip().splitlines()[-1])
except (IndexError, ValueError):
    print("the pull request's code printed no answer:", (run.stdout + run.stderr)[-500:])
    sys.exit(1)
wrong = [(t, g, reference(t)) for t, g in zip(texts, got) if g != reference(t)]
if len(got) != len(texts) or wrong:
    for t, g, want in wrong[:5]:
        print(f"vowels({t!r}) gave {g!r}, expected {want!r}")
    sys.exit(1)
print(f"{len(texts)} texts, all as expected")
