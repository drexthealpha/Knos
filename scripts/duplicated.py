"""What a refusal costs against what it prevents - measured, including the part that looks bad.

The other evidence here has a weakness worth naming. `spend.json` and
`contention.json` are simulations: twenty asks, sixty-nine attempts, agents
with invented reliabilities. Their ratios follow from numbers I chose, and a
reader is right to discount that. This measures real durations on the machine
it runs on and divides them.

The first version of this script measured one thing - a claim, end to end,
from a cold process - and reported that refusing costs 142 ms while reading
and parsing a real source file costs 7.5 ms. That is a ratio of nineteen to
one *against* the product, and it is published below rather than dropped,
because it is true and it is what a cold `knos` command costs.

Taking it apart is what makes it useful. Almost all of that is opening the
store; the compare-and-swap that actually refuses is well under a millisecond.
So the honest answer is three numbers and a break-even, not one number:

    a refusal, store already open      the coordination itself
    a refusal, store opened for it     what one MCP tool call really costs,
                                       because each one opens the store
    one file read and parsed           one unit of the work two agents both
                                       do when neither knows about the other

The break-even follows: below it, coordinating costs more than colliding. A
product that cannot say where its own break-even is has not been measured.

    python scripts/duplicated.py

Writes docs/evidence/duplicated.json. No network. Nothing is written down that
the run did not measure.
"""

from __future__ import annotations

import ast
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Enough files that one slow one cannot carry the median, few enough that the
# whole thing runs in the time a person will actually wait.
FILES = 24
TRIALS = 9


def work(path: Path) -> int:
    """One unit of the work an agent does: read a file and understand it.

    Deliberately the cheapest honest version. A real agent also sends the file
    to a model, which costs seconds and money this script cannot measure
    without a network - so every ratio below is a floor.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return len(text)
    return sum(1 for _ in ast.walk(tree))


# Run in its own process: what is timed is a cold agent reaching for work,
# not a warm function call in the harness that started it.
COLD = """
import json, sys, time
from knos.core import Claims
repo, who, topic = sys.argv[1], sys.argv[2], sys.argv[3]
started = time.perf_counter()
with Claims(repo=repo, who=who) as claims:
    took, holder = claims.take(topic)
print(json.dumps({"took": bool(took), "seconds": time.perf_counter() - started}))
"""


def _sources() -> list[Path]:
    """Real files of this repository, largest first so timing is not all noise."""
    found = sorted((ROOT / "src" / "knos").glob("*.py"))
    found += sorted((ROOT / "tests").glob("*.py"))
    return sorted(found, key=lambda p: -p.stat().st_size)[:FILES]


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    return repo


def _cold(repo: Path) -> list[float]:
    """A whole cold process: import done, then open the store and be refused.

    The path a `knos` command is on, and the number the first version of this
    script reported on its own.
    """
    from knos.core import Claims

    out = []
    for n in range(TRIALS):
        topic = f"cold {n}"
        with Claims(repo=str(repo), who="holder") as held:
            assert held.take(topic)[0], "the first process must get it"
        done = subprocess.run(
            [sys.executable, "-c", COLD, str(repo), "asker", topic],
            capture_output=True, text=True, cwd=ROOT,
        )
        got = json.loads(done.stdout)
        assert not got["took"], "the second must be refused, or this measures nothing"
        out.append(got["seconds"])
    return out


def _open_and_refuse(repo: Path) -> list[float]:
    """Opening the store and being refused, in a process that is already warm.

    This is what one MCP tool call costs today: every tool opens the store,
    does its work and closes it.
    """
    from knos.core import Claims

    out = []
    for n in range(TRIALS):
        topic = f"warm {n}"
        with Claims(repo=str(repo), who="holder") as held:
            assert held.take(topic)[0]
        started = time.perf_counter()
        with Claims(repo=str(repo), who="asker") as asker:
            took, _ = asker.take(topic)
        out.append(time.perf_counter() - started)
        assert not took
    return out


def _refuse_only(repo: Path) -> list[float]:
    """The compare-and-swap itself, with the store already open."""
    from knos.core import Claims

    out = []
    with Claims(repo=str(repo), who="holder") as held:
        for n in range(TRIALS):
            assert held.take(f"cas {n}")[0]
    with Claims(repo=str(repo), who="asker") as asker:
        for n in range(TRIALS):
            started = time.perf_counter()
            took, _ = asker.take(f"cas {n}")
            out.append(time.perf_counter() - started)
            assert not took
    return out


def main() -> None:
    paths = _sources()
    work_seconds = [
        _timed(path) for path in paths
    ]
    with tempfile.TemporaryDirectory() as raw:
        repo = _repo(Path(raw))
        cold = statistics.median(_cold(repo))
        per_call = statistics.median(_open_and_refuse(repo))
        cas = statistics.median(_refuse_only(repo))

    one_file = statistics.median(work_seconds)
    got = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "files_parsed": len(paths),
        "trials": TRIALS,
        "seconds": {
            "one_file_read_and_parsed": round(one_file, 6),
            "refusal_store_already_open": round(cas, 6),
            "refusal_including_opening_the_store": round(per_call, 6),
            "refusal_from_a_cold_process": round(cold, 6),
        },
        "times_cheaper_to_refuse_than_to_duplicate_one_file": round(one_file / cas, 1),
        "files_of_duplicated_work_to_break_even": {
            "per_mcp_tool_call": round(per_call / one_file, 1),
            "per_cold_command": round(cold / one_file, 1),
        },
        "what_this_does_not_say": (
            "That a collision is worth preventing. It says what one costs to "
            "prevent. The work measured is a read and a parse; a real agent "
            "also sends the file to a model, which costs seconds and money "
            "this script cannot measure without a network - so these are "
            "floors, and the break-evens are ceilings."
        ),
        "where_the_time_goes": (
            "Opening the store, not coordinating. The compare-and-swap is "
            "well under a millisecond; every MCP tool opens the store, does "
            "its work and closes it, which is where the rest of the call goes."
        ),
    }
    out = ROOT / "docs" / "evidence" / "duplicated.json"
    out.write_text(json.dumps(got, indent=2) + "\n", encoding="utf-8")
    _refresh_guide(got)
    print(json.dumps(got, indent=2))


# The judge guide prints these durations, so somebody reading it offline is not
# sent to a JSON file to find out what the product costs. That makes them a
# quotation, and a quotation its source has moved on from is the fault this
# repo spent the morning taking out of its own answers. So the script that
# measures them is the thing that rewrites them.
FENCE = "<!-- measured: docs/evidence/duplicated.json -->"
END = "<!-- /measured -->"


def _refresh_guide(got: dict) -> None:
    guide = ROOT / "docs" / "JUDGE_GUIDE.md"
    said = guide.read_text(encoding="utf-8")
    if FENCE not in said:
        return
    s = got["seconds"]
    table = "\n".join([
        FENCE,
        "",
        "| | measured |",
        "|---|---|",
        "| the compare-and-swap that refuses a claim "
        f"| {s['refusal_store_already_open'] * 1000:.2f} ms |",
        "| one MCP tool call, which opens the store and closes it "
        f"| {s['refusal_including_opening_the_store'] * 1000:.1f} ms |",
        "| a cold `knos` command, the slowest path here "
        f"| {s['refusal_from_a_cold_process'] * 1000:.0f} ms |",
        "| one real source file of this repo, read and parsed "
        f"| {s['one_file_read_and_parsed'] * 1000:.1f} ms |",
        "",
    ])
    said = said[:said.index(FENCE)] + table + said[said.index(END):]

    # The two break-evens are quoted in the sentence under the table.
    even = got["files_of_duplicated_work_to_break_even"]
    said = re.sub(r"prevents \*\*[\d.]+\*\* files",
                  f"prevents **{even['per_mcp_tool_call']}** files", said, count=1)
    said = re.sub(r"cold command at \*\*[\d.]+\*\*",
                  f"cold command at **{even['per_cold_command']}**", said, count=1)

    guide.write_text(said, encoding="utf-8", newline="\n")


def _timed(path: Path) -> float:
    started = time.perf_counter()
    work(path)
    return time.perf_counter() - started


if __name__ == "__main__":
    main()
