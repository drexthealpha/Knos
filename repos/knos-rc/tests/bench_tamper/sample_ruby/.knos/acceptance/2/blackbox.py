"""Issue 1 again, as a black-box check: slugify must drop punctuation.

This file runs as the judge, outside the pull request's tree, and never loads the pull request's code. It asks that
code for answers through "$KNOS_RUN <command>" (which runs the command in the tree, inside the sandbox) and compares
them with its own reference, on two fixed inputs and twenty generated ones. So a pull request cannot pass by patching
minitest (it is not in this process, nor in the one that answers), nor by returning constants for inputs it has seen."""
import json
import os
import random
import re
import subprocess
import sys


def want(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


rng = random.Random(os.urandom(8))
cases = ["Hello, World!", "  Rock & Roll -- 2  "]
cases += ["".join(rng.choice("abc XYZ,.!&-_09") for _ in range(rng.randint(1, 24))) for _ in range(20)]
ask = 'require "slug"; puts "KNOS" + JSON.generate(JSON.parse(STDIN.read).map { |s| Slug.slugify(s) })'
got = subprocess.run([os.environ["KNOS_RUN"], "ruby", "-Ilib", "-rjson", "-e", ask], input=json.dumps(cases).encode(),
                     capture_output=True, timeout=120)
lines = [x for x in got.stdout.decode("utf-8", "replace").splitlines() if x.startswith("KNOS")]
try:
    answers = json.loads(lines[-1][4:])
except (IndexError, ValueError):
    sys.exit(f"no answer from the pull request's code: {got.stderr.decode('utf-8', 'replace')[-300:]}")
bad = [(c, a) for c, a in zip(cases, answers) if a != want(c)]
if bad or len(answers) != len(cases):
    sys.exit(f"slugify({bad[0][0]!r}) returned {bad[0][1]!r}, expected {want(bad[0][0])!r}" if bad else "answers missing")
