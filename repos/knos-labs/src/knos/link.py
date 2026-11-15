"""One hop, from a decision to the file it changed.

This is not a graph engine. It answers one shape of question that grep
cannot: something was decided in a session, and the file it landed in is
named in a commit, so the answer needs both and neither alone will do.

The link is the file path. A session says "we moved the retry logic into
the client"; a commit says which file changed and when. Where a session
mentions a path a commit also touched, the two are the same story, and knos
says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import git, private
from .answer import Passage

# A path as a person types it in conversation: at least one slash or a
# recognisable extension, no spaces.
PATH_LIKE = re.compile(r"[A-Za-z0-9_.\-/\\]*[/\\][A-Za-z0-9_.\-/\\]+|[A-Za-z0-9_\-]+\.[a-z]{1,4}\b")


def _short(text: str, keep: int = 260) -> str:
    text = " ".join(text.split())
    return text if len(text) <= keep else text[:keep].rsplit(" ", 1)[0] + "..."


@dataclass(frozen=True)
class TwoHop:
    """A decision, the change it caused, and the file that joins them."""

    file: str
    decision: Passage
    change: Passage

    @property
    def text(self) -> str:
        return (
            f"{_short(self.decision.text)}\n"
            f"    and {self.file} changed: {_short(self.change.text)}"
        )

    @property
    def where(self) -> str:
        return f"{self.decision.where}, then {self.change.where}"


def paths_in(text: str, repo: Path) -> set[str]:
    """File paths a passage mentions, minus anything private."""
    found = set()
    for raw in PATH_LIKE.findall(text):
        candidate = raw.replace("\\", "/").strip("./")
        if not candidate or candidate.count("/") > 6:
            continue
        if private.is_private(repo, candidate):
            continue
        found.add(candidate)
    return found


def _same_file(mentioned: str, touched: str) -> bool:
    """A session names a file loosely; a commit names it exactly."""
    mentioned, touched = mentioned.lower(), touched.lower()
    if mentioned == touched:
        return True
    return touched.endswith("/" + mentioned) or mentioned.endswith("/" + touched)


def cross(repo: Path, passages: list[Passage], limit: int = 3) -> list[TwoHop]:
    """Join sessions to commits through the files they both name.

    Only the commits already in the answer are considered, so this costs one
    pass over what was found and never goes back to disk.
    """
    repo = Path(repo)
    sessions = [p for p in passages if p.source == "session"]
    changes = [p for p in passages if p.source == "git"]
    if not sessions or not changes:
        return []

    touched: dict[str, Passage] = {}
    for commit in git.read_commits(repo, limit=500):
        change = next((c for c in changes if commit.short in c.where), None)
        if change is None:
            continue
        for f in commit.files:
            if not private.is_private(repo, f):
                touched.setdefault(f, change)
    if not touched:
        return []

    out: list[TwoHop] = []
    told: set[str] = set()
    for decision in sessions:
        if decision.text in told:
            continue
        for mentioned in paths_in(decision.text, repo):
            match = next(
                ((f, c) for f, c in touched.items() if _same_file(mentioned, f)), None
            )
            if match is None:
                continue
            # One decision is one story, however many files it touched.
            told.add(decision.text)
            out.append(TwoHop(file=match[0], decision=decision, change=match[1]))
            break
        if len(out) >= limit:
            break
    return out
