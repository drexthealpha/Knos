"""The instruction files agents actually live in.

A study of 557 agent sessions found that most of what a coding agent does
with documentation happens in `CLAUDE.md`, `AGENTS.md` and their own notes,
not in classical docs. Those are also the files that go stale, get copied
three times, and get rewritten by the agents themselves.

So knos reads them as a source like any other, and answers about them with a
file and a line, which is the part a person can go and check.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from . import code

# The names in common use. Anything else is somebody's private convention,
# and guessing at it would put files in the store nobody asked for.
NAMES = ("CLAUDE.md", "AGENTS.md")

# Two reviewers said the same thing in different words: they keep decisions
# and worklogs beside the code, in the repo, on purpose. Knos read the
# instruction files and ignored exactly the files those people had chosen to
# write. These are conventions with names, not guesses: a decision record is
# an ADR or a DECISIONS file, and it is short.
DECISIONS = (
    # What `knos export` writes and a repo commits. Listed here so a second
    # clone reads a teammate's decisions on its first question, with no
    # import step and nothing to configure.
    ".knos/decisions.md",
    "DECISIONS.md",
    "DECISIONS.MD",
    "WORKLOG.md",
    "docs/adr/*.md",
    "docs/decisions/*.md",
    "adr/*.md",
    "doc/adr/*.md",
    ".adr/*.md",
)

# Every pattern handed to `git ls-files`, at the root and at any depth.
PATTERNS = (
    *NAMES,
    *(f"*/{n}" for n in NAMES),
    *DECISIONS,
    *(f"*/{d}" for d in DECISIONS),
)

# A rule is a short thing. Past this a block is prose, and the file and line
# still say where the rest of it is.
KEEP = 400


class Rule:
    """One block of an instruction file, and where it starts."""

    __slots__ = ("text", "where", "path", "when")

    def __init__(self, text: str, where: str, path: str, when: str) -> None:
        self.text = text
        self.where = where
        self.path = path
        self.when = when


def files(repo: Path) -> list[Path]:
    """Every instruction file the repo itself keeps, outermost first.

    Only files git tracks. A vendored dependency ships its own `CLAUDE.md`
    written for its own maintainers, and quoting that as the rule here would
    be a lie with a file and a line attached. The repo's `.gitignore` has
    already drawn that line, so knos uses the answer rather than guessing at
    it again.
    """
    repo = Path(repo).resolve()
    # Asked of git by name. Listing every tracked file and filtering in
    # Python meant 80,000 paths built to find two, which was nine seconds on
    # the kernel.
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--", *PATTERNS],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        done = None
    if done is None or done.returncode != 0:
        # Not a git repo, or git is not installed. The root is the only
        # place knos can be sure the rules belong to this repo.
        found = [repo / n for n in NAMES if (repo / n).is_file()]
        for pattern in DECISIONS:
            found += [f for f in repo.glob(pattern) if f.is_file()]
        return found
    found = [repo / rel for rel in done.stdout.split("\0") if rel]
    return sorted(found, key=lambda p: len(p.parts))


def read(repo: Path) -> list[Rule]:
    """The rules written down in this repo, in order, with their lines."""
    repo = Path(repo).resolve()
    out: list[Rule] = []
    for f in files(repo):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            when = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        except OSError:
            continue
        rel = f.relative_to(repo).as_posix()
        for block, line in _blocks(text):
            out.append(Rule(text=block[:KEEP], where=f"{rel}:{line}", path=rel, when=when))
    return out


def _blocks(text: str) -> list[tuple[str, int]]:
    """Paragraphs, with the line each one starts on.

    A heading is kept with what follows it, because "## Testing" on its own
    answers nothing and the rule under it is what somebody asked for.
    """
    blocks: list[tuple[str, int]] = []
    buf: list[str] = []
    start = 1
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip():
            if buf:
                blocks.append(("\n".join(buf).strip(), start))
                buf = []
            continue
        if not buf:
            start = n
        buf.append(line)
    if buf:
        blocks.append(("\n".join(buf).strip(), start))
    # A heading on its own answers nothing: "## Testing" is not a rule, and
    # quoting it as one wastes the first line of an answer.
    return [
        (b, n)
        for b, n in blocks
        if len(b) > 12 and not (b.startswith("#") and len(b.splitlines()) == 1)
    ]
