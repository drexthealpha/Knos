"""Try a solution before the pull request:  python3 check.py <task>

Runs tasks/<task>.py on the public examples of tasks/<task>.examples.json, one process for each, and compares what it
prints. The check that decides runs the same file on these and on inputs that are not here."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def norm(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip("\n").split("\n"))


def main(argv):
    names = sorted(p.name[:-len(".examples.json")] for p in (HERE / "tasks").glob("*.examples.json"))
    stem = argv[1].replace("-", "_") if len(argv) == 2 else ""
    if stem not in names:
        print("usage: python3 check.py <task>   one of: " + ", ".join(n.replace("_", "-") for n in names))
        return 2
    cases = json.loads((HERE / "tasks" / (stem + ".examples.json")).read_text(encoding="utf-8"))
    for n, case in enumerate(cases, 1):
        got = subprocess.run([sys.executable, str(HERE / "tasks" / (stem + ".py"))], input=(case["input"] + "\n").encode("utf-8"), capture_output=True, timeout=60)
        said = norm(got.stdout.decode("utf-8", "replace"))
        if got.returncode != 0 or said != case["output"]:
            print("example %d, the input %r: it printed %r, expected %r" % (n, case["input"], said, case["output"]))
            return 1
    print("all %d public examples agree. The check also runs inputs that are not here." % len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
