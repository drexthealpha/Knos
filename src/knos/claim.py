"""`knos claim <address>`: one command that names the Solana address your GitHub account is paid at.

GitHub will sign "the owner of this repository names <address>" only from Knos's pinned claim workflow, in a run the
account's owner started by hand in a repository of their own named knos-claim, so the claim has to start there.
Binding is by hand only: a run started by hand (`workflow_dispatch`) with the address typed in is the one thing that
counts. In the browser that is: make the repository from the template, open Actions, run the workflow, type the
address, wait. `bind` does it with the `gh` command you are already logged in with:

    1. uses your `<login>/knos-claim`, made from the template drexthealpha/knos-claim the first time (public; it holds
       one workflow file)
    2. starts its workflow by hand with the address (`gh workflow run`); GitHub signs the token and the workflow posts
       it there
    3. waits for a relayer (Knos's public worker, or anyone) to carry it to Solana, and says what the relayer logged

From then on a merged pull request pays that address, and what was held for the account is sent there.

`bind_org` is the same for an ORGANISATION (`knos claim --org <organisation> <address>`): a payee that is an
organisation (a bot's pull request, a vendor's) is paid at the wallet a member names. The workflow file it puts in
`<organisation>/knos-claim` calls the pinned claim workflow with `kind: org`, and is started by hand by whoever is
logged in to `gh`: who may is the organisation's own rule (write access to that repository). The escrow never lets it
replace a wallet a person bound for his own account.

`claim` is the first deployment's (`knos claim --v1`): it sends what that deployment holds under your account to an
address, from a workflow of its own in the same repository.

Nothing here holds a key: the signed token names the address, and knos-pay sends a payment only to the address a verified
token named.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

TEMPLATE = Path(__file__).parent / "settle" / "knos-claim.yml"          # what a knos-claim repository runs
TEMPLATE_V1 = Path(__file__).parent / "settle" / "knos-claim-v1.yml"    # the first deployment's claim workflow
TEMPLATE_ORG = Path(__file__).parent / "settle" / "knos-claim-org.yml"  # what an organisation's knos-claim repository runs
TEMPLATE_REPO = "drexthealpha/knos-claim"
WORKFLOW = ".github/workflows/knos-claim.yml"
WORKFLOW_V1 = ".github/workflows/knos-claim-v1.yml"
ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
ABOUT = "Names the Solana address that Knos pays my GitHub account at (one workflow file)."
ABOUT_ORG = "Names the Solana address that Knos pays this organisation at (one workflow file)."


class Cannot(Exception):
    """Why the claim could not be made, in words."""


def _gh(*args: str, inp: str | None = None) -> str:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, input=inp, timeout=120, check=False)
    except FileNotFoundError:
        raise Cannot("`knos claim` uses GitHub's `gh` command, which is not installed here. Install it "
                     "(https://cli.github.com) and run `gh auth login`, or claim in the browser: "
                     "https://drexthealpha.github.io/Knos/#claim") from None
    if r.returncode:
        raise Cannot((r.stderr or r.stdout).strip()[:300] or f"gh {' '.join(args[:2])} failed")
    return r.stdout


def _put(gh: Callable[..., str], repo: str, path: str, template: Path, sha: str | None = None) -> None:
    body = {"message": "Add the Knos claim workflow", "content": base64.b64encode(template.read_bytes()).decode(), **({"sha": sha} if sha else {})}
    gh("api", "-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-", inp=json.dumps(body))


def _run(gh: Callable[..., str], repo: str, file: str, address: str, sleep: Callable[[float], None]) -> None:
    last = None
    for _ in range(12):          # GitHub takes a few seconds to see a workflow file it was just given
        try:
            gh("workflow", "run", file, "-R", repo, "-f", f"address={address}")
            return
        except Cannot as why:
            last = why
            sleep(5)
    raise Cannot(f"GitHub would not start the claim workflow in {repo}: {last}")


def _repository(gh: Callable[..., str], repo: str, say: Callable[[str], None], sleep: Callable[[float], None], org: bool = False) -> bool:
    """Makes sure `repo` exists and holds the claim workflow this version of Knos pays by (`org`: an organisation's,
    which calls the claim workflow's later commit with `kind: org`). Returns whether it was made."""
    from .settle.v2 import pay
    # the one commit of the claim workflow the escrow takes this bind from
    pinned = f"claim.yml@{pay.IDS['claim_sha_org' if org else 'claim_sha']}"
    template, about = (TEMPLATE_ORG, ABOUT_ORG) if org else (TEMPLATE, ABOUT)
    made = templated = False
    try:
        gh("api", f"repos/{repo}")
    except Cannot:
        try:
            if org:              # the template repository holds a person's file: an organisation's is put there below
                raise Cannot("no template")
            gh("repo", "create", repo, "--public", "--template", TEMPLATE_REPO, "--description", about)
            templated = True
        except Cannot:           # the template cannot be used from here: an empty repository, and the file below
            gh("repo", "create", repo, "--public", "--description", about)
        made = True
        say(f"Created {repo} (public; it holds only the claim workflow).")
    have, tries = None, 6 if templated else 1    # a repository made from a template gets its files a moment later
    for i in range(tries):
        try:
            have = json.loads(gh("api", f"repos/{repo}/contents/{WORKFLOW}"))
            break
        except Cannot:
            if i + 1 < tries:
                sleep(5)
    text = base64.b64decode(have.get("content", "")).decode("utf-8", "replace") if have else ""
    if pinned not in text or (org and "kind: org" not in text):      # no file yet, or the first deployment's, or one that calls another commit
        _put(gh, repo, WORKFLOW, template, have.get("sha") if have else None)
        say(f"{'Updated' if have else 'Added'} {WORKFLOW} in {repo}.")
    return made


def _carried(gh: Callable[..., str], repo: str, audience: str, address: str, wait: float, say: Callable[[str], None], sleep: Callable[[float], None],
             wait_for, log_repo: str | None) -> str | None:
    """Starts the claim workflow in `repo` by hand with the address, finds the token the run posts there (the one
    whose audience is `audience`, and not an earlier claim's), and waits for a relayer's line about it in the public
    log. The line, or None when no relayer reported in time."""
    from .proof import ghrelay

    def posted() -> list[str]:
        """The ids of the bind tokens for this address among the repository's newest comments."""
        try:
            found = ghrelay.tokens(json.loads(gh("api", f"repos/{repo}/issues/comments?sort=created&direction=desc&per_page=20")))
        except (Cannot, ValueError):
            return []
        return [ghrelay.token_id(jwt) for kind, _n, jwt, _who in found if kind == "bind" and ghrelay.audience(jwt) == audience]
    before = set(posted())       # an earlier claim's token is not this one's
    _run(gh, repo, "knos-claim.yml", address, sleep)
    say(f"GitHub is signing the claim in {repo}; waiting for a relayer to carry it to Solana (up to {int(wait // 60)} min).")
    # the run posts its token on an issue there; the relayer's log names the token by its id
    end, tid = time.monotonic() + wait, None
    while tid is None and time.monotonic() < end:
        sleep(5)
        tid = next((t for t in posted() if t not in before), None)
    if tid is None:
        return None
    get = lambda path: json.loads(gh("api", path))  # noqa: E731 - the public log, read with the same login
    return (wait_for or ghrelay.wait_for)(tid, log_repo or ghrelay.HOME_REPO, max(0.0, end - time.monotonic()), 5.0, get)


def bind(address: str, wait: float = 600, gh: Callable[..., str] = _gh, ledger=None, say: Callable[[str], None] = print,
         sleep: Callable[[float], None] = time.sleep, wait_for=None, log_repo: str | None = None) -> dict:
    """Names `address` as where the logged-in GitHub account is paid (the second deployment's Bind), and says what
    became of it. Returns {"login", "repo", "created", "bound": bool, "said": the relayer's words, or None}. Raises
    Cannot with the reason."""
    from . import fees
    from .commands import address_ok
    from .settle.v2 import pay, relay
    if not address_ok(address or ""):
        raise Cannot("That is not a Solana address.")
    me = json.loads(gh("api", "user"))
    login, uid = me["login"], int(me["id"])
    if ledger is None:
        from . import chain
        ledger = chain.ledger()
    bind_at = pay.bind_pda(uid)
    have, held = pay.read_bind(ledger.account(bind_at)), relay.held_for(ledger, uid)
    repo = f"{login}/knos-claim"
    if have is not None and str(have.wallet) == address and not held:
        say(f"{login} (GitHub user id {uid}) is already paid at {address}. Nothing to do.")
        return {"login": login, "repo": repo, "created": False, "bound": True, "said": None}
    if held:
        rule = fees.live(ledger)        # a held payment's fee is taken when it is sent: by the knos_pay build that is live
        net = sum(j.amount - rule.job(j.amount) for _a, j in held)
        say(f"{len(held)} payment{'s' if len(held) != 1 else ''}, {net / 1_000_000:,.2f} in all, {'are' if len(held) != 1 else 'is'} held for {login} "
            f"and will be sent to {address}.")
    created = _repository(gh, repo, say, sleep)
    line = _carried(gh, repo, pay.bind_audience(address), address, wait, say, sleep, wait_for, log_repo)
    out = {"login": login, "repo": repo, "created": created, "bound": False, "said": None}
    if line and " ok " in line:
        out.update(bound=True, said=re.sub(r" t=\d+$", "", line.split(" note=", 1)[-1]))
        say(out["said"])
    elif line:
        out["said"] = line.split(" fail ", 1)[-1]
        say(f"The claim was refused: {out['said']}")
    else:                        # no relayer's word in time: the chain itself may still show it
        now = pay.read_bind(ledger.account(bind_at))
        out["bound"] = now is not None and str(now.wallet) == address
        say(f"{login} is now paid at {address}." if out["bound"] else
            f"Not bound yet. The run and its verdict are at https://github.com/{repo}/actions; `knos due {login}` shows where the account is paid.")
    return out


def bind_org(org: str, address: str, wait: float = 600, gh: Callable[..., str] = _gh, ledger=None, say: Callable[[str], None] = print,
             sleep: Callable[[float], None] = time.sleep, wait_for=None, log_repo: str | None = None) -> dict:
    """Names `address` as where the ORGANISATION `org` is paid (knos_pay's BindOrg), started by the logged-in member,
    and says what became of it. Returns {"login" (the member), "org", "org_id", "repo", "created", "bound": bool,
    "said": the relayer's words, or None}. Raises Cannot with the reason."""
    from . import fees
    from .commands import address_ok
    from .settle.v2 import pay, relay
    if not address_ok(address or ""):
        raise Cannot("That is not a Solana address.")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", org or ""):
        raise Cannot("Name the organisation as GitHub does, like octo-org.")
    login = json.loads(gh("api", "user"))["login"]
    try:
        them = json.loads(gh("api", f"users/{org}"))
    except Cannot:
        raise Cannot(f"GitHub knows no account named {org}.") from None
    if them.get("type") != "Organization":
        raise Cannot(f"{them.get('login', org)} is a person's account, not an organisation. Its owner binds a wallet with `knos claim <address>`.")
    name, oid = str(them["login"]), int(them["id"])
    if ledger is None:
        from . import chain
        ledger = chain.ledger()
    bind_at, repo = pay.bind_pda(oid), f"{name}/knos-claim"
    have, held = pay.read_bind(ledger.account(bind_at)), relay.held_for(ledger, oid)
    out = {"login": login, "org": name, "org_id": oid, "repo": repo, "created": False, "bound": False, "said": None}
    if have is not None and str(have.wallet) == address and not held:
        say(f"{name} (GitHub organisation id {oid}) is already paid at {address}. Nothing to do.")
        return {**out, "bound": True}
    if held:
        rule = fees.live(ledger)        # a held payment's fee is taken when it is sent: by the knos_pay build that is live
        net = sum(j.amount - rule.job(j.amount) for _a, j in held)
        say(f"{len(held)} payment{'s' if len(held) != 1 else ''}, {net / 1_000_000:,.2f} in all, {'are' if len(held) != 1 else 'is'} held for {name} "
            f"and will be sent to {address}.")
    try:
        out["created"] = _repository(gh, repo, say, sleep, org=True)
    except Cannot as why:
        raise Cannot(f"{repo} could not be made ready ({why}). It takes a member who may create a repository in {name} and write to it; "
                     "or put examples/knos-claim-org.yml there as .github/workflows/knos-claim.yml and run it by hand (Actions > knos claim > "
                     "Run workflow).") from None
    line = _carried(gh, repo, pay.org_bind_audience(address), address, wait, say, sleep, wait_for, log_repo)
    if line and " ok " in line:
        out.update(bound=True, said=re.sub(r" t=\d+$", "", line.split(" note=", 1)[-1]))
        say(out["said"])
    elif line:
        out["said"] = line.split(" fail ", 1)[-1]
        say(f"The claim was refused: {out['said']}")
    else:                        # no relayer's word in time: the chain itself may still show it
        now = pay.read_bind(ledger.account(bind_at))
        out["bound"] = now is not None and str(now.wallet) == address
        say(f"{name} is now paid at {address}." if out["bound"] else
            f"Not bound yet. The run and its verdict are at https://github.com/{repo}/actions.")
    return out


def claim(address: str, repo: str | None = None, wait: float = 600, gh: Callable[..., str] = _gh, ledger=None,
          say: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep) -> dict:
    """The first deployment's claim: sends everything it holds under the logged-in GitHub account to `address`.
    Returns {"login", "repo", "created", "due": [(mint, amount)], "arrived": bool}. Raises Cannot with the reason."""
    from .settle import relay
    if not ADDRESS.fullmatch(address or ""):
        raise Cannot("That is not a Solana address.")
    me = json.loads(gh("api", "user"))
    login, uid = me["login"], int(me["id"])
    if ledger is None:
        from . import chain
        ledger = chain.ledger()
    due = [(str(m), a) for m, a in relay.dues_for(ledger, uid) if a]
    if not due:
        raise Cannot(f"Nothing is waiting for {login} (GitHub user id {uid}).")
    total = sum(a for _m, a in due)
    say(f"{total / 1_000_000:,.2f} USDC is waiting for {login}.")
    repo = repo or f"{login}/knos-claim"
    if repo.split("/")[0].lower() != login.lower():
        raise Cannot(f"The claim must run in a repository {login} owns; {repo} is not one. (GitHub signs the claim only "
                     "for the owner of the repository the workflow runs in.)")
    created = False
    try:
        gh("api", f"repos/{repo}")
    except Cannot:
        gh("repo", "create", repo, "--public", "--description", "Claims Knos payments to my GitHub account (one workflow file).")
        created = True
        say(f"Created {repo} (public; it holds only the claim workflow).")
    try:
        gh("api", f"repos/{repo}/contents/{WORKFLOW_V1}")
    except Cannot:
        _put(gh, repo, WORKFLOW_V1, TEMPLATE_V1)
        say(f"Added {WORKFLOW_V1} to {repo}.")
    _run(gh, repo, "knos-claim-v1.yml", address, sleep)
    say(f"GitHub is signing the claim in {repo}; waiting for a relayer to carry it to Solana (up to {int(wait // 60)} min).")
    end = time.monotonic() + wait
    arrived = False
    while time.monotonic() < end:
        sleep(10)
        if not any(a for _m, a in relay.dues_for(ledger, uid)):
            arrived = True
            break
    if arrived:
        say(f"Sent {total / 1_000_000:,.2f} USDC to {address}.")
    else:
        say(f"Not arrived yet. The run and its verdict are at https://github.com/{repo}/actions; `knos due {login}` shows what is still waiting.")
    return {"login": login, "repo": repo, "created": created, "due": due, "arrived": arrived}
