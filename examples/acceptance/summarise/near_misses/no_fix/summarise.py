"""Honest attempt that leaves out the last sentence: what fixed it."""
import re
import sys

text = " ".join(sys.stdin.read().split())


def find(*patterns: str) -> str:
    for p in patterns:
        if m := re.search(p, text):
            return m.group(1)
    raise SystemExit("this report does not say what TASK.md says every report says")


service = find(r"The (\S+) outage lasted", r"and the fix, (\S+) was unavailable", r"could not reach (\S+) for")
minutes = find(r"outage lasted (\d+) minutes", r"\((\d+) minutes in total\)", r"could not reach \S+ for (\d+) minutes")
cause = find(r"The root cause was ([^.]+)\.", r"showed that (.+?) had triggered", r"traced to ([^.]+)\.")
print(f"{service} was down for {minutes} minutes because of {cause}.")
