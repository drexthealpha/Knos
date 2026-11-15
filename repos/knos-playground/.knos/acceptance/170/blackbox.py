"""Black-box acceptance for issue 170, made by `knos accept init`. Read README.md.

This file runs as the judge, outside the pull request's tree, and never loads the pull request's code. It runs
"$KNOS_RUN <command>" (which runs the command in the pull request's tree, inside the sandbox) on every input in
cases.json, and compares what it prints with the answer recorded from the reference. Exit 0 means every case agrees."""
import json
import os
import subprocess
import sys
from pathlib import Path

SPEC = json.loads((Path(__file__).resolve().parent / "cases.json").read_text(encoding="utf-8"))
SECONDS = 60


def norm(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip("\n").split("\n"))


def ask(argv, stdin):
    got = subprocess.run([os.environ["KNOS_RUN"], *argv], input=stdin, capture_output=True, timeout=SECONDS)
    return got.returncode, got.stdout, got.stderr


def check(ask=ask):
    """None when every case agrees, else one sentence about the first that does not."""
    for n, case in enumerate(SPEC["cases"], 1):
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
    why = check()
    if why:
        sys.exit(why)
    print("all %d cases agree" % len(SPEC["cases"]))
