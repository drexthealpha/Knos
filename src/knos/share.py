"""What one machine's memory can safely put in the repository.

Everything else in knos is deliberately local: the store never leaves your
disk. That is right for transcripts and commits, which the next clone can
read for itself — but it is wrong for the two things that exist nowhere else
and that a *teammate* has no way to re-derive: what somebody decided, and
what somebody is working on right now.

So this writes one file, `.knos/decisions.md`, that you commit like any other
file. It is plain markdown, it diffs, and a second clone reads it without
running anything special — `.knos/decisions.md` is already one of the paths
knos treats as a decision record, so a fresh checkout picks it up on its
first question.

Nothing is exported that an agent could not already ask for. Notes about
private paths never enter, because they never entered the store in a form
this can reach.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import private

# The file a repo commits. Also listed in rules.DECISIONS, which is what
# makes a second clone read it with no extra step.
SHARED = Path(".knos") / "decisions.md"
# Long enough for any decision anyone writes by hand, short enough that a
# machine payload cannot take over the file.
_LINE = 400

HEADER = """# Decisions and current work

<!-- Written by `knos export`. Commit this file. -->

A second clone reads this on its first question — it is one of the decision
records knos looks for. Nothing here is private: secrets and private paths
never reach it.
"""


def _safe(repo: Path, text: str, about: str) -> bool:
    """Whether this note can go in a file the whole team will read.

    A note is only as safe as the path it names. `private.is_private` is the
    same check an agent's query goes through, so a note about `.env` is no
    more shareable than the file itself.
    """
    for token in (about, text):
        for word in str(token).split():
            # Strip quotes and trailing punctuation only. Stripping "." from
            # both ends turns ".env" into "env", which is not a private path
            # and never was - the same slip that once let a secret through
            # `lstrip("./")` here.
            cleaned = word.strip("`'\"()[]").rstrip(",.:;!?")
            if not cleaned:
                continue
            if "/" in cleaned or "." in cleaned:
                if private.is_private(repo, cleaned):
                    return False
    return True


def _one_line(note: str) -> str:
    """The readable part of a note, for a file other people commit.

    A decision is a sentence. What an agent pays for is a whole API response,
    and `remember` keeps it in full because that is what was bought. Putting
    all of it in the shared file turns a repo's decision record into a data
    dump, so this takes the first paragraph and caps it. The store still has
    the whole thing; `knos ask` still answers from it.
    """
    first = note.strip().split("\n\n", 1)[0].strip()
    if len(first) <= _LINE:
        return first
    return first[:_LINE].rstrip() + "..."


def export(repo: Path, mem: Any) -> tuple[str, int, int]:
    """Render the shareable half of this repo's memory.

    Returns the markdown, how many decisions it holds, and how many claims.
    """
    repo = Path(repo).resolve()
    notes = [
        n
        for n in mem.notes()
        if str(n.get("note", "")).strip() and _safe(repo, n.get("note", ""), n.get("about", ""))
    ]
    claims = [c for c in mem.claims() if str(c.get("topic", "")).strip()]

    out = [HEADER]
    out.append("\n## Decisions\n")
    if notes:
        for n in notes:
            when = str(n.get("when", ""))[:10]
            about = str(n.get("about", "")).strip() or "general"
            out.append(f"- **{about}** — {_one_line(str(n.get('note', '')))}")
            if when:
                out[-1] += f"  _(recorded {when})_"
    else:
        out.append("_Nothing recorded yet. `knos remember` adds to this._")

    out.append("\n## Being worked on right now\n")
    if claims:
        out.append(
            "An agent reading this should ask the person named before changing"
            " these, and CI will say so on a pull request that touches them.\n"
        )
        for c in claims:
            who = str(c.get("who", "")) or "someone"
            when = str(c.get("when", ""))[:16].replace("T", " ")
            out.append(f"- `{str(c.get('topic', '')).strip()}` — held by **{who}** since {when} UTC")
    else:
        out.append("_Nothing claimed._")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out.append(f"\n---\n<sub>knos export, {stamp}. Claims lapse after 30 minutes.</sub>\n")
    return "\n".join(out) + "\n", len(notes), len(claims)


def write(repo: Path, mem: Any) -> tuple[Path, int, int]:
    """Write `.knos/decisions.md` into the repo. Returns the path and counts."""
    text, decisions, claims = export(repo, mem)
    target = Path(repo).resolve() / SHARED
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target, decisions, claims


def read_claims(text: str) -> list[tuple[str, str]]:
    """Parse the claims back out of an exported file.

    Used by CI, which has the file but not the store. Deliberately tolerant:
    a malformed line is skipped rather than failing the check, because a
    non-blocking comment that does not appear is better than a red build.
    """
    found: list[tuple[str, str]] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## Being worked on"):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if not inside or not line.startswith("- `"):
            continue
        try:
            topic = line.split("`")[1]
            who = line.split("held by **")[1].split("**")[0]
        except (IndexError, ValueError):
            continue
        if topic.strip():
            found.append((topic.strip(), who.strip()))
    return found
