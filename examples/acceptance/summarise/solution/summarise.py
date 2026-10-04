"""Read an incident report on stdin, print its one-line summary on stdout (the format is in TASK.md)."""
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
fix = find(r"Engineers (.+?) and traffic recovered", r"after the team ([^.]+)\.", r"The fix: the team ([^.]+)\.")
sys.stdout.reconfigure(encoding="utf-8", newline="\n")    # the line ends in \n on every system, as in the example
print(f"{service} was down for {minutes} minutes because of {cause}. The team {fix}.")
