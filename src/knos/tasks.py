"""knos task: take a funded test task and be paid when the pull request is merged. Test USDC, no monetary value.

    knos task list [--board FILE|URL] [--json]            the open funded tasks, as the site publishes them (tasks.json)
    knos task show REF                                     one task: the amount, the acceptance terms, how payment happens
    knos task take REF --address A [--login L --branch B]  the steps: the file to edit, the pull request link, the comment
                                                           that binds where the payment goes. Sends nothing
    knos task submit REF --address A --login L --branch B [--send]
                                                           the same two things made ready; with --send, `gh` opens the pull
                                                           request and posts the comment as you
    knos task why OWNER/REPO#N [--pull M]                  one sentence: why a merged pull request was not paid, and what fixes it
    knos task kinds [--json]                               the tasks that are not code puzzles, each with its evidence

REF is a task's issue number on the board, its slug, or owner/repo#number.

WHERE THE TASKS COME FROM. One public file, tasks.json on the Knos site, which `scripts/task_board.py status --json`
writes when the site is built. Nothing here reads a chain to list a task; `why` reads the chain, because only the chain
says which workflows an order was funded through.

WHAT PAYS. A maintainer merges a pull request that passes the task's check; the merge pays the author's GitHub account.
The payment goes to the wallet bound to that account, else to the address in the author's own `/knos address` comment
on the pull request, else it is HELD for the account until it binds one (ADDRESS_LINE is the one instruction).

WHY A MERGED PULL REQUEST IS NOT PAID (`why`, `explain`). An order names, when it is funded, the one commit of the one
workflow repository whose signed run may pay it. An order funded through another copy of the workflows (a staging
copy) names that copy: the public worker's run is signed for the public workflows, so the program refuses it. The
task board therefore funds only where the repository calls the public pinned workflows (`scripts/task_board.py`,
`unpinned`), and `explain` says so when it finds an order that names another.

TASKS THAT ARE NOT CODE PUZZLES (KINDS; tasks/outside/<kind>.json holds the same text). Each has evidence a
machine checks (`accepts`) and one counter it can move. `keyholder` counts an OFFER of a key, never a holder: a key
is held only once the multisig seats it (docs/KEYHOLDER.md). `witness` is the whole transaction, end to end, in a
repository of the stranger's own (examples/witnessed). A counter moves only when the account that did it is not one
of Knos's own (scripts/own_github_ids.json; scripts/outsiders.py `task_counts` counts, never this module). Every one is
paid in test USDC from a task Knos funded itself, and every count that comes from them carries that label. None is an
offer of work or of money: test USDC cannot be exchanged for anything.

This module imports nothing outside the standard library until `why` reads a chain.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any, Callable

SITE = "https://drexthealpha.github.io/Knos"
BOARD = SITE + "/tasks.json"
FIRST = "Test USDC, no monetary value."
PUBLIC_WORKFLOWS = "drexthealpha/knos-workflows"       # the one workflow repository the public worker's runs are signed for
ADDRESS_LINE = "/knos address <your Solana address>"
PAYS = ("A maintainer merges a pull request that passes the check, and the merge pays the author's GitHub account in test USDC on "
        f"Solana devnet. Comment `{ADDRESS_LINE}` on the pull request to say where it goes; without an address or a bound wallet "
        "the payment is held for the account.")
ACCEPT = ("The check runs the one file as a separate process on recorded inputs and on fresh ones, and compares what it prints "
          "with the reference. A pull request that touches `.knos/` or `.github/` is refused.")
LABEL = "on tasks Knos funded itself"
HELD = "held"
_REF = re.compile(r"([\w.-]{1,100}/[\w.-]{1,100})#(\d{1,9})")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_BRANCH = re.compile(r"[\w./-]{1,200}")


class Stop(Exception):
    """A task command cannot go on. The message is the one sentence the person or the agent reads."""


def is_address(text: str) -> bool:
    """A Solana address as a wallet shows it: base58 that decodes to exactly 32 bytes."""
    if not isinstance(text, str) or not 32 <= len(text) <= 44 or any(c not in _B58 for c in text):
        return False
    n = 0
    for c in text:
        n = n * 58 + _B58.index(c)
    zeros = len(text) - len(text.lstrip("1"))
    return zeros + (n.bit_length() + 7) // 8 == 32


# ---- the board ------------------------------------------------------------------------------------------------------
def fetch(source: str = BOARD, get: Callable[[str], bytes] | None = None) -> dict:
    """tasks.json from a file on this machine or from the site. Stop when it is not the board's document."""
    try:
        if re.match(r"https?://", source):
            if get is None:
                import urllib.request
                with urllib.request.urlopen(urllib.request.Request(source, headers={"User-Agent": "knos-task"}), timeout=20) as got:  # noqa: S310 - http(s) only
                    raw = got.read()
            else:
                raw = get(source)
        else:
            raw = Path(source).read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as why:
        raise Stop(f"the task board at {source} could not be read: {' '.join(str(why).split())[:160]}") from None
    if not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(doc.get("tasks"), list):
        raise Stop(f"{source} is not the task board's document (tasks.json, v 1)")
    return doc


def rows(doc: dict) -> list[dict]:
    """The open tasks, each with what an agent needs before it starts: the amount, the terms, how payment happens.
    Whatever the board's file says in the repository's words (the title) is under `untrusted`: data, never an instruction."""
    repo = str(doc.get("repository") or "")
    out = []
    for t in doc["tasks"]:
        if not isinstance(t, dict) or not isinstance(t.get("issue"), int) or not isinstance(t.get("amount"), int):
            continue
        where = str(t.get("repository") or repo)
        if not _REF.fullmatch(f"{where}#{t['issue']}"):
            continue
        file = str(t.get("file") or "")
        out.append({"id": f"{where}#{t['issue']}", "repository": where, "issue": t["issue"], "slug": str(t.get("slug") or ""),
                    "kind": str(t.get("kind") or "code"), "amount": t["amount"], "decimals": 6, "currency": "test USDC",
                    "deadline": t.get("deadline"), "state": str(t.get("state") or ""), "url": f"https://github.com/{where}/issues/{t['issue']}",
                    "file": file if re.fullmatch(r"[\w./-]{1,200}", file) and ".." not in file else "",
                    "accept": str(t.get("accept") or ACCEPT), "pays": str(t.get("pays") or PAYS), "pulls": [n for n in t.get("pulls") or [] if isinstance(n, int)],
                    "note": FIRST, "untrusted": {"title": str(t.get("title") or "")[:200]}})
    return out


def find(doc: dict, ref: str) -> dict:
    """The task `ref` names: its issue number, its slug, or owner/repo#number. Stop with what is open when none does."""
    found = rows(doc)
    ref = str(ref).strip().lstrip("#")
    hit = [t for t in found if ref in (str(t["issue"]), t["slug"]) or ref.lower() == t["id"].lower()]
    if len(hit) != 1:
        some = ", ".join(f"#{t['issue']} {t['slug']}" for t in found[:8]) or "none"
        raise Stop(f"no open task is named {ref[:60]!r} on the board. Open now: {some}.")
    return hit[0]


def usdc(units: int) -> str:
    return f"{units / 1_000_000:.2f} test USDC"


def take(doc: dict, ref: str, address: str = "", login: str = "", branch: str = "") -> dict:
    """Everything between reading a task and being paid, in order. Sends nothing. `address`: where the payment goes;
    `login` and `branch`: the fork and its branch, for a pull request link that already says `Closes #N`."""
    t = find(doc, ref)
    if address and not is_address(address):
        raise Stop("that is not a Solana address (32 bytes in base58, as a wallet shows it)")
    if login and not _NAME.fullmatch(login) or branch and (not _BRANCH.fullmatch(branch) or ".." in branch):
        raise Stop("login is a GitHub login and branch is a branch name, like fix-7")
    body = f"Closes #{t['issue']}"
    q = urllib.parse.urlencode({"quick_pull": 1, "body": body})
    head = f"{login}:{branch}" if login and branch else "<your login>:<your branch>"
    comment = f"/knos address {address}" if address else ADDRESS_LINE
    steps = [f"Edit {t['file'] or 'the one file the task names'} in a fork of {t['repository']}: https://github.com/{t['repository']}/fork",
             f"Open the pull request with `{body}` in its description: https://github.com/{t['repository']}/compare/main...{head}?{q}",
             f"Comment `{comment}` on your pull request: that is where the payment goes.",
             "A maintainer merges a pull request that passes the check. The merge pays."]
    return {"task": t, "sent": False, "pull_request": {"repository": t["repository"], "base": "main", "head": head, "body": body,
                                                       "url": f"https://github.com/{t['repository']}/compare/main...{head}?{q}"},
            "address_comment": comment, "bound": bool(address), "steps": steps,
            "held_without_address": f"With no address and no bound wallet the payment is held for your account. One comment releases it: `{ADDRESS_LINE}`.",
            "note": FIRST}


def submit(doc: dict, ref: str, address: str, login: str, branch: str, send: bool = False, run: Callable | None = None) -> dict:
    """`take` with every blank filled; with `send`, `gh` opens the pull request and posts the address comment as the
    account `gh` is logged in as. `run(argv)` returns (exit code, what it printed): tests give it."""
    if not (address and login and branch):
        raise Stop("submit needs --address, --login and --branch: the pull request and the address comment are made from them")
    out = take(doc, ref, address, login, branch)
    if not send:
        return out
    if run is None:
        import subprocess

        def run(argv):
            got = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=120)   # noqa: S603 - a fixed argv, no shell
            return got.returncode, (got.stdout or got.stderr).strip()
    t, pr = out["task"], out["pull_request"]
    code, said = run(["gh", "pr", "create", "--repo", t["repository"], "--base", "main", "--head", pr["head"], "--title",
                      f"Task #{t['issue']}" + (f": {t['slug']}" if t["slug"] else ""), "--body", pr["body"]])
    url = next((w for w in reversed(said.split()) if re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+", w)), "")
    if code != 0 or not url:
        raise Stop(f"gh did not open the pull request ({' '.join(said.split())[:160] or 'it said nothing'}). Nothing else was sent.")
    code, said = run(["gh", "pr", "comment", url, "--body", out["address_comment"]])
    if code != 0:
        raise Stop(f"the pull request is open at {url}, and gh did not post the address comment. Post it yourself: `{out['address_comment']}`")
    return {**out, "sent": True, "pull_request": {**pr, "url": url}, "posted": [pr["body"], out["address_comment"]]}


# ---- why a merged pull request was not paid -----------------------------------------------------------------------------
def repo_hash(repository: str) -> bytes:
    """What an order stores of the workflow repository it names (knos.settle.v2.pay.wf_repo_hash)."""
    return hashlib.sha256(repository.encode()).digest()


def explain(f: dict) -> dict:
    """One sentence and one fix from facts already read. `f`: where ("owner/repo#N"), merged (bool or None: not read),
    closes (whether the pull request's description names the issue), orders ([{state, wf_public (the order names the
    public workflow repository), wf_sha, called (the repository's default branch calls that commit; None: not read),
    past (its deadline is over), payee (login the money is held for)}]), pull (the pull request's number, or None).
    Returns {"code", "said", "fix"}: the first thing that stands in the way, in the order money meets them."""
    where, pull = f.get("where") or "the issue", f.get("pull")
    the = f"pull request #{pull}" if pull else "the pull request"
    merged = f"the merged pull request #{pull}" if pull else "the merged pull request"
    tip = f"A maintainer comments `/knos tip <amount>` on {merged}"
    orders = [o for o in f.get("orders") or [] if isinstance(o, dict)]

    def out(code: str, said: str, fix: str) -> dict:
        return {"code": code, "said": said, "fix": fix, "note": FIRST}
    held = next((o for o in orders if o.get("state") == HELD), None)
    if held:
        who = f"@{held['payee']}" if held.get("payee") else "its payee"
        return out("held", f"The payment for {where} is held for {who}: no wallet is bound to that account and no address comment counted.",
                   f"{who} comments `{ADDRESS_LINE}` on {the}, or binds a wallet with `knos claim <address>`; then anyone comments `/knos settle`.")
    if not orders:
        return out("unfunded", f"Nothing is in escrow for {where}, so a merge had nothing to pay.", f"{tip}: a tip is funded and paid after the merge.")
    live = [o for o in orders if o.get("state") == "open"]
    if not live:
        states = ", ".join(sorted({str(o.get("state")) for o in orders}))
        return out("closed", f"The money for {where} is no longer open ({states}): it was paid or went back before this pull request could take it.",
                   f"`/knos status` on the issue says where it went; {tip[0].lower() + tip[1:]} to pay this work anyway.")
    if f.get("merged") is False:
        return out("unmerged", f"{the[0].upper() + the[1:]} is not merged, and a merge is what pays {where}.", "A maintainer merges it once the check passes.")
    if f.get("closes") is False:
        return out("unnamed", f"{the[0].upper() + the[1:]} does not name {where} in its description.",
                   f"{tip}; next time the description says `Closes #<issue>` before the merge.")
    o = live[0]
    if not o.get("wf_public") or o.get("called") is False:
        via = (f"commit {str(o.get('wf_sha') or '')[:12]} of the public workflows, which the repository no longer calls" if o.get("wf_public")
               else "a copy of the workflows that is not the public one (a staging copy)")
        return out("pin", f"The order on {where} was funded through {via}, so the public worker's signed run cannot pay it.",
                   f"{tip}; the old order goes back to its funder at its deadline. "
                   f"Fund the next task only where the repository calls {PUBLIC_WORKFLOWS} at the published commit.")
    if o.get("past"):
        return out("late", f"The order on {where} is past its deadline: it pays nobody now and goes back to its funder.", f"{tip}.")
    return out("retry", f"Nothing read here stands in the way of {where}: the order is open, funded through the public workflows, and in time.",
               f"Comment `/knos settle` on {merged}: it tries the payment again and says what a check or the chain refused.")


def facts(where: str, orders: list, now: int, *, pull: dict | None = None, uses: list | None = None, logins: dict | None = None) -> dict:
    """`explain`'s facts from what was read: `orders` are knos.settle.v2.pay Orders or Jobs on the issue (any state),
    `pull` the pull request as GitHub gives it (None: not read), `uses` the (file, repository, workflow, commit) rows of
    the reusable workflows the default branch calls (None: not read), `logins` {GitHub id: login} for a held payee."""
    m = _REF.fullmatch(where)
    issue = int(m.group(2)) if m else 0
    public = repo_hash(PUBLIC_WORKFLOWS)
    rows_ = []
    for o in orders:
        is_public = bytes(o.wf_repo_hash) == public
        called = None if uses is None else any(repo_hash(u[1]) == bytes(o.wf_repo_hash) and u[3] == o.wf_sha for u in uses)
        rows_.append({"state": o.state, "wf_public": is_public, "wf_sha": o.wf_sha, "called": called, "past": o.state == "open" and o.deadline <= now,
                      "payee": (logins or {}).get(getattr(o, "payee_id", 0), "")})
    closes = None
    if isinstance(pull, dict):
        closes = bool(re.search(rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#{issue}\b", str(pull.get("body") or ""), re.I))
    return {"where": where, "pull": pull.get("number") if isinstance(pull, dict) else None,
            "merged": bool(pull.get("merged") or pull.get("merged_at")) if isinstance(pull, dict) else None, "closes": closes, "orders": rows_}


def why(where: str, pull: int | None = None, server: Any = None) -> dict:
    """Read the chain and GitHub for one issue and explain. `server`: a knos.mcp.Server (tests give one made of dictionaries)."""
    from . import mcp
    from .settle.v2 import pay, relay
    m = _REF.fullmatch(where)
    if not m:
        raise Stop("name the issue as owner/repo#number, e.g. octo/widgets#25")
    repo, issue = m.group(1), int(m.group(2))
    s = server or mcp.Server()
    try:
        info, jobs, _old, now = s._on(repo, issue)
        repo_id = int(info["id"])
        found = [j for _a, j in jobs]
        for state in (1, 3, 4):
            found += [o for _a, o in s._chain(lambda ledger, state=state: relay.orders(ledger, state)) if o.repo_id == repo_id and o.issue == issue]
        page = s._ask(f"repos/{repo}/pulls/{int(pull)}") if pull else None
        try:
            uses = s._workflows(repo, urllib.parse.quote(str(info.get("default_branch") or "main"), safe=""))
        except mcp.Failed:
            uses = None
        logins: dict = {}
        for o in found:
            if o.state == HELD and o.payee_id:
                try:
                    logins[o.payee_id] = str(s._ask(f"user/{int(o.payee_id)}")["login"])
                except (mcp.Failed, KeyError, TypeError):
                    pass
    except mcp.Failed as no:
        raise Stop(str(no)) from None
    assert pay.wf_repo_hash(PUBLIC_WORKFLOWS) == repo_hash(PUBLIC_WORKFLOWS)
    return explain(facts(where, found, now, pull=page if isinstance(page, dict) else None, uses=uses, logins=logins))


# ---- tasks that are not code puzzles ---------------------------------------------------------------------------------
def _kind(title: str, do: str, evidence: str, counter: str, needs: tuple[str, ...], doc: str) -> dict:
    return {"v": 1, "title": title, "statement": f"{FIRST}\n\n{do}", "evidence": evidence, "counter": counter, "needs": list(needs),
            "counted_when": f"the account that did it is not one of Knos's own (scripts/own_github_ids.json); shown as \"{LABEL}\"",
            "amount": 5_000_000, "currency": "test USDC", "doc": doc}


KINDS: dict[str, dict] = {
    "reproduce": _kind("Reproduce what Knos says, in your own fork",
                       "Make a repository from the knos-task template, run the `knos reproduce` workflow there, and open a pull request that files the report GitHub signed.",
                       "a file under reproductions/ whose GitHub-signed token names your account and the report's hash (knos.reproduce.verified accepts it)",
                       "reproductions", ("actor_id", "verified", "file"), "docs/REPRODUCE.md"),
    "shadow": _kind("Count one invoice against GitHub's record, in a repository you own",
                    "Run `knos shadow` on agent pull requests of a repository you own and publish the statement it writes.",
                    "a published statement (knos.shadow) whose repository's owner is your account, with at least one line and its digest",
                    "shadow_counts", ("actor_id", "repository_owner_id", "lines", "digest", "url"), "docs/SHADOW.md"),
    "fund": _kind("Fund a test task yourself, from the faucet",
                  "Ask the faucet for test USDC, install the workflow in a repository you own, and fund one issue there with `/knos fund 5`.",
                  "a funded job or work order on Solana devnet in a repository that is not Knos's, funded by your account or wallet (scripts/outsiders.py funder_of says outside)",
                  "funders", ("actor_id", "repository_owner_id", "funded_tx"), "docs/FAUCET.md"),
    "install": _kind("Install the check in a repository you own",
                     "Add the check workflow to a repository you own and let it finish once on a pull request.",
                     "a repository your account owns whose default branch calls the public pinned check workflow, and one finished run of it",
                     "repositories", ("actor_id", "repository_owner_id", "calls_public_check", "finished_runs"), "docs/INSTALL.md"),
    "judge": _kind("Host a judge",
                   "Make a repository from the host-a-judge template (examples/host_a_judge) and let it judge one order: GitHub signs your run, not Knos's.",
                   "one GitHub-signed attestation run in a repository your account owns, of the workflow the template installs (.github/workflows/knos-attest.yml, a copy of examples/knos-attest.yml)",
                   "judges", ("actor_id", "repository_owner_id", "workflow", "signed_run"), "examples/host_a_judge"),
    "compose": _kind("Read the verifier from a program of your own",
                     "Build a Solana program on the published crate `knos-oidc-interface = \"0.3.14\"` (examples/reader_template is a "
                     "complete one), deploy it to devnet, and send one transaction in which it reads a token knos-oidc verified.",
                     "one devnet transaction of a program your account deployed whose accounts include a token account owned by knos-oidc "
                     "(FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W), and the program's source naming knos-oidc-interface 0.3.14",
                     "programs", ("actor_id", "program_id", "tx", "reads_verifier", "crate", "source"), "examples/reader_template"),
    "gate": _kind("Put a program of yours behind the upgrade gate",
                  "Make your gate with `examples/upgrade_gate/adopt.py init`, deploy it to devnet, give your program's upgrade "
                  "authority to a Squads multisig, and let your build workflow record one build.",
                  "a devnet transaction in which your gate wrote the record [\"build\", program, executable hash] on a token "
                  "from a workflow of a repository your account owns, and `adopt.py check` on the program exiting 0",
                  "gates", ("actor_id", "repository_owner_id", "program_id", "gate_id", "record_tx", "checked"), "docs/GATE.md"),
    "keyholder": _kind("Offer to hold one key of the upgrade multisig",
                       "Open the Key holder request issue (.github/ISSUE_TEMPLATE/key_holder.md) on drexthealpha/Knos with your public "
                       "key, a name or handle, and how to reach you. An offer is counted as an offer; a key is held only once it is seated.",
                       "an issue your account opened on drexthealpha/Knos from the key holder template, naming a Solana public key",
                       "key_offers", ("actor_id", "issue", "public_key", "contact"), "docs/KEYHOLDER.md"),
    "tamper": _kind("Fool the judge on a task",
                    "Write a submission meant to make the judge accept work that does not do what the task asks. If the judge "
                    "accepts it, the cheat joins the tamper set as a case written outside Knos. If the judge refuses it, nothing is paid.",
                    "a pull request of yours on a funded task whose judge verdict was accepted, and a maintainer's note that the "
                    "accepted work does not do what the task asks (docs/TAMPER.md)",
                    "outside_cheats", ("actor_id", "task", "submission", "verdict", "why_wrong"), "docs/TAMPER.md"),
    "witness": _kind("Witness one transaction from start to end",
                     "In a repository of your own, run examples/witnessed/witness.py: fix terms and a budget with faucet test USDC, "
                     "submit failing work, then passing work, make the buyer's and the supplier's statements, try a replay, get paid, "
                     "and check the archive with the stand-alone verifier.",
                     "the public record witness.py writes (witness.json): each step's link, the payment's transaction, the replay "
                     "refused, both statements with one hash, and the verifier's result",
                     "witnessed", ("actor_id", "repository_owner_id", "funded_tx", "failed_run", "paid_tx", "replay_refused",
                                   "statements_agree", "verified"), "examples/witnessed"),
}
COUNTERS = {k: v["counter"] for k, v in KINDS.items()}
OIDC_PROGRAM = "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W"      # knos-oidc on devnet (knos_oidc_interface::ID)
CRATE = "knos-oidc-interface 0.3.14"                                # the published crate a `compose` program builds on


def accepts(kind: str, e: dict) -> tuple[bool, str]:
    """Whether evidence `e` meets the task `kind`: (yes, "") or (no, the one thing missing). It checks the shape of what
    was read by whoever gathered it (a signed file verified, a run listed by the forge); it never decides who is outside."""
    if kind not in KINDS:
        return False, f"there is no task kind {kind!r}: {', '.join(KINDS)}"
    if not isinstance(e, dict):
        return False, "the evidence is not an object"
    missing = [k for k in KINDS[kind]["needs"] if e.get(k) in (None, "", 0, False, [])]
    if missing:
        return False, f"the evidence lacks {missing[0]}"
    if not isinstance(e.get("actor_id"), int) or e["actor_id"] <= 0:
        return False, "actor_id is the GitHub id of the account that did it"
    if "repository_owner_id" in KINDS[kind]["needs"] and e["repository_owner_id"] != e["actor_id"]:
        return False, "the repository is not the account's own"
    if kind == "reproduce" and not re.fullmatch(r"reproductions/[\w.-]+\.json", str(e["file"])):
        return False, "the report is one file directly under reproductions/"
    if kind in ("compose", "gate") and not is_address(str(e["program_id"])) or kind == "gate" and not is_address(str(e["gate_id"])):
        return False, "a program is named by its Solana address"
    if kind == "compose" and (str(e["program_id"]) == OIDC_PROGRAM or " ".join(str(e["crate"]).replace("=", " ").replace('"', " ").split()) != CRATE):
        return False, f"the program is your own and builds on the published crate {CRATE}"
    if kind == "keyholder" and not is_address(str(e["public_key"])):
        return False, "the public key is a Solana address (32 bytes in base58)"
    if kind == "keyholder" and e.get("seated"):
        return False, "a seated key is counted by the multisig, not as an offer"
    if kind == "tamper" and e["verdict"] != "accepted":
        return False, "the judge refused it: only a cheat the judge accepted is paid"
    if kind == "witness" and e.get("payments", 1) != 1:
        return False, "the replay made a second payment: the record shows more than one"
    if kind == "judge" and not str(e["workflow"]).endswith("knos-attest.yml"):       # knos.host_judge.WORKFLOW_PATH (tests/test_tasks.py holds the two together)
        return False, "the run is not the template's attest workflow"
    return True, ""


def kind_file(kind: str) -> str:
    """tasks/outside/<kind>.json, byte for byte."""
    return json.dumps({"kind": kind, **KINDS[kind]}, indent=1, ensure_ascii=False) + "\n"


# ---- the command line -----------------------------------------------------------------------------------------------------
def lines(t: dict) -> list[str]:
    return [f"#{t['issue']} {t['slug'] or t['kind']}: {usdc(t['amount'])}, until {str(t['deadline'] or 'not read')[:10]} ({t['id']})",
            f"  accept: {t['accept']}", f"  pays:   {t['pays']}", f"  open:   {t['url']}"]


def register(app, help_lines: list | None = None) -> None:
    """`knos task ...` on the command line (typer is named here only: an MCP session never loads it)."""
    import importlib
    typer = importlib.import_module("typer")
    sub = typer.Typer(no_args_is_help=True, help="Take a funded test task; the merge pays. Test USDC, no monetary value.")
    board = typer.Option(BOARD, "--board", help="tasks.json: a file or a URL")

    def said(fn):
        try:
            return fn()
        except Stop as no:
            typer.echo(f"knos task: {no}")
            raise typer.Exit(1) from None

    def show_(got: dict, as_json: bool, words: list[str]) -> None:
        typer.echo(json.dumps(got, indent=1, ensure_ascii=False) if as_json else "\n".join(words))

    @sub.command("list")
    def _list(board: str = board, as_json: bool = typer.Option(False, "--json")) -> None:
        """The open funded tasks."""
        found = said(lambda: rows(fetch(board)))
        show_({"tasks": found, "note": FIRST}, as_json, [FIRST] + [x for t in found for x in lines(t)[:1]] + ([] if found else ["No task is open on the board now."]))

    @sub.command("show")
    def _show(ref: str, board: str = board, as_json: bool = typer.Option(False, "--json")) -> None:
        """One task: the amount, the acceptance terms, how payment happens."""
        t = said(lambda: find(fetch(board), ref))
        show_(t, as_json, [FIRST] + lines(t))

    @sub.command("take")
    def _take(ref: str, address: str = typer.Option("", "--address"), login: str = typer.Option("", "--login"), branch: str = typer.Option("", "--branch"),
              board: str = board, as_json: bool = typer.Option(False, "--json")) -> None:
        """The steps from here to paid. Sends nothing."""
        got = said(lambda: take(fetch(board), ref, address, login, branch))
        show_(got, as_json, [FIRST] + [f"{n}. {s}" for n, s in enumerate(got["steps"], 1)] + ([] if address else [got["held_without_address"]]))

    @sub.command("submit")
    def _submit(ref: str, address: str = typer.Option("", "--address"), login: str = typer.Option("", "--login"), branch: str = typer.Option("", "--branch"),
                send: bool = typer.Option(False, "--send", help="open the pull request and post the comment with gh, as you"),
                board: str = board, as_json: bool = typer.Option(False, "--json")) -> None:
        """The pull request and the address comment, made ready; --send posts both."""
        got = said(lambda: submit(fetch(board), ref, address, login, branch, send))
        show_(got, as_json, [FIRST, f"Pull request: {got['pull_request']['url']}", f"Comment on it: {got['address_comment']}",
                             "Both were posted as your account." if got["sent"] else "Nothing was sent. With --send, gh posts both as you."])

    @sub.command("why")
    def _why(where: str, pull: int = typer.Option(0, "--pull", help="the merged pull request's number"), as_json: bool = typer.Option(False, "--json")) -> None:
        """Why a merged pull request was not paid, and what fixes it."""
        got = said(lambda: why(where, pull or None))
        show_(got, as_json, [got["said"], f"Fix: {got['fix']}"])

    @sub.command("kinds")
    def _kinds(as_json: bool = typer.Option(False, "--json")) -> None:
        """The tasks that are not code puzzles."""
        show_(KINDS, as_json, [FIRST] + [f"{k}: {v['title']}. Evidence: {v['evidence']}. Counter: {v['counter']} ({LABEL})." for k, v in KINDS.items()])

    if help_lines is not None:
        help_lines.append(("task", "For money", "Take a funded test task; the merge pays. Why a merged pull request was not paid."))
    app.add_typer(sub, name="task", rich_help_panel="For money")
