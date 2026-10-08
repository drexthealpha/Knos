"""Who outside Knos has used it: three numbers that are never added to each other.

    funders        GitHub accounts and wallets that are not Knos's and funded a job or a work order: the account whose
                   comment funded it, or the wallet that funded it directly. Two parts, shown apart:
                     in_outside_repositories       the money was the repository owner's own Balance, a wallet's, or the
                                                   faucet's in a repository that is not Knos's
                     in_knos_repositories_faucet   "outside funder, Knos repository, faucet money": an outside account's
                                                   comment funded it in a repository of Knos's (the playground) with the
                                                   devnet faucet's free test USDC. Nothing of the funder's was spent.
                   An outside account that spends a Balance of Knos's real tokens is not a funder: the money is Knos's.
    repositories   repositories that are not Knos's in which an outside funder funded at least one.
    payees         GitHub accounts and wallets that are not Knos's and were paid by a job somebody else funded. A payment
                   to the funder's own account or back to the wallet whose money it was is not counted.

"Knos's" is scripts/own_github_ids.json: account ids, wallets and, under "repositories", repository ids. A repository
is Knos's when its id is listed, when GitHub names one of Knos's account ids as its owner (scripts/network_stats.py
own_repositories: the chain gives a repository's id only, so a wallet that funds there carries no owner on record), or
when the Balance the job spent belongs to one of Knos's accounts (a comment spends the
repository owner's Balance, and the faucet's Balance is the repository owner's too: its address is derived from the
owner's id, so it is known even when the line that opened it was not read). An account is counted by its
GitHub id, a wallet by its address; an id of 0 is "no account".

This reads a job as scripts/network_stats.py and scripts/pages_data.py hold it (knos.records' jobs and work orders) and
needs nothing else, so a build that read no chain can still write the three zeros and say they were not measured.
"""
from __future__ import annotations

import re

LABEL_KNOS_FAUCET = "outside funder, Knos repository, faucet money"
DEFINITIONS = {
    "funders": "accounts and wallets that are not Knos's and funded a job: the commenter, or the wallet that funded it",
    "funders_in_outside_repositories": "of those, the ones that funded in a repository that is not Knos's",
    "funders_in_knos_repositories_faucet": f"{LABEL_KNOS_FAUCET}: an outside account's comment in a repository of Knos's, paid by the devnet faucet's test USDC",
    "repositories": "repositories that are not Knos's in which an outside funder funded a job",
    "payees": "accounts and wallets that are not Knos's and were paid by a job somebody else funded",
}


def _paid(job: dict) -> bool:
    return job.get("state") == "paid" or bool(job.get("paid_at"))


def funder_of(job: dict, own: frozenset, own_wallets: frozenset, own_repos: frozenset = frozenset(),
              own_balances: frozenset = frozenset()) -> tuple[str, str] | None:
    """(who funded, where) for a job an outsider funded, else None. Who: "gh:<id>" or "wallet:<address>". Where:
    "outside" (a repository that is not Knos's) or "knos_faucet" (a repository of Knos's, the faucet's money).
    `own_balances`: addresses of Balances that are Knos's whoever opened them on record (its faucet Balances: a
    history read in part may not hold the line that says whose a Balance is)."""
    by, owner, wallet = int(job.get("by") or 0), int(job.get("owner") or 0), job.get("wallet") or (job.get("source") if not job.get("by") else None)
    knos_repo = owner in own or job.get("repo") in own_repos or (bool(job.get("source")) and job.get("source") in own_balances)
    if by:
        if by in own:
            return None
        if knos_repo:      # Knos's Balance: the faucet's test money is nobody's, anything else is Knos's own
            return (f"gh:{by}", "knos_faucet") if job.get("faucet") else None
        return (f"gh:{by}", "outside") if wallet not in own_wallets or job.get("faucet") else None
    if owner:              # a Balance spent with no commenter on record: its owner funded
        return None if knos_repo else (f"gh:{owner}", "outside")
    if not wallet or wallet in own_wallets or job.get("repo") in own_repos:
        return None
    return f"wallet:{wallet}", "outside"


def payees_of(job: dict, own: frozenset, own_wallets: frozenset) -> set[str]:
    """The outside accounts and wallets a job paid that are not its funder."""
    if not _paid(job):
        return set()
    funders = {int(job.get("by") or 0), int(job.get("owner") or 0)} - {0}
    wallet = job.get("wallet") or job.get("source")
    out = set()
    ids, tos = list(job.get("payees") or [job.get("payee") or 0]), list(job.get("tos") or [job.get("to")])
    tos += [None] * (len(ids) - len(tos))
    for i, to in zip(ids, tos):
        if i:
            if i not in own and i not in funders and to not in own_wallets:
                out.add(f"gh:{i}")
        elif to and to not in own_wallets and to != wallet:
            out.add(f"wallet:{to}")
    return out


def count(jobs: list[dict], own: frozenset, own_wallets: frozenset, own_repos: frozenset = frozenset(), measured: bool = True,
          own_balances: frozenset = frozenset()) -> dict:
    """The three numbers and the two parts of the first, with what each means. `measured` False: nothing was read, and
    the zeros are not a count."""
    outside, faucet, repos, payees = set(), set(), set(), set()
    for j in jobs:
        f = funder_of(j, own, own_wallets, own_repos, own_balances)
        if f:
            (outside if f[1] == "outside" else faucet).add(f[0])
            if f[1] == "outside" and j.get("repo"):
                repos.add(j["repo"])
        payees |= payees_of(j, own, own_wallets)
    return {"measured": bool(measured), "funders": len(outside | faucet), "funders_in_outside_repositories": len(outside),
            "funders_in_knos_repositories_faucet": len(faucet), "repositories": len(repos), "payees": len(payees),
            "summed": False, "definitions": DEFINITIONS}


# ---- tasks that turn a zero into a one: counted only when the account that did them is outside --------------------------------------
TASK_LABEL = "on tasks Knos funded itself"
TASK_COUNTERS = {"reproduce": "reproductions", "shadow": "shadow_counts", "fund": "funders", "install": "repositories", "judge": "judges"}
TASK_DEFINITIONS = {
    "reproductions": "GitHub-signed reproduction reports filed by accounts that are not Knos's",
    "shadow_counts": "published shadow counts of a repository whose owner is not Knos's",
    "funders": "accounts that are not Knos's and funded a task in a repository of their own",
    "repositories": "repositories that are not Knos's with the check installed and one finished run",
    "judges": "accounts that are not Knos's and hosted a judge whose run GitHub signed",
}


def task_counts(done: list[dict] | None, own: frozenset, own_wallets: frozenset = frozenset()) -> dict:
    """Each counter the five task kinds can move (src/knos/tasks.py KINDS), counted from accepted evidence rows:
    {"kind", "accepted": True, "actor_id": the GitHub id that did it, "wallet": optional, "repository_owner_id": optional}.
    A row counts only when it was accepted, its actor is a real account that is not Knos's, and (when it names them) its
    wallet and its repository's owner are not Knos's either. One account moves one counter once. `done` None: nothing
    was read, and every number is None, never 0. These are apart from `count` above and are never added to it."""
    out: dict = {"measured": done is not None, "label": TASK_LABEL, "summed": False, "definitions": TASK_DEFINITIONS,
                 **{name: None for name in TASK_COUNTERS.values()}}
    if done is None:
        return out
    seen: dict[str, set[int]] = {name: set() for name in TASK_COUNTERS.values()}
    for row in done:
        if not isinstance(row, dict) or row.get("accepted") is not True or row.get("kind") not in TASK_COUNTERS:
            continue
        actor = row.get("actor_id")
        if not isinstance(actor, int) or isinstance(actor, bool) or actor <= 0 or actor in own:
            continue
        if row.get("wallet") in own_wallets or int(row.get("repository_owner_id") or 0) in own:
            continue
        seen[TASK_COUNTERS[row["kind"]]].add(actor)
    out.update({name: len(who) for name, who in seen.items()})
    return out


# ---- pull requests strangers sent to funded tasks: counted from the forge and the chain, apart from the three above --------------
PULL_DEFINITIONS = {
    "received": "pull requests opened by accounts that are not Knos's that name (Closes #N) an issue a job or work order held money for",
    "merged": "of those, the ones the forge says were merged",
    "paid": "of those, the ones whose author the chain says was paid by the job on an issue the pull request names",
    "accounts": "distinct accounts that opened the received ones",
    "payees": "distinct accounts among the paid ones: each is an outside PAYEE. None is an outside funder: the task's money was Knos's",
}
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.I)


def named_issues(pull: dict) -> set[int]:
    """The issues a pull request's description says it closes."""
    return {int(n) for n in _CLOSES.findall(str(pull.get("body") or ""))}


def pulls(forge_pulls: list[dict] | None, jobs: list[dict] | None, own: frozenset, repo: int | None = None) -> dict:
    """Outside pull requests on funded tasks of ONE repository. `forge_pulls`: the forge's list of its pull requests
    (number, user.id, merged_at, body), None when the forge was not read. `jobs`: the chain's jobs and work orders
    (knos.records), None when the chain was not read; `repo`: that repository's id there (None: every job given is its).
    A number that was not read is None, never 0. `funders` is always 0 here and says why: paying a stranger for a task
    Knos funded makes an outside payee."""
    out: dict = {"measured": forge_pulls is not None and jobs is not None, "received": None, "merged": None, "paid": None, "accounts": None,
                 "payees": None, "funders": 0, "summed": False, "definitions": PULL_DEFINITIONS}
    if forge_pulls is None or jobs is None:
        return out
    mine = [j for j in jobs if repo is None or j.get("repo") == repo]
    funded = {int(j["issue"]) for j in mine if j.get("issue")}
    paid_to: dict[int, set[int]] = {}
    for j in mine:
        if _paid(j) and j.get("issue"):
            paid_to.setdefault(int(j["issue"]), set()).update(int(i) for i in (j.get("payees") or [j.get("payee") or 0]) if i)
    got = [(p, named_issues(p) & funded) for p in forge_pulls if isinstance(p, dict)]
    got = [(p, on) for p, on in got if on and int((p.get("user") or {}).get("id") or 0) not in own | {0}]
    author = lambda p: int(p["user"]["id"])  # noqa: E731
    paid = [p for p, on in got if any(author(p) in paid_to.get(n, ()) for n in on)]
    out.update(received=len(got), merged=sum(1 for p, _ in got if p.get("merged_at")), paid=len(paid), accounts=len({author(p) for p, _ in got}),
               payees=len({author(p) for p in paid}))
    return out
