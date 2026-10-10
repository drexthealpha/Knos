"""Count what docs/DISCLOSURE.md states about the repository's history, at one commit.

Usage: python scripts/disclosure_counts.py [--repo PATH] [--commit SHA] [--json]

It needs a FULL clone (a shallow one cannot see the commits before the contest period). It prints the number of
commits up to the commit, how many predate 13:00 UTC on 14 Sep 2026, and, over every text file at the commit, how
many lines `git blame` attributes to commits made before that moment, with the files that hold them.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

START = 1789390800  # 2026-09-14T13:00:00Z: 06:00 Pacific time, the contest period begins
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return out.stdout.decode("utf-8", "replace")


def text_files(repo: Path, commit: str) -> list[str]:
    files = []
    for line in git(repo, "diff", "--numstat", EMPTY_TREE, commit).splitlines():
        added, _, name = line.split("\t", 2)
        if added != "-":
            files.append(name)
    return files


def blame_old(repo: Path, commit: str, name: str) -> tuple[int, int]:
    total = old = 0
    for line in git(repo, "blame", "--line-porcelain", commit, "--", name).splitlines():
        if line.startswith("author-time "):
            total += 1
            old += int(line.split()[1]) < START
    return total, old


def counts(repo: Path, commit: str) -> dict:
    times = [int(t) for t in git(repo, "log", commit, "--format=%at").split()]
    by_file: Counter[str] = Counter()
    total = 0
    files = text_files(repo, commit)
    for name in files:
        n, o = blame_old(repo, commit, name)
        total += n
        if o:
            by_file[name] = o
    old = sum(by_file.values())
    return {
        "commit": git(repo, "rev-parse", commit).strip(),
        "commits": len(times),
        "commits_before": sum(t < START for t in times),
        "text_files": len(files),
        "lines": total,
        "lines_before": old,
        "share_before": round(old / total, 4) if total else 0.0,
        "files_before": dict(by_file.most_common()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    if git(repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        print("a shallow clone cannot count the commits before the contest period: clone in full", file=sys.stderr)
        return 2
    c = counts(repo, a.commit)
    if a.json:
        print(json.dumps(c, indent=1))
        return 0
    print(f"{c['commits']} commits up to {c['commit'][:7]}, {c['commits_before']} before the contest period")
    print(f"{c['lines_before']} of {c['lines']} lines in {c['text_files']} text files predate it ({c['share_before']:.1%})")
    for name, n in c["files_before"].items():
        print(f"{n:6d} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
