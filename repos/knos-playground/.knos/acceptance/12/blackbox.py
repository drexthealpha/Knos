"""Black-box acceptance for issue 12: the task "weekday" of the Knos playground. Read README.md.

This file runs as the judge, outside the pull request's tree, and never loads the pull request's code. It runs
"$KNOS_RUN <command>" (which runs the command in the pull request's tree, inside the sandbox) on every recorded input
of cases.json, then on inputs gen.py makes from a seed drawn when this runs, and compares what the command prints with
what reference.py answers. Exit 0 means every case agrees."""
import importlib.util
import json
import os
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
SECONDS = 60
sys.dont_write_bytecode = True


def part(name):
    spec = importlib.util.spec_from_file_location("knos_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def norm(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip("\n").split("\n"))


def ask(argv, stdin):
    got = subprocess.run([os.environ["KNOS_RUN"], *argv], input=stdin, capture_output=True, timeout=SECONDS)
    return got.returncode, got.stdout, got.stderr


def fresh(seed):
    """Cases nobody has seen: the generator's inputs at this seed, answered by the reference now."""
    solve, known = part("reference").solve, {c["input"] for c in SPEC["cases"]}
    return [{"input": line, "output": norm(solve(line + "\n"))} for line in dict.fromkeys(part("gen").inputs(random.Random(seed))) if line not in known]


def check(ask=ask, seed=None):
    """None when every case agrees, else one sentence about the first that does not. `seed` None: the recorded cases only."""
    for n, case in enumerate(SPEC["cases"] + (fresh(seed) if seed is not None else []), 1):
        at = "case %d, the input %s" % (n, repr(case["input"][:60]))
        try:
            code, out, err = ask(SPEC["run"], (case["input"] + "\n").encode("utf-8"))
        except subprocess.TimeoutExpired:
            return "%s: the command took more than %d seconds" % (at, SECONDS)
        if code != 0:
            return "%s: the command exited %d: %s" % (at, code, " ".join(err.decode("utf-8", "replace").split())[-200:] or "it said nothing")
        got = norm(out.decode("utf-8", "replace"))
        if got != case["output"]:
            return "%s: it printed %s, expected %s" % (at, repr(got[:80]), repr(case["output"][:80]))
    return None


if __name__ == "__main__":
    seed = int.from_bytes(os.urandom(8), "big")
    why = check(seed=seed)
    if why:
        sys.exit("%s (fresh inputs: seed %d)" % (why, seed))
    print("every recorded case and every fresh one (seed %d) agrees" % seed)
