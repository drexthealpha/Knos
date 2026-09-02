"""Warn a pull request that touches work somebody is already on.

The third side of the loop. A maintainer runs `knos export` and commits
`.knos/decisions.md`; a contributor's agent reads it on its first question;
and this reads the same file in CI and says so on the pull request.

Deliberately non-blocking. It comments and exits 0, always. A memory tool
that can fail somebody's build has bought a veto it did not earn, and the
first thing a maintainer would do is delete it.

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

    claims = read_claims(SHARED.read_text(encoding="utf-8"))
    if not claims:
        print("knos: nothing is claimed.")
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
    hits = [(topic, who) for topic, who in claims if words(topic) & subject]

    if not hits:
        print("knos: this pull request does not touch claimed work.")
        return 0

    lines = [
        MARKER,
        "**Someone is already working on this.**",
        "",
        f"`.knos/decisions.md` in this repo says the following is claimed, and this"
        f" pull request looks like it touches {'it' if len(hits) == 1 else 'them'}:",
        "",
    ]
    for topic, who in hits:
        lines.append(f"- **{topic}** — held by {who}")
    lines += [
        "",
        "Nothing is blocked. This is a heads-up so two people do not land the same"
        " change twice — talk to them, or carry on if you already have.",
        "",
        "<sub>Claims lapse after 30 minutes and are refreshed by `knos export`.</sub>",
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
