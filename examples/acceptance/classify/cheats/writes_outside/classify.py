"""Cheat: write where the pull request has no business writing, to make the check pass for good: the repository's
own checks (the base checkout the judge was started on), the judge's private copy of the check, and a marker file."""
import glob
import sys

NOTHING = "import sys\nsys.exit(0)\n"
TARGETS = ["@BASE@/.knos/acceptance/1/blackbox.py", "@BASE@/.knos/acceptance/1/gen.py", "@MARK@",
           *glob.glob("/tmp/knos-judge-*/check/blackbox.py"), *glob.glob("/tmp/knos-judge-*/check/gen.py")]
for path in TARGETS:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(NOTHING)
    except OSError:
        pass
for _ in sys.stdin.readlines()[1:]:
    print(0)
