"""Acceptance check for this issue: wordcount(phrase) counts the runs of letters or digits in a phrase.

Black-box: the pull request's code runs only as a separate process, through $KNOS_RUN, and only what it prints is
compared with a reference computed here, on inputs generated afresh on every run.
"""
import json
import os
import random
import re
import string
import subprocess
import sys


def reference(phrase: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", phrase))


rng = random.Random()
alphabet = string.ascii_letters + string.digits + "  ,.-'!\t"
phrases = ["one, two-three  4", "", "   ", "x"]
phrases += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40))) for _ in range(40)]

program = ("import json, sys\nfrom wordcount import wordcount\n"
           "print(json.dumps([wordcount(p) for p in json.loads(sys.argv[1])]))")
run = subprocess.run([os.environ["KNOS_RUN"], sys.executable, "-c", program, json.dumps(phrases)],
                     capture_output=True, text=True, timeout=120)
try:
    got = json.loads(run.stdout.strip().splitlines()[-1])
except (IndexError, ValueError):
    print("the pull request's code printed no answer:", (run.stdout + run.stderr)[-500:])
    sys.exit(1)
wrong = [(p, g, reference(p)) for p, g in zip(phrases, got) if g != reference(p)]
if len(got) != len(phrases) or wrong:
    for p, g, want in wrong[:5]:
        print(f"wordcount({p!r}) gave {g!r}, expected {want!r}")
    sys.exit(1)
print(f"{len(phrases)} phrases, all as expected")
