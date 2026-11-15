"""One plain answer to a claim of payment where nothing was funded (.github/workflows/claims.yml runs this).

Knos pays one thing: an order funded with `/knos fund`, on Solana devnet, in test USDC, to the Solana address or the
passkey its payee bound. Pull requests arrive that claim a payment anyway: they carry the commands of bounty
platforms (`/claim`, `/attempt`, `/opire try`), or a wallet address on another chain, against an issue nobody
funded: sometimes against an issue that is not a task at all, such as the one the relay writes its log in. Left
unanswered, that reads as a debt. This module answers it once, in words that accuse nobody:

    python -m knos.claim_guard --event "$GITHUB_EVENT_PATH" --event-name "$GITHUB_EVENT_NAME"
    python -m knos.claim_guard --sweep          # every open issue and pull request (the timer: see claims.yml)

The always-on worker also runs this sweep (`sweep_served`, every pass of `knos.proof.ghrelay.once`), at most once
every SWEEP_EVERY seconds per repository it may write to, through the worker's own conditional reader, so a listing
with nothing new is a 304. GitHub's timer is only a fallback: in one release run (Knos 0.3.18) claims.yml's 15-minute
schedule did not fire once in 38 minutes.

What it does, and all it does: one comment (found again by its hidden first line, so a second event posts nothing)
and the label `no-order`. It closes nothing. It answers nothing written by the owner, a member, a collaborator or a
bot, and nothing when any issue the claim is about holds money on chain (the check is flow.py's own:
`knos.flow.funded`). When the chain does not answer it says nothing: not knowing is not "there is none". The one exception
is an issue that is a log (labels `knos-relay`, `knos-memory`; the titles those issues are made with): a log is not
a task whatever the chain says about its number.

NOTHING THE CLAIMANT WROTE REACHES THE COMMENT. The text is the constants below and issue numbers: integers this
repository's own API confirmed are issues. No title, no login, no address, no line of the claim is quoted, so
markdown, a mention or a very long body in a claim cannot put a word into what this repository says.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARK = "<!-- knos-no-order 1 -->"       # the first line of the answer: an item that has one gets no second
LABEL = "no-order"
LABEL_ABOUT = "No funded Knos order is attached, so no payment is due."    # GitHub keeps 100 characters of it
BOT = "github-actions[bot]"
PLAYGROUND = "https://github.com/drexthealpha/knos-playground"
FUNDED_LABEL = "knos-funded"            # the label every funded task of the playground carries
FUNDED = f"{PLAYGROUND}/issues?q=is%3Aissue+is%3Aopen+label%3A{FUNDED_LABEL}"       # the funded tasks, open to anyone
SWEEP_EVERY = 300                       # seconds between two sweeps of one repository by the always-on worker
SWEEP_AGAIN = 60                        # and after a sweep that could not read the listing
LOG_LINE = "a log written by a workflow. It is not a task and carries no payment."
OURS = {"OWNER", "MEMBER", "COLLABORATOR"}       # GitHub's author_association for whoever may write here
MAX_TEXT = 20_000                       # of a claim, what is read: the words of a claim come first or not at all
MAX_ISSUES = 3                          # the issues one answer names
MAX_NUMBER = 10_000_000
MACHINE_LABELS = ("knos-relay", "knos-memory")
MACHINE_TITLES = ("knos relay log", "knos tokens", "knos memory")

_PLATFORMS = r"algora|opire|issuehunt|bountysource|gitcoin|bountyhub|boss\.dev|bountycaster|gitpay"
_SOL = r"[1-9A-HJ-NP-Za-km-z]{32,44}"
_PAY_WORD = r"wallet|reward|payout|pay[- ]?out|payment|bounty|pay(?:able)? to|send (?:it |funds |payment )?to"
_COMMAND = re.compile(r"^[ \t>*_`-]*/(claim|attempt|opire|bounty)\b([^\n]*)", re.I | re.M)
_EVM = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{40}(?![0-9A-Za-z])")
_SOLANA = re.compile(rf"\b(?:{_PAY_WORD})\b[^\n]{{0,60}}?(?<![0-9A-Za-z]){_SOL}(?![0-9A-Za-z])", re.I)
_PLATFORM = re.compile(rf"(?<![0-9A-Za-z])(?:{_PLATFORMS})(?![0-9A-Za-z])", re.I)
_NUMBER = re.compile(r"(?<![0-9A-Za-z/])#(\d{1,8})\b|/issues/(\d{1,8})\b")
_KNOS = re.compile(r"^[ \t]*/knos[ \t]", re.M)


def claims(text: str | None) -> list[str]:
    """Why a text reads as a claim of payment: the names of the signs found (never posted), empty when none.
    A text with a `/knos` command line is Knos's own grammar, which the payment workflows answer, and is left to them."""
    text = str(text or "")[:MAX_TEXT]
    if _KNOS.search(text):
        return []
    found = [f"/{m.group(1).lower()}" for m in _COMMAND.finditer(text)]
    found += ["an EVM address"] if _EVM.search(text) else []
    found += ["a Solana address beside a word for payment"] if _SOLANA.search(text) else []
    found += ["a bounty platform"] if _PLATFORM.search(text) else []
    return list(dict.fromkeys(found))


def named(text: str | None) -> list[int]:
    """The issue numbers the claim's own command lines name (`/claim #17`, `/claim [#17](.../issues/17)`)."""
    out: list[int] = []
    for m in _COMMAND.finditer(str(text or "")[:MAX_TEXT]):
        out += [int(a or b) for a, b in _NUMBER.findall(m.group(2))]
    return [n for n in dict.fromkeys(out) if 0 < n < MAX_NUMBER]


def machine(issue: dict | None) -> bool:
    """Whether an issue is one a workflow writes its log in: the relay log, the tokens issue, the judge's memory."""
    if not isinstance(issue, dict) or "pull_request" in issue:
        return False
    labels = {str(x.get("name") if isinstance(x, dict) else x).lower() for x in issue.get("labels") or []}
    return bool(labels & set(MACHINE_LABELS)) or " ".join(str(issue.get("title") or "").lower().split()) in MACHINE_TITLES


def _issues(numbers: list[int]) -> str:
    words = [f"#{int(n)}" for n in numbers]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def answer(pull: bool, logs: list[int], plain: list[int]) -> str:
    """The comment: constants and issue numbers, nothing else. `logs` are the issues that are logs, `plain` the
    others with no funded order; with neither, the answer is about the item itself."""
    this = "this pull request" if pull else "this issue"
    lines = [MARK, f"Thank you for {'the pull request' if pull else 'writing'}. One thing to set straight, so that nobody waits for a payment:", ""]
    for n in logs[:MAX_ISSUES]:
        lines.append(f"- Issue #{int(n)} is {LOG_LINE}")
    every = [*logs[:MAX_ISSUES], *plain[:max(0, MAX_ISSUES - len(logs))]]
    if every:
        many = len(every) > 1
        lines.append(f"- Issue{'s' if many else ''} {_issues(every)} {'have' if many else 'has'} no funded order, so no payment is attached to "
                     f"{'them' if many else 'it'} or to work done for {'them' if many else 'it'}.")
    else:
        lines.append(f"- No funded order is attached to {this}, so no payment is attached to it.")
    lines += [
        "- Knos pays only orders funded with `/knos fund`, on Solana devnet, in test USDC that has no monetary value.",
        "- A payment goes to the Solana address or passkey its payee binds. An address on another chain cannot be paid.",
        f"- Funded work is listed by `knos work list`. The playground shows a funded order from start to finish: {PLAYGROUND}",
        f"- Funded tasks anyone may take carry the label `{FUNDED_LABEL}` there: {FUNDED}",
        "",
        ("This pull request is welcome as an ordinary, unpaid contribution if it is useful, and will be read as one."
         if pull else "A pull request is welcome as an ordinary, unpaid contribution if it is useful."),
    ]
    return "\n".join(lines)


def funded(run, repo_id: int, issue: int) -> bool:
    """Whether an issue holds money on chain: a job or a work order that is open, held or in its warranty. This is
    flow.py's own reading (`knos.flow.funded`), the one a settlement uses. Raises when the chain does not answer."""
    from . import flow
    return flow.funded(run, repo_id, issue)


def _ours(who: dict | None, association) -> bool:
    """Whether this repository wrote it: its own people (OURS) or Knos's own workflow account. Another bot (a review
    service, dependabot) is not this repository: its comment is not an answer."""
    who = who if isinstance(who, dict) else {}
    return str(association or "").upper() in OURS or str(who.get("login") or "") == BOT


def bot(who: dict | None) -> bool:
    """Whether an account is any bot: nothing is said to one."""
    who = who if isinstance(who, dict) else {}
    return who.get("type") == "Bot" or str(who.get("login") or "").endswith("[bot]")


def answered(comments: list) -> bool:
    """Whether this repository has answered here already: the marker, in a comment by the workflow's own account or
    by someone who may write here (the owner may post the same answer by hand). A marker in anyone
    else's comment is ignored."""
    return any(isinstance(c, dict) and str(c.get("body") or "").startswith(MARK)
               and ((c.get("user") or {}).get("login") == BOT or str(c.get("author_association") or "").upper() in OURS) for c in comments)


def handle(run, repo: str, repo_id: int, item: dict, texts: list[str], closes: list[int] | None = None) -> dict:
    """Answer one issue or pull request (`item`, as GitHub's issues API gives it) when `texts` claim a payment and
    nothing it is about is funded. Returns {"did": "answered" | "nothing", "why": ..., "body"?: ...}."""
    from . import terms
    number, pull = int(item["number"]), "pull_request" in item or "head" in item
    signs = [s for t in texts for s in claims(t)]
    if not signs:
        return {"did": "nothing", "why": "no claim of payment"}
    comments = terms.pages(f"repos/{repo}/issues/{number}/comments", run.github)
    if comments is None:
        return {"did": "nothing", "why": "the comments could not be read"}
    if answered(comments):
        return {"did": "nothing", "why": "answered already"}
    about = list(dict.fromkeys([*(n for t in texts for n in named(t)), *(closes or [])]))[:MAX_ISSUES + 2]
    logs: list[int] = []
    plain: list[int] = []
    for n in dict.fromkeys([*about, number]):
        try:
            issue = item if n == number else run.github(f"repos/{repo}/issues/{int(n)}")
        except OSError:
            continue        # not an issue of this repository: a number the claim made up names nothing here
        if not isinstance(issue, dict) or int(issue.get("number") or 0) != n:
            continue
        log = machine(issue)
        try:
            if funded(run, repo_id, n):
                return {"did": "nothing", "why": f"#{n} holds a funded order"}
        except Exception:  # noqa: BLE001 - the chain did not answer: whether #n is funded is not known
            if not log:
                return {"did": "nothing", "why": f"the chain did not say whether #{n} is funded"}
        if log or n != number:      # the item itself, when it is no log, is "this pull request" or "this issue"
            (logs if log else plain).append(n)
    body = answer(pull, logs, plain)
    run.github(f"repos/{repo}/issues/{number}/comments", {"body": body})
    try:
        run.github(f"repos/{repo}/labels", {"name": LABEL, "color": "ededed", "description": LABEL_ABOUT})
    except (OSError, ValueError):
        pass                # the label is there already
    try:
        run.github(f"repos/{repo}/issues/{number}/labels", {"labels": [LABEL]})
    except (OSError, ValueError):
        return {"did": "answered", "why": ", ".join(dict.fromkeys(signs)), "body": body, "label": False}
    return {"did": "answered", "why": ", ".join(dict.fromkeys(signs)), "body": body, "label": True}


def _closes(run, repo: str, number: int, pull: dict | None = None) -> list[int]:
    """The issues a pull request says it closes (knos.closing: the same reading a settlement makes of its words)."""
    from . import closing
    try:
        pull = pull if isinstance(pull, dict) and pull.get("base") else run.github(f"repos/{repo}/pulls/{int(number)}")
    except OSError:
        return []
    return [int(n) for n in closing.closed_by(pull if isinstance(pull, dict) else {}, None)]


def on_event(run, name: str, event: dict) -> dict:
    """One event of `issues`, `issue_comment` (or `pull_request`, as data, should a caller hand one in)."""
    rp = event.get("repository") or {}
    repo, repo_id = str(rp.get("full_name") or run.repo), int(rp.get("id") or 0)
    comment = event.get("comment") if name == "issue_comment" else None
    item = event.get("pull_request") or event.get("issue")
    if not isinstance(item, dict) or not repo_id:
        return {"did": "nothing", "why": "not an event about an issue or a pull request"}
    said = comment if isinstance(comment, dict) else item
    if _ours(said.get("user"), said.get("author_association")) or bot(said.get("user")):
        return {"did": "nothing", "why": "written by this repository's own people or a bot"}
    pull = "pull_request" in item or "head" in item
    texts = [str(said.get("body") or "")] if comment else [str(item.get("title") or ""), str(item.get("body") or "")]
    if not any(claims(t) for t in texts):
        return {"did": "nothing", "why": "no claim of payment"}
    closes = _closes(run, repo, int(item["number"]), event.get("pull_request")) if pull else []
    return handle(run, repo, repo_id, item, texts, closes)


def sweep(run, repo: str) -> list[dict]:
    """Every open issue and pull request of `repo`, newest change first: the ones that claim a payment and have no
    answer get one. This is how a pull request from a fork is answered: its own event carries a read-only token."""
    return _sweep(run, repo)[1]


def _sweep(run, repo: str, passed: list | None = None) -> tuple[int | None, list[dict]]:
    """(how many open issues and pull requests were read, what was done for each that claims a payment). The count
    is None when the listing could not be read whole: GitHub did not answer, or there were over 300. `passed`: given
    a list, the numbers of the items that read as a claim but are never answered (written by this repository's own
    people or a bot) are added to it, for the run's page (`left_out`)."""
    from . import terms
    rp = run.github(f"repos/{repo}")
    rows = terms.pages(f"repos/{repo}/issues?state=open&sort=updated&direction=desc", run.github, cap=3)
    if rows is None:
        return None, []
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        texts = [str(item.get("title") or ""), str(item.get("body") or "")]
        if not any(claims(t) for t in texts):
            continue
        if _ours(item.get("user"), item.get("author_association")) or bot(item.get("user")):
            if passed is not None:      # never answered; named on the run's page, so a claim-shaped item passed over is not invisible
                passed.append(int(item["number"]))
            continue
        closes = _closes(run, repo, int(item["number"])) if "pull_request" in item else []
        out.append({"number": int(item["number"]), **handle(run, repo, int(rp["id"]), item, texts, closes)})
    return len(rows), out


def left_out(number: int, repo: str = "") -> str:
    """The run page's line for an item that reads as a claim and is never answered: its author may write here, or is a
    bot. Before 0.3.19 such an item left no trace, and the page said "0 with a claim of payment" beside it."""
    return f"claims: {repo}#{int(number)} not answered (it reads as a claim, but this repository's own people or a bot wrote it)"


class Unread(RuntimeError):
    """A sweep could not read a repository's open issues and pull requests whole: nothing is known about its claims.
    `done`: what the same pass did in the repositories it could read."""
    done: list[dict] = []


def sweep_served(run_for, repos, state: dict, now: float, every: float = SWEEP_EVERY, say=print) -> list[dict]:
    """The always-on worker's part: sweep each of `repos` that is due. `state` is the worker's own note of when each
    repository was last swept ({repo: unix time}; changed here), so one repository is swept at most once in `every`
    seconds however often a pass asks. `run_for(repo)` gives the Run to read and write that repository with (the
    worker hands in its conditional reader: a listing it already holds costs a 304). Returns what was done, each
    with its repository. A repository whose listing could not be read is tried again after SWEEP_AGAIN seconds, and
    after every other repository was swept `Unread` is raised naming each: a sweep that read nothing is never silent."""
    done: list[dict] = []
    unread: list[str] = []
    for repo in sorted({str(r) for r in repos if "/" in str(r)}):
        if repo in state and float(state[repo]) > now - every:
            continue
        state[repo] = now
        passed: list[int] = []
        try:
            read, got = _sweep(run_for(repo), repo, passed)
        except Exception as why:  # noqa: BLE001 - GitHub or the chain did not answer for this repository: the others are still swept
            read, got = None, []
            say(f"claims: {repo}: {type(why).__name__}: {' '.join(str(why).split())[:200]}")
        if read is None:
            state[repo] = now - every + SWEEP_AGAIN
            unread.append(repo)
            continue
        say(f"claims: {repo}: {read} read (open issues and pull requests), {len(got)} with a claim of payment")
        for r in got:
            say(f"claims: {repo}#{r['number']} {r['did']} ({r['why']})")
        for n in passed:
            say(left_out(n, repo))
        done += [{"repo": repo, **r} for r in got]
    if unread:
        err = Unread(f"the open issues and pull requests of {', '.join(unread)} could not be read whole: no claim there was answered on this pass "
                     f"(asked again in {SWEEP_AGAIN} seconds)")
        err.done = done
        raise err
    return done


def main(argv: list[str] | None = None, run=None) -> int:
    import os
    p = argparse.ArgumentParser(prog="python -m knos.claim_guard", description="Answer a claim of payment on an issue with no funded order.")
    p.add_argument("--event", help="the event's JSON file ($GITHUB_EVENT_PATH)")
    p.add_argument("--event-name", default="")
    p.add_argument("--sweep", action="store_true", help="read every open issue and pull request instead of one event")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = p.parse_args(argv)
    from . import flow
    event = {}
    if args.event and not args.sweep:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    run = run or flow.Run(args.repo, event)
    if args.sweep:
        passed: list[int] = []
        read, got = _sweep(run, args.repo, passed)
        if read is None:    # a sweep that read nothing must not look like one that found nothing to answer
            print("claims: nothing (the open issues and pull requests could not be read whole)")
            return 1
        print(f"claims: {read} read (open issues and pull requests), {len(got)} with a claim of payment")
        for n in passed:
            print(left_out(n))
    else:
        got = [on_event(run, args.event_name, event)]
    for r in got:       # the job's log: what was done and why, never the claim's words
        print(f"claims: {('#' + str(r['number']) + ' ') if 'number' in r else ''}{r['did']} ({r['why']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
