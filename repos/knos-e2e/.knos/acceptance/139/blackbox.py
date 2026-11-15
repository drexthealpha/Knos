"""Acceptance check for this issue: initials(name) gives the capital initials of a name.

Black-box: the pull request's code runs only as a separate process, through $KNOS_RUN, and only what it prints is
compared with a reference computed here. The inputs are generated afresh on every run, so no fixed example can be
special-cased.
"""
import json
import os
import random
import re
import string
import subprocess
import sys


def reference(name: str) -> str:
    return "".join(w[0].upper() for w in re.findall(r"[A-Za-z]+", name))


rng = random.Random()
alphabet = string.ascii_letters + "    -.'"
names = ["Ada Lovelace", "jean-luc picard", "  grace   hopper ", "O'Neil", "x"]
names += ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 30))) for _ in range(40)]

program = ("import json, sys\nfrom initials import initials\n"
           "print(json.dumps([initials(n) for n in json.loads(sys.argv[1])]))")
run = subprocess.run([os.environ["KNOS_RUN"], sys.executable, "-c", program, json.dumps(names)],
                     capture_output=True, text=True, timeout=120)
try:
    got = json.loads(run.stdout.strip().splitlines()[-1])
except (IndexError, ValueError):
    print("the pull request's code printed no answer:", (run.stdout + run.stderr)[-500:])
    sys.exit(1)
wrong = [(n, g, reference(n)) for n, g in zip(names, got) if g != reference(n)]
if len(got) != len(names) or wrong:
    for n, g, want in wrong[:5]:
        print(f"initials({n!r}) gave {g!r}, expected {want!r}")
    sys.exit(1)
print(f"{len(names)} names, all as expected")
