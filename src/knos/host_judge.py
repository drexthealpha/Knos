"""Host a judge: an account that is neither the buyer nor the supplier runs the neutral evaluator in a repository of
its own, and a receipt then says more than `reported`.

Why it matters. A receipt's assurance level (knos.receipt.assurance_of) is computed from account ids GitHub signed:

    reported   the default. Every evaluator that spoke is the order's own repository, or is owned or was started by a
               payee, or read the check results without running the suite.
    rerun      one evaluator outside the order's repository, whose owner and starter are not a payee (nor declared one
               party with a payee), ran the pinned suite itself.
    agreed     two such evaluators with different owners and starters each ran it, and the verdict is accepted.

While one account funds, delivers and evaluates, the level stays `reported`. A host changes that, and needs two
minutes: a repository made from the template (`template_link`), which holds examples/knos-attest.yml and nothing
else, and one press of "Run workflow". The host needs no secret, no wallet and no key.

Two ways an order reaches a host's repository (both exist in knos_pay 2.1; this module adds no rule):

    a neutral run       any order funded without `neutral off`. The host presses Run workflow for the merged pull
                        request. The program takes the run when the account that started it owns the repository.
    the named judge     `/knos fund 20 checks: unit quorum 2 judge: <host>/knos-judge` (`fund_line`). The order then
                        pays only after that repository's run and the order's own have passed the same commit.

What the level does NOT follow from: the order's own repository never raises it (the buyer chose it and its
administrators can accept), and an order paid on the merge has no suite to run, so a host's run of it reads GitHub's
record and the receipt stays `reported`. `reads` says which level a set of accounts would give, by calling the
receipt's own function: nothing here decides a level.

`python -m knos.host_judge link | editor | level | says`. No outside account has hosted a judge yet.
"""
from __future__ import annotations

import re
from urllib.parse import quote

TEMPLATE = "drexthealpha/knos-attest"                    # the template repository: it holds examples/knos-attest.yml
WORKFLOW_PATH = ".github/workflows/knos-attest.yml"
NAME = "knos-judge"                                      # what the host's repository is called unless they say otherwise
URL_LIMIT = 8191                                         # the longest link GitHub's editor takes (web/install.js)
_REPO = re.compile(r"(?:https://github\.com/)?([A-Za-z0-9](?:-?[A-Za-z0-9]){0,38})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?\Z")

PAID = ("The host is paid nothing by the order: knos_pay has no judge's share. The only money a run can bring is the "
        "relayer's tip, 0.05 test USDC out of the fee (0.30 when the paying transaction creates a payee's token "
        "account), and it goes to whoever paid for the paying transaction. A host who also runs `knos relay` with a "
        "fee payer of their own gets that tip when theirs is the transaction that pays; a host who does not gets nothing.")
CAN = ("start the run, or not start it: an order that names the host's repository in a quorum is then refunded at its deadline",
       "run the order's pinned acceptance suite on the two commits, in the minutes of their own repository",
       "delete the repository: receipts already written stay valid, and no later order can name it")
CANNOT = ("get anything signed that GitHub's public record of the pull request does not support: the run is Knos's "
          "attest.yml at the commit the order pinned when it was funded, and the caller's file decides only when it runs",
          "choose or change who is paid, how much, the terms or the deadline",
          "move, hold or see the order's money: no instruction of the program takes a key of the host's",
          "raise a receipt's level for work they are paid for: a host who is a payee, or is declared one party with "
          "a payee, counts as the supplier",
          "count twice: two repositories of one owner, or two runs one account started, are one evaluator")


def parse(spec: str) -> tuple[str, str] | None:
    """("owner", "name") from owner/name or the repository's address; None otherwise."""
    m = _REPO.match(str(spec or "").strip())
    return (m.group(1), m.group(2)) if m and m.group(2) not in (".", "..") else None


def template_link(name: str = NAME) -> str:
    """The one click: GitHub's "create a repository from this template" form, filled in, public, in the account of
    whoever follows it (the same form of link web/task.js writes for the task template)."""
    owner, repo = TEMPLATE.split("/")
    return f"https://github.com/new?template_owner={owner}&template_name={repo}&name={quote(name, safe='')}&visibility=public&owner=@me"


def short(text: str) -> str:
    """A workflow file without its comment lines and blank lines: what fits in a link. Trailing comments stay."""
    return "".join(line + "\n" for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def editor_link(spec: str, workflow: str, branch: str = "main") -> str | None:
    """The other click, for a host who has a repository already: GitHub's editor in it with the workflow filled in as
    a new file. None when `spec` is no repository or the link would be longer than GitHub takes."""
    at = parse(spec)
    if at is None:
        return None
    url = (f"https://github.com/{at[0]}/{at[1]}/new/{'/'.join(quote(p, safe='') for p in branch.split('/'))}"
           f"?filename={quote(WORKFLOW_PATH, safe='')}&value={quote(short(workflow), safe='')}")
    return url if len(url) <= URL_LIMIT else None


def run_link(spec: str) -> str | None:
    """Where the host presses "Run workflow"."""
    at = parse(spec)
    return None if at is None else f"https://github.com/{at[0]}/{at[1]}/actions/workflows/{WORKFLOW_PATH.rsplit('/', 1)[1]}"


def fund_line(amount: str, host: str, checks: str = "unit", quorum: int = 2) -> str:
    """The funding comment that names the host's repository as the order's judge. Raises ValueError in words."""
    at = parse(host)
    if at is None or quorum not in (2, 3) or not re.fullmatch(r"[0-9]{1,6}(\.[0-9]{1,2})?", str(amount)):
        raise ValueError("the line is `/knos fund <amount> checks: <names> quorum 2|3 judge: owner/name`: give an amount, the host's repository and a quorum of 2 or 3")
    return f"/knos fund {amount} checks: {checks} quorum {quorum} judge: {at[0]}/{at[1]}"


def entry(kind: str, claims: dict, buyers, sellers, verdict: dict | None = None) -> dict:
    """What a receipt records of one hosted judge: knos.receipt.evaluator on the claims GitHub signed for its run, with
    what the run's own verdict says of running the suite (knos.receipt.reexecution) when there is one."""
    from . import receipt
    return receipt.evaluator(kind, claims, buyers, sellers, None if verdict is None else receipt.reexecution(verdict))


def level(entries: list[dict], payees, declared=()) -> dict:
    """{level, says, same_controller, independence}: what knos.receipt.assurance_of makes of these evaluators' entries
    for an accepted result paid to `payees` (account ids). The receipt's function, not a copy of its rule."""
    from . import receipt
    got = receipt.assurance_of({"version": 3, "evaluator_observed": {"evaluators": list(entries)}, "payees": [{"github_id": int(p)} for p in payees]}, declared)
    same, said = receipt.independence_of(list(entries), got["declared_related"]) if entries else (False, "")
    return {"level": got["level"], "says": receipt.LEVEL_WORDS[got["level"]], "same_controller": same, "independence": said}


def reads(payees, hosts, buyers=(), declared=(), suite: bool = True) -> dict:
    """The level a receipt would read with these hosts, before anyone runs anything. `hosts`: account ids, each a
    personal account that owns its repository and starts the run itself (so owner and starter are one id). `suite`:
    whether the order is paid by its acceptance checks; an order paid on the merge gives a host nothing to run.
    Adds `why`: the one sentence a host or a buyer needs."""
    ran: dict = {"reexecuted": True, "assurance": "black-box", "environment": {}, "image_digest": None}
    read: dict = {"reexecuted": False, "assurance": None, "environment": {}, "image_digest": None}
    from . import receipt
    made = []
    for n, host in enumerate(hosts):
        claims = {"repository_id": 1 + n, "repository_owner_id": int(host), "actor_id": int(host), "runner_environment": "github-hosted"}
        made.append(receipt.evaluator("neutral" if n == 0 else "attestor", claims, buyers, payees, ran if suite else read))
    got = level(made, payees, declared)
    sellers = {int(p) for p in payees}
    why = {"agreed": "Two hosts with different owners, neither of them paid by this order, each ran the suite.",
           "rerun": "One evaluator the supplier does not control ran the suite." + (" The hosts given count as one: they share an owner, a starter or a declared relationship, or all but one are paid by this order." if len(hosts) > 1 else ""),
           "reported": ("Nobody hosts a judge for this order: only the order's own repository speaks." if not hosts else
                        "This order is paid on the merge: a host has no suite to run and reads GitHub's record." if not suite else
                        "Every host given is paid by this order, or is declared one party with someone who is.")}[got["level"]]
    return {**got, "why": why, "hosts_paid_by_the_order": sorted(int(h) for h in hosts if int(h) in sellers)}


def says() -> list[str]:
    """What a host is paid, can do and cannot do, as lines (examples/host_a_judge/README.md and docs/ATTESTOR.md say the same)."""
    return ["Paid: " + PAID, "A host can:", *("  - " + line for line in CAN), "A host cannot:", *("  - " + line for line in CANNOT)]


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(prog="python -m knos.host_judge", description="Host the neutral evaluator in a repository of your own: the links, and the level a receipt then reads.")
    sub = ap.add_subparsers(dest="what", required=True)
    one = sub.add_parser("link", help="the one click: a repository of your own from the template")
    one.add_argument("--name", default=NAME)
    ed = sub.add_parser("editor", help="for a repository you have already: GitHub's editor with the workflow filled in")
    ed.add_argument("repository", help="owner/name")
    ed.add_argument("--file", type=Path, default=Path("examples/knos-attest.yml"), help="the workflow file (examples/knos-attest.yml of a checkout)")
    ed.add_argument("--branch", default="main")
    lv = sub.add_parser("level", help="the level a receipt would read, from account ids")
    lv.add_argument("--payee", type=int, action="append", required=True, help="a payee's GitHub account id (repeat)")
    lv.add_argument("--host", type=int, action="append", default=[], help="a host's GitHub account id (repeat for a second host)")
    lv.add_argument("--related", action="append", default=[], help="ids the terms declare one party, as a,b (repeat)")
    lv.add_argument("--merge", action="store_true", help="the order is paid on the merge, not by an acceptance suite")
    sub.add_parser("says", help="what a host is paid, can do and cannot do")
    a = ap.parse_args(argv)
    try:
        if a.what == "link":
            print(template_link(a.name))
        elif a.what == "editor":
            link = editor_link(a.repository, a.file.read_text(encoding="utf-8"), a.branch)
            if link is None:
                raise ValueError("write the repository as owner/name (the link must also fit in 8,191 bytes)")
            print(link)
            print(run_link(a.repository))
        elif a.what == "level":
            got = reads(a.payee, a.host, declared=[[int(x) for x in g.split(",")] for g in a.related], suite=not a.merge)
            print(f"{got['level']}: {got['says']}. {got['why']}")
        else:
            print("\n".join(says()))
        return 0
    except (OSError, ValueError) as why:
        print(f"not done: {why}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
