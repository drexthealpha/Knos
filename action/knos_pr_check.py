"""Warn a pull request that touches work somebody is already on.

The third side of the loop. A maintainer runs `knos export` and commits
`.knos/decisions.md`; a contributor's agent reads it on its first question;
and this reads the same file in CI and says so on the pull request.

Deliberately non-blocking: every path through `main` returns 0, including
every failure path, so this can never redden a build.

Safe on both `pull_request` and `pull_request_target`. It reads only
`.knos/decisions.md` from the checkout and the pull request's own title,
body and file list from the API — it never checks out, executes or
evaluates anything from the head branch, which is the hazard that makes
`pull_request_target` dangerous in general.

No knos install needed here — CI has the committed file, not the store.
Standard library only, so the Action needs no dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

MARKER = "<!-- knos-pr-check -->"
MAX_DECISIONS = 3  # a comment nobody reads is worse than no comment
MAX_CLAIMS = 5  # same reason; a repository mid-sprint can hold many
SHARED = Path(".knos/decisions.md")

# Enough English to see that parser, parsers and parsing are one word. Same
# rule knos uses in-process; duplicated rather than imported because this
# runs with no dependencies.
_ENDINGS = ("ings", "ing", "ers", "er", "ed", "es", "s")
STOP = {
    "the", "and", "for", "with", "from", "into", "this", "that", "have",
    "has", "was", "were", "are", "not", "but", "all", "any", "our", "your",
    "add", "fix", "use", "new", "get", "set", "run", "make",
}


def stem(word: str) -> str:
    for ending in _ENDINGS:
        if len(word) - len(ending) >= 4 and word.endswith(ending):
            word = word[: -len(ending)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 4 else word


def words(text: str) -> set[str]:
    found = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", (text or "").lower())
    return {stem(w) for w in found if w not in STOP}


def read_decisions(text: str) -> list[tuple[str, str]]:
    """The decisions section of an exported file, as (about, note).

    Claims are about who is moving right now; decisions are about what was
    already settled. A pull request that reopens a settled decision is worth
    one line in the same comment.
    """
    found: list[tuple[str, str]] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## Decisions"):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if not inside or not line.startswith("- **"):
            continue
        try:
            about = line.split("**")[1]
            note = line.split("** — ", 1)[1].split("  _(recorded")[0]
        except (IndexError, ValueError):
            continue
        if about.strip():
            found.append((about.strip(), note.strip()))
    return found


def read_claims(text: str) -> list[tuple[str, str]]:
    """The claims section of an exported file, as (topic, who)."""
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


def api(url: str, token: str, payload: dict | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "knos-pr-check")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode()
    return json.loads(body) if body else None


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not (token and repo and event_path):
        print("knos: not in a pull request context, nothing to do.")
        return 0

    if not SHARED.exists():
        print(f"knos: no {SHARED}. Run `knos export` and commit it.")
        return 0

    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        number = event["pull_request"]["number"]
        title = event["pull_request"].get("title", "")
        body = event["pull_request"].get("body") or ""
    except (OSError, ValueError, KeyError) as why:
        print(f"knos: could not read the event ({why}).")
        return 0

    shared = SHARED.read_text(encoding="utf-8")
    claims = read_claims(shared)
    decisions = read_decisions(shared)
    if not (claims or decisions):
        print("knos: nothing is claimed and nothing is recorded.")
        return 0

    try:
        files = api(
            f"https://api.github.com/repos/{repo}/pulls/{number}/files?per_page=100", token
        )
        paths = [f["filename"] for f in files or []]
    except (urllib.error.URLError, KeyError, TypeError) as why:
        print(f"knos: could not list the changed files ({why}).")
        paths = []

    subject = words(f"{title} {body} " + " ".join(p.replace("/", " ").replace("_", " ") for p in paths))
    matched = [(topic, who) for topic, who in claims if words(topic) & subject]
    hits, spare = matched[:MAX_CLAIMS], len(matched) - MAX_CLAIMS

    # Decisions are quieter than claims: a settled decision is a note, not a
    # collision, so it is mentioned only when the branch names it, and only
    # the first few.
    touched = [(a, n) for a, n in decisions if words(a) & subject][:MAX_DECISIONS]

    if not (hits or touched):
        print("knos: this pull request touches neither claimed nor recorded work.")
        return 0

    lines = [MARKER]
    if hits:
        lines += [
            "**Someone is already working on this.**",
            "",
            "`.knos/decisions.md` in this repo says the following is claimed, and"
            " this pull request looks like it touches "
            + ("it" if len(hits) == 1 else "them")
            + ":",
            "",
        ]
        for topic, who in hits:
            lines.append(f"- **{topic}** - held by {who}")
        if spare > 0:
            lines.append(f"- and {spare} more, in `.knos/decisions.md`")
        lines += [
            "",
            "Nothing is blocked. This is a heads-up so two people do not land the"
            " same change twice - talk to them, or carry on if you already have.",
        ]
    if touched:
        if hits:
            lines.append("")
        lines += ["**Already decided here:**", ""]
        for about, note in touched:
            lines.append(f"- **{about}** - {note}")
        lines += [
            "",
            "Recorded in `.knos/decisions.md`. Changing it is fine; knowing it was"
            " decided is the point.",
        ]
    lines += [
        "",
        "<sub>Claims lapse after 30 minutes and are refreshed by `knos export`."
        " This check never fails a build.</sub>",
    ]
    comment = "\n".join(lines)

    # One comment per pull request, edited rather than repeated. A bot that
    # comments on every push is one people mute.
    try:
        existing = api(
            f"https://api.github.com/repos/{repo}/issues/{number}/comments?per_page=100", token
        )
        mine = [c for c in existing or [] if MARKER in (c.get("body") or "")]
        if mine:
            api(
                f"https://api.github.com/repos/{repo}/issues/comments/{mine[0]['id']}",
                token,
                {"body": comment},
            )
            print(f"knos: updated the note on #{number}.")
        else:
            api(
                f"https://api.github.com/repos/{repo}/issues/{number}/comments",
                token,
                {"body": comment},
            )
            print(f"knos: commented on #{number}.")
    except (urllib.error.URLError, KeyError, TypeError) as why:
        # A comment that cannot be posted is not a reason to fail a build.
        print(f"knos: could not comment ({why}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
