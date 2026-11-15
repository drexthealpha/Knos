"""Acceptance check for issue 24: slugify drops punctuation.

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


def reference(title: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", title.lower()))


rng = random.Random()
alphabet = string.ascii_letters + string.digits + "    ,.!?;:'\"()-"
titles = ["Hello, World!", "  a  --  b  ", "What's new?", "KNOS", "Top 10 Tips"]
titles += ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 30))) for _ in range(40)]
titles = [t for t in titles if reference(t)]

program = ("import json, sys\nfrom slug import slugify\n"
           "print(json.dumps([slugify(t) for t in json.loads(sys.argv[1])]))")
run = subprocess.run([os.environ["KNOS_RUN"], sys.executable, "-c", program, json.dumps(titles)],
                     capture_output=True, text=True, timeout=120)
try:
    got = json.loads(run.stdout.strip().splitlines()[-1])
except (IndexError, ValueError):
    print("the pull request's code printed no answer:", (run.stdout + run.stderr)[-500:])
    sys.exit(1)
wrong = [(t, g, reference(t)) for t, g in zip(titles, got) if g != reference(t)]
if len(got) != len(titles) or wrong:
    for t, g, want in wrong[:5]:
        print(f"slugify({t!r}) gave {g!r}, expected {want!r}")
    sys.exit(1)
print(f"{len(titles)} titles, all slugged as expected")
