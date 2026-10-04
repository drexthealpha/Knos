"""Who a pull request's bounty is paid to, where, and who holds an issue. Pure: the caller fetched everything.

    payee           who is paid and why, or nobody plus the exact comment that would fix it
    reservation     who holds the issue, since when, until when, and whether that has lapsed
    take, release   what `/knos take` and `/knos release` do: the assignees to add or remove, and the reply
    payout_address  where the payee's money goes: a bound wallet, else their own `/knos address` comment
    rejected        a maintainer's `/knos reject` on the pull request, written before the merge

The rules. A pull request a person opened pays that person. One a bot account opened pays a person only when GitHub
authenticates an act of theirs or of a maintainer: (1) the issue is assigned to exactly one person, by a maintainer
or by their own `/knos take`; else (2) a maintainer wrote `/knos pay @login` on the pull request; else (3) a person
named in the pull request's assignees wrote `/knos mine` on it. What the description or a commit says ("Requested
by", "Knos-Pay-To", a co-author) is shown as a hint and never decides: an agent can be talked into writing a line.

An assigned issue pays only its assignee's pull request. An assignment a person made holds until a person changes
it. A `/knos take` (the workflow's own token made the assignment) lasts the bounty's `reserve` days; after that it
has lapsed and anyone's merged pull request is paid.

A `/knos tip` goes to the same person, decided on the merged pull request alone (`payee(..., tip=True)`): no issue
enters it, and a `/knos reject`, which is about the bounty, does not stop it.

An edited comment never counts for `/knos pay`, `/knos mine`, `/knos address` or `/knos reject`: anyone with write
access can edit anyone's comment, and GitHub's REST API says only that the text changed. "Maintainer" means GitHub
answers write, maintain or admin for that account now (GET /repos/{repo}/collaborators/{login}/permission), never
the label on a comment.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from . import commands

MAINTAINER = ("admin", "maintain", "write")
WORKFLOW = (41898282, "github-actions[bot]")    # who GitHub records when a workflow's own token acts


def _ts(stamp) -> float | None:
    """GitHub's timestamp (2026-10-02T12:00:00Z) in seconds."""
    try:
        at = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)).timestamp()


def when(at: float) -> str:
    return datetime.datetime.fromtimestamp(at, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def unedited(comment: dict) -> bool:
    made = comment.get("created_at")
    return bool(made) and made == comment.get("updated_at")


def _person(user) -> bool:
    return isinstance(user, dict) and bool(user.get("id")) and user.get("type", "User") == "User"


def is_maintainer(login, permission) -> bool | None:
    """Whether GitHub says this account can write to the repository. None when it could not be asked."""
    if not login or permission is None:
        return None
    try:
        return str(permission(login)).lower() in MAINTAINER
    except Exception:  # noqa: BLE001 - GitHub did not answer: nobody is confirmed
        return None


def _once(permission):
    """`permission`, asking GitHub once per account (no answer is remembered too): one decision never rests on two
    different answers about the same account."""
    if permission is None:
        return None
    seen: dict = {}

    def ask(login):
        if login not in seen:
            try:
                seen[login] = (permission(login), None)
            except Exception as why:  # noqa: BLE001 - kept, and raised to everyone who asks about this account
                seen[login] = (None, why)
        got, why = seen[login]
        if why is not None:
            raise why
        return got
    return ask


def _agent(user) -> bool:
    """A GitHub account of type Bot (an App's or an agent's own): never a person, and never the workflow's own token."""
    return isinstance(user, dict) and bool(user.get("id")) and user.get("type") == "Bot" and not _workflow(user)


def _said(comments, kind) -> list[tuple[dict, object]]:
    """(comment, command) for every unedited comment by a person whose `/knos` line is a `kind`, newest first."""
    out = []
    for c in comments or []:
        if isinstance(c, dict) and unedited(c) and _person(c.get("user")):
            command = commands.parse(c.get("body") or "")
            if isinstance(command, kind):
                out.append((c, command))
    return sorted(out, key=lambda x: (_ts(x[0].get("created_at")) or 0, x[0].get("id") or 0), reverse=True)


# ---- who holds an issue ----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Hold:
    id: int
    login: str
    person: bool             # a person's account, not a bot's
    since: float | None      # when GitHub recorded the assignment (None: its events did not say)
    until: float | None      # when a `/knos take` lapses; None for an assignment, which holds until it is changed
    lapsed: bool
    by: str                  # who made the assignment
    taken: bool              # the workflow's own token made it: a `/knos take`


def _assigned(events, user_id) -> list[tuple[float, dict]]:
    """(when, by whom) for every time this account was assigned. The issue events API names the one who did it
    `assigner`; the timeline API names them `actor`."""
    out = []
    for e in events or []:
        if isinstance(e, dict) and e.get("event") == "assigned" and (e.get("assignee") or {}).get("id") == user_id:
            at = _ts(e.get("created_at"))
            if at is not None:
                out.append((at, e.get("assigner") or e.get("actor") or {}))
    return sorted(out, key=lambda x: x[0])


def _workflow(user: dict) -> bool:
    return user.get("id") == WORKFLOW[0] or user.get("login") == WORKFLOW[1]


def reservation(issue: dict | None, events: list | None, terms: dict | None, now: float | None) -> list[Hold]:
    """Every assignee of the issue as a Hold. `events` is GET /repos/{repo}/issues/{n}/events (None when it could
    not be read: then nothing is known to have lapsed); `terms` gives the days a take lasts; `now` is in seconds."""
    reserve = terms.get("reserve") if isinstance(terms, dict) else None
    out = []
    for a in (issue or {}).get("assignees") or []:
        if not a.get("id"):
            continue
        times = _assigned(events, a["id"])
        since, by = times[-1] if times else (None, {})
        taken = _workflow(by)
        until = since + reserve * 86_400 if taken and since is not None and isinstance(reserve, int) else None
        out.append(Hold(a["id"], str(a.get("login") or ""), a.get("type", "User") == "User", since, until,
                        until is not None and now is not None and now > until, str(by.get("login") or ""), taken))
    return out


def _holders(held: list[Hold]) -> str:
    return ", ".join(f"@{h.login}" + (f" until {when(h.until)}" if h.until is not None else "") for h in held[:4])


def excluded(issue: dict | None, pull: dict, paid: dict, events=None, terms=None, now=None) -> str:
    """Why the issue's assignment keeps this pull request from being paid; empty when it does not. An issue someone
    holds is theirs: only a pull request by a holder (or by the agent a holder ran) is paid for it."""
    held = [h for h in reservation(issue, events, terms, now) if not h.lapsed]
    ids = {h.id for h in held}
    if not ids or (pull.get("user") or {}).get("id") in ids or paid.get("id") in ids:
        return ""
    return f"issue #{issue.get('number')} is assigned to {_holders(held)}; only an assignee's pull request is paid for it"


@dataclass(frozen=True)
class Outcome:
    reply: str                         # the comment to post; empty when what comes next writes it
    assign: tuple[str, ...] = ()       # POST /repos/{repo}/issues/{n}/assignees {"assignees": [...]}
    unassign: tuple[str, ...] = ()     # DELETE the same path with the same body
    then: str = ""                     # what is left for the caller, because it needs the chain: fund, tip, settle, status


def take(issue: dict, events: list | None, terms: dict | None, commenter: dict, now: float, auto: bool = False) -> Outcome:
    """What `/knos take` by `commenter` (the comment's `user`) does. `terms` is the issue's bounty (None: not
    funded). It reserves an issue nobody holds, for `reserve` days, once per person: a reservation that lapsed is
    not renewed by taking again. Check GitHub's answer to the assignment: it ignores a login it cannot assign.
    A bot's account takes nothing, except with `auto` (the order was funded `auto`: it pays a pull request on the
    black-box suite alone, and an agent's own account is who takes such work)."""
    n, login = issue.get("number"), commenter.get("login")
    if terms is None or issue.get("state") == "closed":
        return Outcome(f"Knos: issue #{n} " + ("is closed" if terms is not None else "has no bounty") + ", so there is nothing to reserve.")
    if not (_person(commenter) or (auto and _agent(commenter))):
        return Outcome(commands.reply("not_allowed", "take"))
    holds = reservation(issue, events, terms, now)
    mine = next((h for h in holds if h.id == commenter["id"]), None)
    held = [h for h in holds if not h.lapsed]
    if mine and not mine.lapsed:
        return Outcome(f"Knos: you already hold issue #{n}" + (f" until {when(mine.until)}." if mine.until is not None else "."))
    if held:
        timed = all(h.until is not None for h in held)
        return Outcome(f"Knos: issue #{n} is assigned to {_holders(held)}, so only their pull request is paid"
                       + (" until then. After that it is open to everyone, and you can take it." if timed else
                          ". A maintainer can change the assignee."))
    if mine:
        return Outcome(f"Knos: your reservation of issue #{n} lapsed on {when(mine.until)}, and taking it again does "
                       "not renew it. The issue is open to everyone now, you included: any merged pull request that "
                       "closes it is paid.")
    if not terms.get("reserve"):
        return Outcome(f"Knos: the bounty on issue #{n} takes no reservations. It is open to everyone: the first accepted "
                       "pull request that is merged is paid.")
    if events is None:
        return Outcome(f"Knos: GitHub did not answer for issue #{n}'s history, so nothing was reserved. Comment `/knos take` again.")
    before = [at for at, by in _assigned(events, commenter["id"]) if _workflow(by)]
    if before:
        return Outcome(f"Knos: you took issue #{n} before, on {when(before[-1])}, and a reservation is given once. "
                       "Nobody holds it now, so you can still open the pull request: any merged pull request that closes "
                       "it is paid. A maintainer can also assign you.")
    until = when(now + terms["reserve"] * 86_400)
    gone = tuple(h.login for h in holds if h.person and h.login)
    return Outcome(f"Knos: issue #{n} is reserved for @{login} until {until}. Open a pull request whose description says "
                   f"`Fixes #{n}`; until then only yours is paid for it. After that it is open to everyone again. "
                   "`/knos release` gives it back sooner."
                   + (f" ({', '.join('@' + g for g in gone)}'s reservation had lapsed.)" if gone else ""), (login,), gone)


def release(issue: dict, events: list | None, terms: dict | None, commenter: dict, now: float) -> Outcome:
    """What `/knos release` by `commenter` does: it takes them off an issue they are assigned to, whoever assigned
    them. Nobody releases someone else: a maintainer changes the assignee with GitHub's own control."""
    n = issue.get("number")
    if terms is None:
        return Outcome(f"Knos: issue #{n} has no bounty, so there is nothing to release.")
    holds = reservation(issue, events, terms, now)
    if not any(h.id == commenter.get("id") for h in holds):
        held = [h for h in holds if not h.lapsed]
        return Outcome(f"Knos: you do not hold issue #{n}, so nothing changed."
                       + (f" It is assigned to {_holders(held)}; a maintainer can change that." if held else ""))
    still = [h for h in holds if not h.lapsed and h.id != commenter.get("id")]
    after = (f"It is still assigned to {_holders(still)}." if still else
             "It is open to everyone." + (" `/knos take` reserves it." if terms.get("reserve") else ""))
    return Outcome(f"Knos: @{commenter.get('login')} gave issue #{n} back. {after}", unassign=(commenter.get("login"),))


# ---- who is paid -----------------------------------------------------------------------------------------------------

# How the agents that open pull requests under a bot account name the person who ran them. Each is a whole line of
# the description: Devin ends it with "Requested by: @login"; Jules with "PR created automatically by Jules for task
# N started by @login"; anyone can write "Knos-Pay-To: @login".
_LOGIN = r"@([A-Za-z0-9][A-Za-z0-9-]{0,38})"
_PAY_TO = (re.compile(r"knos-pay-to:[ \t]{0,8}" + _LOGIN + r"\.?", re.I),
           re.compile(r"requested by:?[ \t]{0,8}" + _LOGIN + r"\.?", re.I),
           re.compile(r"pr created automatically by jules\b[^@]{0,120}\bstarted by[ \t]{0,8}" + _LOGIN + r"\.?", re.I))
# Copilot and Cursor credit that person in the commit, with GitHub's no-reply address.
_CO_AUTHOR = re.compile(r"co-authored-by:[^<]{0,120}<\d{1,12}\+([A-Za-z0-9-]{1,39})@users\.noreply\.github\.com>", re.I)


def hinted(pull: dict, head_message: str = "") -> list[str]:
    """The logins a bot's description and head commit name as the person who ran it, lowercased. A hint to show:
    it never decides who is paid. Quoted lines and fenced code are not the description's own words and are skipped."""
    out, fenced = set(), False
    for line in (pull.get("body") or "").splitlines()[-400:]:
        line = line.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or line.startswith(">") or len(line) > 300:
            continue
        out.update(m.group(1).lower() for m in (pat.fullmatch(line) for pat in _PAY_TO) if m)
    out.update(m.group(1).lower() for line in (head_message or "").splitlines()[-200:] if len(line) <= 300
               for m in [_CO_AUTHOR.fullmatch(line.strip())] if m)
    return sorted(out)


def _known(login: str, user, *sources) -> dict | None:
    """The person's account behind a login: from what the caller already holds, else asked of GitHub (`user`,
    which raises when GitHub does not answer). None when it is nobody's, or not a person's."""
    want = login.lower()
    for source in sources:
        for item in source or []:
            for u in (item, item.get("user") if isinstance(item, dict) else None):
                if isinstance(u, dict) and str(u.get("login") or "").lower() == want and u.get("id") and u.get("type"):
                    return u if _person(u) else None
    got = user(login) if user else None
    return got if _person(got) and got.get("type") == "User" else None


def _rejects(pull: dict, pull_comments: list | None, permission):
    """(comment, command, whether its writer can write to the repository) for every unedited `/knos reject` a person
    wrote on the pull request before it was merged, newest first."""
    merged = _ts(pull.get("merged_at")) if pull.get("merged_at") else None
    for c, command in _said(pull_comments, commands.Reject):
        at = _ts(c.get("created_at"))
        if merged is None or (at is not None and at < merged):
            yield c, command, is_maintainer(c["user"].get("login"), permission)


def rejected(pull: dict, pull_comments: list | None, permission) -> dict | None:
    """The newest `/knos reject` on the pull request that counts: unedited, by someone with write access, written
    before the merge. {"by", "reason", "at", "comment"}; None when there is none. After the merge a payment that
    was made is final, so a later reject does nothing."""
    for c, command, can in _rejects(pull, pull_comments, permission):
        if can:
            return {"by": c["user"].get("login"), "reason": commands._show(command.reason, 200),
                    "at": c.get("created_at"), "comment": c.get("id")}
    return None


def payee(pull: dict, issue: dict | None = None, events: list | None = None, pull_comments: list | None = None,
          issue_comments: list | None = None, permission=None, terms: dict | None = None, now: float | None = None,
          head_message: str = "", user=None, strict: bool = False, closes: list | None = None, tip: bool = False,
          edited: float | bool | None = False, auto: bool = False) -> dict:
    """Who this pull request's bounty is paid to: {"id", "login", "why"}; or {"id": None, "why", "fix", "kind"} when
    nobody is, where `fix` is the exact comment (or act) that would change that and `kind` is payee (nobody can be
    named), assigned (the issue is someone else's), rejected (a maintainer said no before the merge), issue (the
    pull request does not close it), unmerged (a tip, before the merge) or unread (GitHub did not give what
    decides it). For a bot's pull request "hint" says who its text names; that is shown and never used.

    The caller fetched it all: `pull` and `issue` as GitHub gives them; `events` (the issue's events, for when and
    by whom it was assigned); the comments on the pull request and on the issue; `permission(login)` (GitHub's
    answer for that account on this repository) and `user(login)` (GET /users/{login}, to turn the login a
    maintainer named into an account); `terms` (the bounty's, for how long a take lasts); `now` in seconds.
    With only `pull`, a person's pull request still pays its author, and a bot's pays nobody.

    What was not given (None) names nobody and holds nothing against anyone. `strict` (the merged commit, where
    money moves) does not let that pass: without a fact the answer rests on (the issue, the pull request's
    comments, who assigned the issue, whether the writer of a `/knos reject` or a `/knos pay` can write to the
    repository, whose account a named login is) nobody is paid until it is run again. And there the pull request
    must close the issue: it is in `closes`, GitHub's own list of the issues it closes
    (knos.closing.closing_from_graphql), or the description closes it with one of GitHub's keywords in a pull
    request against the default branch. And it must have said so when it was merged: `edited` is
    knos.closing.edited_late (when the description was last edited, if at or after the merge; None: GitHub did not
    say). A description can be edited after the merge, by its author among others, and what it closes follows the
    edit, so one edited then closes nothing here: the merge accepted what it said before.

    `auto`: the order was funded `auto` and the pull request is open. Its funder chose that the first pull request the
    black-box suite passes is paid to its author, nobody deciding in between, so a bot's pull request pays the bot's
    own account (an agent with a GitHub account of its own is who such an order is for). Everything else holds as
    it does for a person: the pull request closes the issue, a maintainer's `/knos reject` stops it, and an issue
    someone else holds is theirs.

    `tip`: who a `/knos tip` on this pull request goes to. The same person, decided on the pull request alone: it
    must be merged; no issue is asked about and no assignment excludes anyone; a `/knos reject` is about the bounty
    and does not stop a tip; and, money moving here too, nothing is decided on a read that failed."""
    author = pull.get("user") or {}
    bot = author.get("type", "User") != "User"
    names = hinted(pull, head_message) if bot else []
    hint = {"hint": "its text names " + ", ".join("@" + n for n in names) + ", which is a hint and decides nothing"} if names else {}
    permission = _once(permission)

    def nobody(why: str, fix: str, kind: str = "payee") -> dict:
        return {"id": None, "login": None, "why": why, "fix": fix, "kind": kind, **hint}

    def unread(what: str) -> dict:
        return nobody(f"GitHub did not {what}, so who is paid cannot be decided yet", "Run this again.", "unread")

    if tip:
        if not (pull.get("merged_at") or pull.get("merged")):
            return nobody("this pull request is not merged", "A tip is for a merged pull request: merge it first.", "unmerged")
        if bot and pull_comments is None:
            return unread("give this pull request's comments")
        issue = events = issue_comments = None
    elif strict:
        asked = [c["user"].get("login") for c, _, can in _rejects(pull, pull_comments, permission) if can is None]
        missing = ("give the issue" if not isinstance(issue, dict) else "give this pull request's comments" if pull_comments is None
                   else "say who assigned the issue, and when" if events is None and issue.get("assignees")
                   else f"say whether @{asked[0]}, who wrote `/knos reject`, can write to the repository" if asked else "")
        if missing:
            return unread(missing)
        why = _open(pull, issue.get("number"), closes)
        if why:
            return nobody(why, f"Its description must say `Fixes #{issue.get('number')}`.", "issue")
        if pull.get("merged_at") and edited is None:
            return unread("say whether this pull request's description was edited after it was merged")
        if pull.get("merged_at") and edited:
            return nobody(f"its description was edited on {when(edited)}, after it was merged, so what it says it closes no longer "
                          f"counts (anyone who can edit it could add `Fixes #{issue.get('number')}` later)", "", "issue")
    no = None if tip else rejected(pull, pull_comments, permission)
    if no:
        return nobody(f"@{no['by']} rejected this pull request for the bounty" + (f" ({no['reason']})" if no["reason"] else ""),
                      f"To undo, @{no['by']} deletes that `/knos reject` comment.", "rejected")
    if not bot or (auto and not tip and _agent(author)):
        if not author.get("id"):
            return nobody("GitHub did not say who opened this pull request", "Run this again.")
        paid = {"id": author["id"], "login": author.get("login"),
                "why": "the pull request's author" + (", an agent's account: the order was funded `auto`" if bot else "")}
    else:
        paid = _for_agent(pull, issue, reservation(issue, events, terms, now), pull_comments, issue_comments,
                          permission, user, names, nobody, unread if strict or tip else None)
        if not paid.get("id"):
            return paid
    why = excluded(issue, pull, paid, events, terms, now)
    if why:
        return nobody(why, "A maintainer can change the issue's assignee; a `/knos take` lapses on the date shown.", "assigned")
    return {**paid, **hint}


def _open(pull: dict, n, closes: list | None) -> str:
    """Why this pull request does not close issue `n`; empty when it does: GitHub lists the issue among those it
    closes, or its description closes it the way GitHub documents (and it is against the default branch)."""
    from .closing import closed_by, closing_issues
    if n in closed_by(pull, closes):
        return ""
    base = pull.get("base") or {}
    if n in closing_issues(pull.get("body") or "", str((base.get("repo") or {}).get("full_name") or "")):
        return (f"this pull request is against `{commands._show(base.get('ref'))}`, and GitHub closes an issue only from a pull "
                "request against the default branch")
    return f"this pull request does not close issue #{n}"


def _for_agent(pull, issue, holds, pull_comments, issue_comments, permission, user, names, nobody, unread) -> dict:
    """Who a bot's pull request pays. `unread` (given at the merge) is the answer when GitHub did not give a fact
    one of the three ways rests on; without it that way names nobody and the next is tried."""
    bot, n = (pull.get("user") or {}).get("login"), (issue or {}).get("number")
    people = [h for h in holds if h.person and not h.lapsed]
    silent = False              # GitHub did not answer who can write
    if len(people) == 1:        # (1) the issue is one person's, by an act GitHub authenticates
        h = people[0]
        if h.taken:
            if issue_comments is None and unread:
                return unread("give the issue's comments")
            if any(isinstance(c, dict) and (c.get("user") or {}).get("id") == h.id
                   and isinstance(commands.parse(c.get("body") or ""), commands.Take) for c in issue_comments or []):
                return {"id": h.id, "login": h.login, "why": f"issue #{n} is theirs: they took it with `/knos take`"}
        elif h.by:
            can = is_maintainer(h.by, permission)
            if can:
                return {"id": h.id, "login": h.login, "why": f"issue #{n} is theirs: maintainer @{h.by} assigned it to them"}
            if can is None and unread:
                return unread(f"say whether @{h.by}, who assigned the issue, can write to the repository")
            silent = can is None
    for c, command in _said(pull_comments, commands.Pay):      # (2) a maintainer named the person, newest first
        by = c["user"].get("login")
        can = is_maintainer(by, permission)
        if can is None and unread:
            return unread(f"say whether @{by}, who wrote `/knos pay`, can write to the repository")
        silent = silent or can is None
        if not can:
            continue
        try:
            who = _known(command.login, user, [pull.get("user")], pull.get("assignees"), (issue or {}).get("assignees"),
                         pull_comments, issue_comments)
        except Exception:  # noqa: BLE001 - GitHub did not answer whose login that is: nobody is confirmed
            if unread:
                return unread(f"say whose account @{command.login} is")
            who = None
        if not who:
            return nobody(f"maintainer @{by} named @{command.login}, which GitHub did not confirm as a person's account",
                          "A maintainer comments `/knos pay @login` on this pull request, with a person's login.")
        return {"id": who["id"], "login": who.get("login"), "why": f"maintainer @{by} named them with `/knos pay`"}
    named = {a["id"]: a.get("login") for a in pull.get("assignees") or [] if _person(a)}
    mine = {c["user"]["id"]: c["user"].get("login") for c, _ in _said(pull_comments, commands.Mine) if c["user"]["id"] in named}
    if len(mine) == 1:          # (3) a person the pull request names claimed it
        (uid, login), = mine.items()
        return {"id": uid, "login": login, "why": f"named in the assignees of {bot}'s pull request, and claimed it with `/knos mine`"}
    if len(mine) > 1:
        return nobody(f"more than one person claimed {bot}'s pull request with `/knos mine` ("
                      + ", ".join("@" + str(v) for v in sorted(map(str, mine.values()))) + ")",
                      "A maintainer decides: they comment `/knos pay @login` on this pull request.")
    fix = f"A maintainer comments `/knos pay @{names[0] if len(names) == 1 else 'login'}` on this pull request"
    if named:
        fix += ", or " + " or ".join("@" + str(v) for v in list(named.values())[:3]) + " (named in its assignees) comments `/knos mine`"
    return nobody(f"{bot} is a bot account, and nothing GitHub authenticates names the person who ran it"
                  + (" (GitHub did not answer who has write access; run this again)" if silent else ""), fix + ".")


def payout_address(paid: dict, pull_comments: list | None, bound: str | None = None) -> dict:
    """Where the payee's money goes: {"address", "from", "why"}. `bound` is the wallet bound to their GitHub account
    on chain, when the caller read one: it comes first. Else their own newest `/knos address` comment on the pull
    request, when it is unedited. Else nothing (address None, "-" in the pay audience): the bounty is held for them
    for 180 days, until they bind a wallet. An edited newest comment is not skipped in favour of an older one: the
    older address is the one they replaced."""
    if not paid.get("id"):
        return {"address": None, "from": None, "why": "nobody is paid"}
    who = f"@{paid.get('login')}"
    if bound:
        return {"address": bound, "from": "bound", "why": f"the wallet bound to {who}'s GitHub account"}
    theirs = [c for c in pull_comments or [] if isinstance(c, dict) and (c.get("user") or {}).get("id") == paid["id"]
              and isinstance(commands.parse(c.get("body") or ""), commands.Address)]
    if not theirs:
        return {"address": None, "from": None,
                "why": f"{who} gave no address: the bounty is held for them until they bind a wallet to their GitHub account. "
                       "To be paid at the merge instead, they comment `/knos address <address>` on this pull request before it"}
    newest = max(theirs, key=lambda c: (_ts(c.get("created_at")) or 0, c.get("id") or 0))
    if not unedited(newest):
        return {"address": None, "from": None,
                "why": f"{who}'s newest `/knos address` comment was edited, so it does not count: they post the address "
                       "again in a new comment"}
    return {"address": commands.parse(newest["body"]).address, "from": "comment", "comment": newest.get("id"),
            "why": f"{who}'s `/knos address` comment on this pull request"}


# ---- one comment, answered -------------------------------------------------------------------------------------------

def answer(command, commenter: dict, pull: dict | None = None, issue: dict | None = None, events: list | None = None,
           pull_comments: list | None = None, issue_comments: list | None = None, permission=None,
           terms: dict | None = None, now: float | None = None, user=None, auto: bool = False) -> Outcome | None:
    """What Knos does with one `/knos` comment: the reply to post, the assignees to change, and what is left for
    the caller (`then`). None when the comment holds no command.

    `command` is commands.parse(body, on_pull) and `commenter` the comment's `user`. On a pull request: `pull`, its
    comments (the new one among them), and `issue` with its `events` and comments when the caller knows which
    issue's bounty it is for. On an issue: `issue` and its `events`. `terms` is that issue's bounty (None: it has
    none). Who may give a command is decided here from what GitHub authenticates: a maintainer is whoever
    `permission(login)` says can write; `/knos mine` is for a person in a bot's pull request's assignees; and
    `/knos address` for the person the pull request pays. `auto`: the issue's open order was funded `auto`, so
    an agent's own account (GitHub type Bot) may take it; every other command still asks for a person. Who may spend money (`/knos fund`, `/knos tip`) is the
    chain's to decide, so those are handed on."""
    if command is None:
        return None
    if isinstance(command, commands.Error):
        return Outcome(command.reply)
    name, login = command.name, commenter.get("login")
    now = datetime.datetime.now(datetime.timezone.utc).timestamp() if now is None else now
    if name in ("fund", "status"):
        return Outcome("", then=name)
    if name == "help":
        return Outcome(commands.reply("understood", command))
    if name in ("take", "release"):
        return take(issue or {}, events, terms, commenter, now, auto) if name == "take" else release(issue or {}, events, terms, commenter, now)
    pull = pull or {}
    merged = bool(pull.get("merged_at") or pull.get("merged"))
    if name in ("tip", "settle"):
        if not merged:
            return Outcome("Knos: this pull request is not merged. " + ("A tip is for a merged pull request: merge it first."
                                                                         if name == "tip" else "Its payment is tried once it is."))
        return Outcome(commands.reply("understood", command) if name == "settle" else "", then=name)
    if name in ("pay", "reject"):
        can = is_maintainer(login, permission)
        if can is None:
            return Outcome(f"Knos: GitHub did not answer whether @{login} can write to this repository, so nothing was noted. "
                           "Post the comment again.")
        if not can:
            return Outcome(commands.reply("not_allowed", name))
        if name == "reject":
            return Outcome("Knos: this pull request is already merged. `/knos reject` counts only before the merge: a payment "
                           "that was made is final." if merged else commands.reply("understood", command, login=login))
    author = pull.get("user") or {}
    bot = author.get("type", "User") != "User"
    if name == "mine":
        if not bot:
            return Outcome(f"Knos: a person opened this pull request, so it pays them (@{author.get('login')}). `/knos mine` is "
                           "for a pull request a bot account opened.")
        if not _person(commenter) or commenter["id"] not in {a.get("id") for a in pull.get("assignees") or [] if isinstance(a, dict)}:
            return Outcome(commands.reply("not_allowed", name))
    paid = payee(pull, issue, events, pull_comments, issue_comments, permission, terms, now, "", user)
    if name == "address":       # a person's pull request is its author's, whatever happens to the bounty: a tip pays them too
        if commenter.get("id") and commenter["id"] == (paid if bot else author).get("id"):
            return Outcome(commands.reply("understood", command, login=login))
        return Outcome(commands.reply("not_allowed", name, instead=(
            "An address counts once this pull request pays you: if an agent opened it for you and you are one of its "
            "assignees, comment `/knos mine`; or a maintainer comments `/knos pay @you`. Then post the address again.")
            if bot and not paid.get("id") else None))
    if name == "mine" and paid.get("id") and paid["id"] != commenter["id"]:
        return Outcome(f"Knos: this pull request pays @{paid.get('login')}, not @{login}: {paid.get('why')}.")
    return Outcome(commands.reply("understood", command, paid=paid))      # mine, pay: who it pays now


# ---- reading GitHub: `get(path)` is knos.judge.github ------------------------------------------------------------------

def read(repo: str, number: int, issue, get) -> dict:
    """What `payee` needs from GitHub for pull request `number` closing `issue`: {"issue", "events",
    "pull_comments", "issue_comments"}, each None when GitHub did not give all of it."""
    from .terms import pages

    def one(path: str):
        try:
            got = get(path)
        except Exception:  # noqa: BLE001
            return None
        return got if isinstance(got, dict) else None

    n = str(issue or "")
    return {"issue": one(f"repos/{repo}/issues/{n}") if n.isdigit() else None,
            "events": pages(f"repos/{repo}/issues/{n}/events", get) if n.isdigit() else None,
            "pull_comments": pages(f"repos/{repo}/issues/{number}/comments", get),
            "issue_comments": pages(f"repos/{repo}/issues/{n}/comments", get) if n.isdigit() else None}


def permission_of(repo: str, get):
    """`permission(login)` for `payee`: GitHub's answer for that account on this repository, as admin, write, read
    or none (it reads maintain as write and triage as read). An account GitHub does not know there (404) has
    none. Raises when GitHub does not answer: not knowing is not the same as "cannot"."""
    def permission(login: str) -> str:
        try:
            return str(get(f"repos/{repo}/collaborators/{login}/permission").get("permission"))
        except OSError as why:
            if getattr(why, "code", None) == 404:
                return "none"
            raise
    return permission


def user_of(get):
    """`user(login)` for `payee`: the account behind a login (GET /users/{login}). None when GitHub knows no such
    account (404). Raises when GitHub does not answer."""
    def user(login: str):
        try:
            return get(f"users/{login}")
        except OSError as why:
            if getattr(why, "code", None) == 404:
                return None
            raise
    return user
