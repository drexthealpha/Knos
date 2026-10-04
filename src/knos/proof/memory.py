"""The judge's memory between runs on GitHub, without the Actions cache: an issue labelled `knos-memory`.

Sibyl's store is still the only engine. A run loads the issue's lessons into Sibyl's local store (`pull`), judges
from that store, and a run in the base repository's own context posts what the store has that the issue does not
(`push`): one comment per run, the lessons as JSON lines in a code fence, under a marker line. Take Sibyl away and
the comments are only text: nothing here decides anything from them.

Only what GitHub Actions itself wrote is read: an issue opened by `github-actions[bot]` (user id 41898282), and in
it the comments by that account that were never edited. Anyone can comment on an issue, and anyone with write access
can edit a comment; neither can write a lesson. Closing the issue makes Knos forget: the next run opens a new one.

`get(path)` and `post(path, payload)` are knos.judge.github.
"""

from __future__ import annotations

import json

from ..terms import pages
from . import history

LABEL = "knos-memory"
BOT = (41898282, "github-actions[bot]")
MARK = "<!-- knos-memory 1 -->"      # the first line of a comment that holds lessons
_TITLE = "Knos memory"
_ABOUT = ("Knos keeps here what its judge learned from pull requests to this repository: one comment per run, written "
          "by GitHub Actions and read at the start of every later run. Comments by anyone else, and edited comments, "
          "are ignored. Close this issue to make Knos forget.")
_ROOM = 60_000                       # a comment holds 65536 characters


def _ours(item) -> bool:
    user = item.get("user") if isinstance(item, dict) else None
    return isinstance(user, dict) and user.get("id") == BOT[0] and user.get("login") == BOT[1]


def issues(repo: str, get) -> list[int]:
    """The repository's memory: its open issues labelled `knos-memory` that GitHub Actions opened, oldest first
    (one, unless two runs opened theirs at the same moment). Raises when GitHub does not answer."""
    found = get(f"repos/{repo}/issues?labels={LABEL}&state=open&sort=created&direction=asc&per_page=100")
    return [int(it["number"]) for it in found or [] if _ours(it) and "pull_request" not in it][:5]


def lessons_in(body: str) -> list[dict]:
    """The lessons one comment holds: its first line is the marker, and they are the lines of its code fence."""
    lines = (body or "").splitlines()
    if not lines or lines[0].strip() != MARK:
        return []
    out, inside = [], False
    for line in lines[1:]:
        if line.startswith("```"):
            if inside:
                break
            inside = True
        elif inside:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return [x for x in out if history.lesson(x)]


def comment(lessons: list[dict], run: str = "") -> str:
    """The comment that holds these lessons."""
    where = f" in run {run}" if run else ""
    return (f"{MARK}\nWhat Knos's judge learned{where}. Later runs read it; an edited comment is ignored.\n\n```json\n"
            + history.export_lessons(lessons) + "```\n")


def read(repo: str, get) -> tuple[int | None, list[dict] | None]:
    """(the issue new lessons go to, every lesson the repository's memory holds). The lessons are None when GitHub
    could not be read, and empty, with no issue, when the repository has no memory yet."""
    try:
        numbers = issues(repo, get)
    except Exception:  # noqa: BLE001 - GitHub did not answer
        return None, None
    out: list[dict] = []
    for n in numbers:
        comments = pages(f"repos/{repo}/issues/{n}/comments", get, cap=50)
        if comments is None:
            return numbers[0], None
        out += [x for c in comments if _ours(c) and c.get("created_at") and c.get("created_at") == c.get("updated_at")
                for x in lessons_in(c.get("body") or "")]
    return (numbers[0] if numbers else None), out


def pull(repo: str, store, get) -> int | None:
    """Load the repository's lessons into the store; how many there were. None when GitHub could not be read.
    Loading them again changes nothing: each lesson is kept under its own name."""
    _n, found = read(repo, get)
    return None if found is None else history.import_lessons(store, found)


def push(repo: str, store, get, post, run: str = "") -> int | None:
    """Post the lessons the store holds and the issue does not: one comment (more only when they do not fit in
    one), in an issue it opens when the repository has none. Returns how many lessons were posted; None, with
    nothing posted, when GitHub could not be read.

    The issue is append-only: a lesson is never edited, only posted again. So a settlement the store knows was paid
    is posted even when the issue has the same lesson saying "not paid" (another run settled the same pull request
    at the same moment and refused it), and every run reads the paid one as final (history.import_lessons)."""
    n, there = read(repo, get)
    if there is None:
        return None
    have, paid = {(x["category"], x["name"]) for x in there}, history.paid_settlements(there)
    new = [x for x in history.lessons(store) if (x["category"], x["name"]) not in have
           or (x["category"] == "settlement" and x["body"]["paid"] is True and x["name"] not in paid)]
    if not new:
        return 0
    if n is None:
        n = int(post(f"repos/{repo}/issues", {"title": _TITLE, "body": _ABOUT, "labels": [LABEL]})["number"])
    batch: list[dict] = []
    for x in [*new, None]:
        if batch and (x is None or len(comment([*batch, x], run)) > _ROOM):
            post(f"repos/{repo}/issues/{n}/comments", {"body": comment(batch, run)})
            batch = []
        if x is not None:
            batch.append(x)
    return len(new)
