"""Which issue a pull request closes: the bounty it is for.

GitHub's own answer comes first: GraphQL `closingIssuesReferences` (`read` asks QUERY, `closing_from_graphql` reads
the answer), which also holds the links a maintainer made by hand. When that cannot be had, `closing_issues` reads the description the
way GitHub documents it: one of close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved, in any case,
with or without a colon, then `#N` or `owner/repo#N`. GitHub honours a keyword only in a pull request against the
default branch; `closed_by` puts the two together for one pull request. `mentions_without_closing` is for the check
on a pull request: it names a funded issue the description talks about without closing, so the author can be told
to write `Fixes #N`.

A description can be edited after the merge, by its author among others, and both answers follow the edit. A bounty
is paid for what a maintainer merged, so where money moves the caller also asks `facts`, which says from the same
answer whether the description was edited at or after the merge (`edited_late`); what it closes then does not count.
"""

from __future__ import annotations

import datetime
import re

QUERY = ("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number)"
         "{mergedAt lastEditedAt closingIssuesReferences(first:100){totalCount nodes{number repository{nameWithOwner}}}}}}")
_KEYWORD = re.compile(r"(?<![\w-])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?[ \t]+(?:([\w.-]{1,100}/[\w.-]{1,100}))?#(\d{1,10})\b",
                      re.I | re.A)
_MENTION = re.compile(r"(?<![\w/#&])(?:([\w.-]{1,100}/[\w.-]{1,100}))?#(\d{1,10})\b"
                      r"|github\.com/([\w.-]{1,100}/[\w.-]{1,100})/(?:issues|pull)/(\d{1,10})\b", re.I | re.A)


def variables(repo: str, number: int) -> dict:
    """QUERY's variables for one pull request: POST {"query": QUERY, "variables": ...} to GitHub's /graphql."""
    owner, _, name = repo.partition("/")
    return {"owner": owner, "name": name, "number": int(number)}


def cut(text: str, start: str = "<!--", end: str = "-->") -> str:
    """`text` without what lies between `start` and `end` (an HTML comment: there to be read by nobody). One left
    open hides the rest, as GitHub renders it."""
    out, i = [], 0
    while True:
        a = text.find(start, i)
        if a < 0:
            out.append(text[i:])
            break
        out.append(text[i:a] + " ")
        b = text.find(end, a + len(start))
        if b < 0:
            break
        i = b + len(end)
    return "".join(out)


def _prose(body: str) -> str:
    """The description without what GitHub does not read as its words: HTML comments, fenced code and inline code."""
    lines, fenced = [], False
    for line in cut((body or "")[:200_000]).splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            lines.append(re.sub(r"`[^`]*`", " ", line))
    return "\n".join(lines)


def closing_issues(body: str, repo: str) -> list[int]:
    """The issues of `repo` (owner/name) a description closes, in the order it names them. A keyword must come
    before every one: in "Fixes #10, #11" only #10 is closed. An issue of another repository is not this one's."""
    out = []
    for m in _KEYWORD.finditer(_prose(body)):
        if (not m.group(1) or m.group(1).lower() == repo.lower()) and int(m.group(2)) and int(m.group(2)) not in out:
            out.append(int(m.group(2)))
    return out


def closing_from_graphql(payload, repo: str | None = None) -> list[int] | None:
    """The same from GitHub's answer to QUERY: the issues of `repo` it closes (of any repository, when none is
    named). None when the answer is an error or was cut short: then read the description with `closing_issues`."""
    try:
        refs = payload["data"]["repository"]["pullRequest"]["closingIssuesReferences"]
        nodes = refs["nodes"]
        if payload.get("errors") or refs.get("totalCount", len(nodes)) > len(nodes):
            return None
        return list(dict.fromkeys(int(x["number"]) for x in nodes if repo is None
                                  or str((x.get("repository") or {}).get("nameWithOwner", repo)).lower() == repo.lower()))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _at(stamp) -> float | None:
    """GitHub's timestamp (2026-10-02T12:00:00Z) in seconds; None for anything else."""
    try:
        at = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)).timestamp()


def edited_late(payload) -> float | bool | None:
    """From GitHub's answer to QUERY: when the pull request's description was last edited, if that was at or after
    its merge (GitHub's clock counts in seconds, so the same second is not known to be before it); False when it is
    not merged, was never edited, or was last edited before the merge; None when the answer does not say."""
    try:
        if payload.get("errors"):
            return None
        pull = payload["data"]["repository"]["pullRequest"]
        merged, edited = pull["mergedAt"], pull["lastEditedAt"]
    except (KeyError, TypeError, AttributeError):
        return None
    if not merged or not edited:
        return False
    merged, edited = _at(merged), _at(edited)
    if merged is None or edited is None:
        return None
    return edited if edited >= merged else False


def facts(repo: str, number: int, post) -> tuple[list[int] | None, float | bool | None]:
    """(GitHub's own list of this repository's issues a pull request closes, `edited_late`), from one question asked
    through `post(path, payload)` (knos.judge.github). (None, None) when GitHub did not answer; either is None when
    its part of the answer was not whole."""
    try:
        got = post("graphql", {"query": QUERY, "variables": variables(repo, number)})
    except Exception:  # noqa: BLE001 - GitHub said no, or did not answer
        return None, None
    return closing_from_graphql(got, repo), edited_late(got)


def read(repo: str, number: int, post) -> list[int] | None:
    """GitHub's own list of this repository's issues a pull request closes: `facts` without the edit. None when
    GitHub did not give a whole answer."""
    return facts(repo, number, post)[0]


def closed_by(pull: dict, listed: list | None = None) -> list[int]:
    """Every issue a pull request closes when it is merged, GitHub's own list first: `listed` (from `read`; None
    when it could not be had), then what its description closes with a keyword, which counts only in a pull
    request against the default branch. These are the issues whose bounty it can be paid for."""
    base = pull.get("base") or {}
    repo = base.get("repo") or {}
    aside = bool(base.get("ref") and repo.get("default_branch") and base["ref"] != repo["default_branch"])
    words = [] if aside else closing_issues(pull.get("body") or "", str(repo.get("full_name") or ""))
    return list(dict.fromkeys([*(listed or []), *words]))


def mentions_without_closing(body: str, funded_issue_numbers, repo: str | None = None) -> list[int]:
    """The funded issues a description mentions (`#30`, `owner/repo#30`, or the issue's link) without closing them.
    `repo` tells this repository's `owner/repo#N` and links from another's; without it only a bare `#N` counts."""
    funded = {int(n) for n in funded_issue_numbers or ()}
    closed = set(closing_issues(body, repo or ""))
    seen = set()
    for m in _MENTION.finditer(_prose(body)):
        where, number = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
        if not where or (repo and where.lower() == repo.lower()):
            seen.add(int(number))
    return sorted((seen & funded) - closed)


def mention_note(numbers) -> str:
    """What to tell the author about them; empty when there is nothing to tell."""
    if not numbers:
        return ""
    one = len(numbers) == 1
    named = ", ".join(f"#{n}" for n in numbers)
    return (f"This mentions funded issue{'' if one else 's'} {named} but does not close {'it' if one else 'them'}. If this "
            f"pull request is for {'that bounty' if one else 'those bounties'}, write `Fixes #{numbers[0]}` in its description.")
