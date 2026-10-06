"""Where the test suite's time goes, from what pytest already writes.

    python scripts/suite_time.py junit/*.xml                 a table of each shard, and the 20 slowest tests
    python scripts/suite_time.py --limit 300 junit/          the same, and exit 1 if a shard ran over 300 seconds
    python scripts/suite_time.py --markdown junit/           as Markdown (tests.yml writes it to the job summary)
    python scripts/suite_time.py --slow junit/               the test ids over 5 seconds (--over N), as tests/slow.txt lists them
    pytest --durations=0 tests/test_x.py | python scripts/suite_time.py -

A shard is one file: a JUnit XML file (`pytest --junitxml=...`), or the text of a run with `--durations`. A folder
stands for every .xml file in it. The time of a shard is the wall time pytest recorded for the session (with
pytest-xdist that is less than the sum of its tests, which is printed beside it); the rule is that no shard takes more
than five minutes (.github/workflows/tests.yml fails the job that does). A test's time is its setup, call and teardown
together. Reads files only; standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

LIMIT = 300.0   # seconds: the five-minute rule
SLOW = 5.0      # seconds: over this a test belongs in tests/slow.txt

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s+(setup|call|teardown)\s+(\S.*?)\s*$")
_TOTAL = re.compile(r"\bin (\d+(?:\.\d+)?)s\b(?: \(\d+:\d\d:\d\d\))?\s*=*\s*$")


@dataclass
class Shard:
    name: str
    wall: float | None = None                                   # what pytest says the session took; None: not recorded
    tests: dict[str, float] = field(default_factory=dict)       # test id -> seconds
    failed: int = 0
    skipped: int = 0

    @property
    def total(self) -> float:
        return sum(self.tests.values())

    @property
    def seconds(self) -> float:
        """What the rule is checked against: the session's wall time, or the sum of the tests when none was recorded."""
        return self.total if self.wall is None else self.wall


def node_id(classname: str, name: str, root: Path) -> str:
    """The id pytest prints, from a JUnit test case: `tests.test_x.TestY` and `test_z[1]` are
    tests/test_x.py::TestY::test_z[1]. The file is the longest start of the class name that is a file under `root`;
    with no such file (the run was elsewhere) every part but those that begin with a capital is taken as the path."""
    parts = classname.split(".") if classname else []
    cut = next((i for i in range(len(parts), 0, -1) if (root.joinpath(*parts[:i])).with_suffix(".py").is_file()), None)
    if cut is None:
        cut = next((i for i, part in enumerate(parts) if part[:1].isupper()), len(parts))
    path = "/".join(parts[:cut]) + ".py" if cut else ""
    return "::".join([p for p in [path, *parts[cut:], name] if p])


def read_junit(path: Path, root: Path) -> Shard:
    tree = ET.parse(path).getroot()
    suites = [tree] if tree.tag == "testsuite" else list(tree.iter("testsuite"))
    shard = Shard(path.stem)
    walls = [float(s.get("time") or 0) for s in suites if s.get("time")]
    shard.wall = sum(walls) if walls else None
    for case in tree.iter("testcase"):
        tid = node_id(case.get("classname", ""), case.get("name", ""), root)
        shard.tests[tid] = shard.tests.get(tid, 0.0) + float(case.get("time") or 0)
        shard.failed += any(child.tag in ("failure", "error") for child in case)
        shard.skipped += any(child.tag == "skipped" for child in case)
    return shard


def read_durations(text: str, name: str) -> Shard:
    """The lines `1.66s call tests/test_x.py::test_y` of `pytest --durations=N`, and the last line's `in 19.42s`.
    pytest leaves out what took under 0.005 s (unless -vv) and what is past N, so the sum is of what it printed."""
    shard = Shard(name)
    for line in text.splitlines():
        m = _DURATION.match(line)
        if m:
            shard.tests[m[3]] = shard.tests.get(m[3], 0.0) + float(m[1])
            continue
        m = _TOTAL.search(line)
        if m and re.search(r"\b(passed|failed|error|errors|skipped|deselected|no tests ran)\b", line):
            shard.wall = float(m[1])
            found = re.search(r"(\d+) failed", line), re.search(r"(\d+) errors?", line), re.search(r"(\d+) skipped", line)
            shard.failed = sum(int(f[1]) for f in found[:2] if f)
            shard.skipped = int(found[2][1]) if found[2] else 0
    return shard


def read(paths: list[str], root: Path) -> list[Shard]:
    shards: list[Shard] = []
    for given in paths:
        if given == "-":
            shards.append(read_durations(sys.stdin.read(), "stdin"))
            continue
        path = Path(given)
        if path.is_dir():
            files = sorted(path.rglob("*.xml"))
            if not files:
                raise SystemExit(f"{given}: no .xml file in this folder")
        elif path.is_file():
            files = [path]
        else:
            raise SystemExit(f"{given}: no such file or folder")
        for file in files:
            text = file.read_text(encoding="utf-8", errors="replace")
            shards.append(read_junit(file, root) if text.lstrip().startswith("<") else read_durations(text, file.stem))
    return shards


def clock(seconds: float) -> str:
    return f"{int(seconds // 60)}m{seconds % 60:04.1f}s"


def slowest(shards: list[Shard], count: int) -> list[tuple[float, str, str]]:
    rows = [(seconds, tid, shard.name) for shard in shards for tid, seconds in shard.tests.items()]
    return sorted(rows, key=lambda row: (-row[0], row[1], row[2]))[:count]


def over(shards: list[Shard], limit: float) -> list[Shard]:
    return [shard for shard in shards if shard.seconds > limit]


def slow_ids(shards: list[Shard], threshold: float = SLOW) -> list[str]:
    """Every test that took over `threshold` seconds in any shard given (the same test runs on each platform)."""
    worst: dict[str, float] = {}
    for shard in shards:
        for tid, seconds in shard.tests.items():
            worst[tid] = max(worst.get(tid, 0.0), seconds)
    return sorted(tid for tid, seconds in worst.items() if seconds > threshold)


def unlisted(shards: list[Shard], root: Path, threshold: float = SLOW) -> list[str]:
    """The tests over `threshold` seconds that tests/slow.txt does not list (as tests/conftest.py reads it: a line is
    a whole id, a test without its parameters, or a file)."""
    file = root / "tests" / "slow.txt"
    lines = file.read_text(encoding="utf-8").splitlines() if file.is_file() else []
    listed = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return [tid for tid in slow_ids(shards, threshold)
            if not any(tid == s or (tid.startswith(s) and tid[len(s)] in ":[") for s in listed)]


def table(shards: list[Shard], limit: float, top: int, markdown: bool) -> str:
    head = ["shard", "tests", "failed", "skipped", "wall time", "sum of tests", f"limit {clock(limit)}"]
    rows = [[s.name, str(len(s.tests)), str(s.failed), str(s.skipped), "not recorded" if s.wall is None else clock(s.wall),
             clock(s.total), "OVER" if s.seconds > limit else "ok"] for s in shards]
    slow = [[f"{seconds:.2f}s", shard, tid] for seconds, tid, shard in slowest(shards, top)]
    if markdown:
        def md(header: list[str], body: list[list[str]]) -> list[str]:
            return ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header), *("| " + " | ".join(r) + " |" for r in body)]
        out = ["### Suite time", "", *md(head, rows), "", f"### The {len(slow)} slowest tests", "",
               *md(["time", "shard", "test"], [[t, s, f"`{tid}`"] for t, s, tid in slow])]
    else:
        widths = [max(len(r[i]) for r in [head, *rows]) for i in range(len(head))]
        out = ["  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in [head, *rows]]
        out += ["", f"the {len(slow)} slowest tests"]
        width = max((len(s) for _, s, _ in slow), default=0)
        out += [f"{t:>9}  {s.ljust(width)}  {tid}" for t, s, tid in slow]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Per-shard times and the slowest tests, from JUnit XML or `pytest --durations` output.")
    ap.add_argument("paths", nargs="+", help="JUnit XML files, files of --durations output, folders of .xml files, or - for stdin")
    ap.add_argument("--limit", type=float, default=None, metavar="SECONDS",
                    help=f"exit 1 if a shard took longer (the rule is {LIMIT:.0f}); without it nothing fails")
    ap.add_argument("--top", type=int, default=20, help="how many of the slowest tests to print (20)")
    ap.add_argument("--markdown", action="store_true", help="print Markdown tables (for a job summary)")
    ap.add_argument("--slow", action="store_true", help="print only the ids of the slow tests, one a line, as tests/slow.txt lists them")
    ap.add_argument("--over", type=float, default=SLOW, metavar="SECONDS", help=f"what --slow calls slow: over this many seconds ({SLOW:.0f})")
    ap.add_argument("--root", default=".", help="the repository the tests ran in (to turn a JUnit class name into a file): .")
    args = ap.parse_args(argv)
    shards = read(args.paths, Path(args.root))
    if args.slow:
        print("\n".join(slow_ids(shards, args.over)))
        return 0
    print(table(shards, LIMIT if args.limit is None else args.limit, args.top, args.markdown))
    new = unlisted(shards, Path(args.root), args.over)
    if new:
        tick = "`" if args.markdown else ""
        print(f"\nover {args.over:g} seconds and not in tests/slow.txt ({len(new)}): add them, so `pytest -m \"not slow\"` stays quick\n")
        print("\n".join(f"{'- ' if args.markdown else '  '}{tick}{tid}{tick}" for tid in new))
    late = over(shards, args.limit) if args.limit is not None else []
    for shard in late:
        print(f"\n{shard.name} took {clock(shard.seconds)}: over the limit of {clock(args.limit)}. Split it (one more shard in "
              ".github/workflows/tests.yml) or make its slowest tests faster.", file=sys.stderr)
    return 1 if late else 0


if __name__ == "__main__":
    sys.exit(main())
