"""The knos command line.

    knos check owner/repo#7   does what a pull request says agree with GitHub's record of its checks?
    knos init                 the free Stop hook: before your coding agent stops, Knos checks what it says is done against the repository's own checks
    knos claim <address>      name the Solana address your GitHub account is paid at, in one command (uses your gh login);
                              `knos claim --org <organisation> <address>` names the one an organisation is paid at
    knos status               is the second deployment running as designed? `--json` prints the same as data

  for a repository's workflows
    knos command | settle | review | check --event E --repo R    what a repository's workflow runs: one command per job (knos.flow)
    knos relay                carry GitHub-signed tokens to Solana (what the always-on worker runs; anyone can)
    knos mcp                  paid bounties and claim checks for a coding agent, over MCP (knos init registers it)
    knos proof ...            the same checks by hand; and the judge GitHub runs on a bounty's pull request
    knos accept init          scaffold a black-box acceptance bundle from a reference implementation

  for money
    knos bounty owner/repo#7  what is in escrow for an issue, and its state
    knos due <github login>   where a GitHub account is paid, what is held for it, and its record
    knos fund-wallet o/r#7 20 put a bounty on an issue straight from a wallet
    knos balance ...          money a wallet sets aside for one GitHub owner's repositories: show, open, deposit, set, withdraw
    knos keys                 the signing keys the verifier holds; exit 1 when one of GitHub's is missing or expiring
    knos receipts | statement | export | invoice    records for the person who signs off spend, recomputed from the chain's log
    knos statement --meter --buyer X --seller Y --month YYYY-MM    what knos_meter counted for one buyer and one seller in a month
    knos receipt <file>       check an acceptance receipt against the specification and print its digest
    knos mainnet-check        every gate that must hold before mainnet, with its evidence

Every failure is one line that says what happened.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from . import badge, ghwords, version

_app = typer.Typer(add_completion=False, pretty_exceptions_enable=False, no_args_is_help=True,
                  help="The neutral meter for AI agent work: neither side keeps the count. "
                       "Start with `knos check`, `knos init`, `knos claim` or `knos status`.")

for _stream in (sys.stdout, sys.stderr):   # a Windows console's code page cannot encode everything a PR says
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

out = Console(highlight=False, soft_wrap=True)
err = Console(highlight=False, soft_wrap=True, stderr=True)         # notes beside data that goes to a file or a pipe


class Stop(Exception):
    """A refusal, in words: what happened, and (optionally) the command that fixes it."""

    def __init__(self, said: str, fix: str = ""):
        super().__init__(said)
        self.said, self.fix = said, fix


def _repo(given: str | None = None) -> Path:
    here = Path(given).resolve() if given else Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return d
    raise Stop(f"{here} is not inside a git repository.", "Run this inside the repository, or pass --in PATH.")


def _version(show: bool) -> None:
    if show:
        out.print(f"knos {version()}", markup=False)
        raise typer.Exit()


@_app.callback()
def _main(_v: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="print the version")) -> None:
    pass


@_app.command()
def init(undo: bool = typer.Option(False, "--undo", help="remove what knos init added"),
         hosts: str = typer.Option(None, "--hosts",
                                   help="claude,codex,cursor,gemini (default: every one installed here)"),
         pr: str = typer.Option(None, "--pr", help="owner/repo: instead, print the link that installs Knos in that repository by one pull request"),
         host: str = typer.Option(None, "--host", help="instead, write Knos for one coding agent into this project: cursor, gemini, copilot, opencode, ... (a name nobody knows lists them all)"),
         everywhere: bool = typer.Option(False, "--global", help="with --host: also write that agent's file in your home, where it reads nothing else")) -> None:
    """Install the Stop hook for Claude Code and Codex: it compares what the agent says is done with what the repository's checks show. And register `knos mcp` with them,
    Cursor and Gemini CLI, so an agent can find paid bounties. Free; nothing leaves this machine except the public
    GitHub, PyPI and Solana lookups a claim or a tool needs."""
    from . import init as setup
    if pr: raise typer.Exit(setup.pull_request(pr, lambda said: out.print(said, markup=False, highlight=False, soft_wrap=True)))  # noqa: E701
    if host: raise typer.Exit(setup.project_cli(host, everywhere, lambda said: out.print(said, markup=False, highlight=False, soft_wrap=True)))  # noqa: E701
    picked = [h.strip() for h in hosts.split(",") if h.strip()] if hosts else None
    rep = setup.undo(picked) if undo else setup.install(picked)
    for what in rep["removed"]:
        out.print(f"  removed {what} (an older Knos's, or one whose command is gone)", markup=False)
    for host, where in rep["done"]:
        out.print(f"  {'removed from' if undo else 'Stop hook for'} {host}: {where}", markup=False)
    for host, where in rep["mcp"]:
        out.print(f"  {'removed from' if undo else 'MCP server for'} {host}: {where}", markup=False)
    for host, why in rep["skipped"]:
        out.print(f"  skipped {host}: {why}", markup=False)
    if undo:
        out.print("Knos is out of your agents' settings." if rep["done"] or rep["mcp"] or rep["removed"]
                  else "Nothing of Knos's was installed.")
        return
    if not rep["done"] and not rep["mcp"]:
        raise Stop("No coding agent Knos knows (Claude Code, Codex, Cursor, Gemini CLI) is installed here.",
                   "Install one, or name it: knos init --hosts claude")
    if rep["done"]:
        out.print("From the next session, when your agent says tests pass, CI is green, it shipped or it is done, Knos "
                  "runs that check itself before the agent may stop.")
    if rep["mcp"]:
        out.print("From the next session your agent can also ask Knos for paid bounties (knos_bounties), what one would pay "
                  "(knos_quote, knos_can_pay), the comment to post to fund, take or settle one (it sends nothing), and whether a "
                  "pull request's claims agree with GitHub's record (knos_check_pr).")
    out.print("Undo: knos init --undo")


@_app.command("hook", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def hook_cmd(ctx: typer.Context, which: str = typer.Argument(...)) -> None:
    """What the installed hook calls. A hook name from an older version does nothing, quietly."""
    if which == "proof":
        from .proof import hook
        raise typer.Exit(hook.main_proof(list(ctx.args)))
    raise typer.Exit(0)


@_app.command()
def mcp() -> None:
    """Paid bounties and claim checks for a coding agent, over MCP on stdio. Read-only: no key, no wallet. An agent
    host starts this; `knos init` registers it."""
    from . import mcp as server
    raise typer.Exit(server.main())


def _register_proof() -> None:
    from .proof.cli import register
    register(_app, out, Stop, _repo)


_register_proof()
badge.register(_app)    # knos badge, knos record


def _register_flow() -> None:
    """The four commands a repository's workflow runs, one per job: knos command, settle, review, check. knos.flow holds
    what they do; nothing here but their options."""
    event_opt = typer.Option(..., "--event", help="the event GitHub handed the workflow (GITHUB_EVENT_PATH)")
    repo_opt = typer.Option(..., "--repo", help="owner/name (GITHUB_REPOSITORY)")

    def run(name: str, event: Path, repo: str, **more) -> None:
        from . import flow
        try:
            payload = json.loads(event.read_text(encoding="utf-8"))
        except (OSError, ValueError) as why:
            raise Stop(f"{event} is not the event GitHub handed the workflow: {why}") from None
        if repo.count("/") != 1:
            raise Stop("Name the repository as owner/name.")
        raise typer.Exit(getattr(flow, name)(flow.Run(repo, payload), **more))

    @_app.command("command")
    def command(event: Path = event_opt, repo: str = repo_opt) -> None:
        """A comment, or a new issue: act on its `/knos` line (fund, tip, take, release, the rest) and reply."""
        run("command", event, repo)

    @_app.command("settle")
    def settle(event: Path = event_opt, repo: str = repo_opt,
               tests: bool = typer.Option(False, "--tests", help="the job after the sandboxed judge passed: sign for the bounty "
                                                                 "paid by acceptance checks, for --pull at --head"),
               pull: int = typer.Option(0, "--pull", help="with --tests: the pull request the judge passed"),
               head: str = typer.Option("", "--head", help="with --tests: the commit it passed at; nothing is signed unless the "
                                                           "pull request is still at it"),
               issue: int = typer.Option(0, "--issue", help="with --tests: the issue whose acceptance checks were judged (default: "
                                                            "the one `knos review` named)")) -> None:
        """A push to the default branch, a `/knos settle` or `/knos tip` comment, or a workflow_dispatch with a pull
        request's number: pay what each merged pull request earned, and say so on it."""
        if not tests and (pull or head or issue):
            raise Stop("--pull, --head and --issue go with --tests: the job that follows the sandboxed judge.")
        run("settle", event, repo, **(dict(tests=True, pull=pull or None, head=head, issue=issue or None) if tests else {}))

    @_app.command("review")
    def review(event: Path = event_opt, repo: str = repo_opt) -> None:
        """The "knos check" workflow finished for a pull request: one comment on it, kept up to date, saying whether
        it takes a bounty, what is missing and who would be paid."""
        run("review", event, repo)

    @_app.command("check")
    def check(pr: str = typer.Argument(None, metavar="[OWNER/REPO#N]", help="the pull request to check, as owner/repo#number or its github.com URL"),
              event: Path = typer.Option(None, "--event", help="a workflow's job: the event GitHub handed it (GITHUB_EVENT_PATH)"),
              repo: str = typer.Option(None, "--repo", help="a workflow's job: owner/name (GITHUB_REPOSITORY)")) -> None:
        """Does what a pull request says agree with GitHub's record? Name one (`knos check owner/repo#7`) and its description's
        "tests pass" or "CI is green" is held against the checks GitHub recorded at its head commit; exit 1 only when the claim
        is false. A repository's workflow runs this with --event and --repo instead: the same read-only look at the pull request,
        the repository's rules and a funded issue's terms so far."""
        if pr:
            if event or repo:
                raise Stop("Name a pull request, or give --event and --repo from a workflow; not both.")
            from . import mcp as server
            try:
                got = server.Server()._check_pr({"pr": pr})
            except server.Failed as why:
                raise Stop(str(why)) from None
            names = [" ".join(str(x).split()) for x in (got.get("untrusted") or {}).get("failed_checks") or []]
            out.print(got["said"] + (f" Failed: {', '.join(names)}." if names else ""), markup=False)      # names are a workflow file's words, so only here, never in `said`
            raise typer.Exit(1 if got["verdict"] == "false" else 0)
        if not event or not repo:
            raise Stop("Name a pull request: knos check owner/repo#7", "(A repository's workflow gives --event and --repo instead.)")
        run("check", event, repo)


    # attest and canary take options of their own, which knos.flow reads with argparse (a signing job installs neither
    # typer nor rich): `knos attest ...` and `knos canary ...` go there before this command line is ever built
    # (flow.takes). They are named here so that `knos --help` lists them; reached this way, they are handed on as they came.
    passed_on = {"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []}

    @_app.command("attest", context_settings=passed_on)
    def attest(ctx: typer.Context) -> None:
        """Ask GitHub to sign that a work order's terms were met, from any repository: what attest.yml runs
        (`knos attest --help` lists its options)."""
        from . import flow
        raise typer.Exit(flow.main(["attest", *ctx.args]))

    @_app.command("canary", context_settings=passed_on)
    def canary(ctx: typer.Context) -> None:
        """One timed round on devnet: fund, pull request, merge, payment (`knos canary --help` lists its options)."""
        from . import flow
        raise typer.Exit(flow.main(["canary", *ctx.args]))


_register_flow()



# ---- money on Solana: relay, keys, balance, fund-wallet, bounty, due, claim ------------------------------------------
# One block. knos.settle.v2 is the second deployment, where new bounties go; knos.settle is the first, whose bounties
# finish where they were funded. Each command is thin: the relays, the worker and the claim hold the logic.

def _fetch(path: str) -> dict:
    """GitHub's answer for `path`, as it came: a failed request raises (urllib's own error), for callers that word it themselves."""
    import os
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "knos"})
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - api.github.com
        return json.loads(resp.read())


def _github(path: str) -> dict:
    try:
        return _fetch(path)
    except OSError as why:
        raise Stop(ghwords.failed(path, why)) from None


def _usdc(units: int) -> str:
    return f"{units / 1_000_000:,.2f}"


def _when(t: int) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


def _ledger():
    from . import chain
    try:
        return chain.ledger()
    except chain.Refused as why:
        raise Stop(str(why)) from None


def _wallet(keypair: Path | None):
    from . import chain
    try:
        return chain.wallet(keypair)
    except chain.Refused as why:
        raise Stop(str(why)) from None


def _owner(who: str) -> int:
    """A GitHub owner's id: the number itself, or the id of the user or organisation with that login."""
    return int(who) if who.isdigit() else int(_github(f"users/{who}")["id"])


def _issue(where: str) -> tuple[str, int]:
    name, _, n = where.partition("#")
    if "/" not in name or not n.isdigit():
        raise Stop("Name the issue as owner/repo#number, e.g. octo/widgets#7.")
    return name, int(n)


def _mint(ledger, given: str | None):
    """(mint, its token program, its decimals): the mint named, or test USDC (Circle's devnet mint)."""
    from solders.pubkey import Pubkey

    from .settle.v2 import pay
    try:
        mint = Pubkey.from_string(given) if given else pay.USDC_DEVNET
    except ValueError:
        raise Stop(f"{given!r} is not a mint address.") from None
    info = ledger.infos([mint])[0]
    if info is None or info[0] not in (pay.TOKEN, pay.TOKEN_2022) or len(info[1]) < 82:
        raise Stop(f"{mint} is not a token mint on this cluster.")
    return mint, info[0], info[1][44]


def _units(text: str, decimals: int) -> int:
    import re
    m = re.fullmatch(r"([0-9]{1,12})(?:\.([0-9]+))?", text or "")
    if not m or len(m.group(2) or "") > decimals:
        raise Stop(f"An amount is digits with at most {decimals} decimals, like 20 or 12.5; {text!r} is not one.")
    return int(m.group(1)) * 10 ** decimals + int((m.group(2) or "").ljust(decimals, "0") or 0)


def _money(units: int, mint, decimals: int = 6) -> str:
    """An amount as people write it. On devnet every mint is test money; the two test USDC mints are called that."""
    from .settle.v2 import pay
    return f"{units / 10 ** decimals:,.2f} " + ("test USDC" if mint in (pay.USDC_DEVNET, pay.faucet_mint()) else f"of mint {mint}")


def _send(ledger, ixs, wallet) -> str:
    """One transaction, signed and paid for by the wallet. A refusal is said in the escrow's own words."""
    from .settle.v2 import relay
    try:
        return ledger.send(ixs, wallet)
    except Exception as why:  # noqa: BLE001 - whatever the cluster said, in one line
        words = relay.why_failed(why)
        if "no SOL" in words:
            words = f"this wallet ({wallet.pubkey()}) has no SOL for the transaction fee. On devnet: solana airdrop 1 {wallet.pubkey()} --url devnet"
        raise Stop(f"Solana refused it: {words}") from None


def _tx(sig: str) -> str:
    return f"  https://explorer.solana.com/tx/{sig}?cluster=devnet"


@_app.command()
def relay(token_file: Path = typer.Option(None, "--token-file", "--token", help="relay this one token now and print the result as JSON"),
          terms_file: Path = typer.Option(None, "--terms-file", help="a fund token's terms JSON (as its `knos-terms:` line gave them)"),
          serve: float = typer.Option(None, "--serve", metavar="SECONDS", help="keep making passes for this long"),
          every: float = typer.Option(3.0, "--every", help="seconds from one pass to the next, with --serve")) -> None:
    """Carry GitHub-signed tokens to Solana and pay the transaction fees (KNOS_RELAY_KEY). A relayer decides nothing:
    the money goes where the token says. With no option: one pass over the tokens repositories posted, which is what
    the public worker does all day with --serve."""
    from . import chain
    from .proof import ghrelay
    if token_file is None:
        if serve:
            ghrelay.serve(serve, every)
        else:
            ghrelay.once()
        return
    text = token_file.read_text(encoding="utf-8")
    found = ghrelay.TOKEN.search(text)                                  # the token alone, or the comment that carried it
    # what travels beside it, read as the worker reads it (ghrelay.tokens): a key token's `knos-issuer:` line, else `knos-terms:`
    said = (ghrelay.ISSUER if found and found.group(1) == "key" else ghrelay.TERMS).search(text)
    terms = terms_file.read_bytes().strip() if terms_file else said.group(1).encode() if said else None
    r = ghrelay.carry(_ledger(), chain.key(), found.group(2) if found else text.strip(), terms)
    if r.get("ok"):
        r["note"] = ghrelay.note(r)
    typer.echo(json.dumps(r))
    raise typer.Exit(0 if r.get("ok") else 1)


def _key_state(k, now: int) -> str:
    """What a key is, in words: "ready" only when Step would accept it now; else why it cannot be used, and when it can."""
    from .settle.v2 import oidc
    if oidc.key_usable(k, now)[0]:
        return "ready"
    if k.state != 1:
        return "registered, its parameters not sent yet (anyone can send them)"
    if k.revoked:
        return "revoked, never usable again"
    if not (k.genesis or k.approved):
        return "not usable yet: the guardian has not approved it" + (f", and its delay ends {_when(k.active_at)}" if now < k.active_at else "")
    if now < k.active_at:
        return f"not usable yet: approved, usable from {_when(k.active_at)}"
    return f"expired {_when(k.expires_at)}"


def _waiting(k, now: int) -> bool:
    """Whether a key is only waiting out its delay: registered and ready, not revoked, and not yet active."""
    return k is not None and k.state == 1 and not k.revoked and now < k.active_at


@_app.command()
def keys() -> None:
    """Every signing key the second verifier holds, and whether each key GitHub and GitLab publish today verifies
    there. Exit 1 when one of GitHub's is missing, cannot be used, or expires within 7 days, or when another issuer's is
    missing or broken; exit 0 when the only keys that cannot be used yet are others' waiting out their delay."""
    from .settle import relay as first
    from .settle.v2 import oidc
    from .settle.v2 import relay as second
    ledger = _ledger()
    now = ledger.now()
    names = {oidc.GITHUB: "GitHub", oidc.GITLAB: "GitLab"}
    published, wrong, waiting = {}, [], []
    for issuer, name in names.items():
        try:
            published.update({oidc.key_pda(issuer, n): (name, kid, issuer) for kid, n in oidc.jwks_keys(first.fetch_jwks(issuer))})
        except Exception as err:  # noqa: BLE001 - the issuer did not answer: its keys cannot be vouched for
            wrong.append(f"{name}'s key set could not be read ({type(err).__name__}: {err}), so its keys were not checked.")
    held = {addr: k for addr, k, _n in second.keys(ledger)}
    k: oidc.Key | None
    for addr, k in held.items():
        today = f"published today as {published[addr][1]}" if addr in published else "not in the issuer's key set today"
        out.print(f"{names.get(k.issuer, k.issuer)}  {k.bits} bits  {_key_state(k, now)}  active from {_when(k.active_at)}  expires {_when(k.expires_at)}  "
                  f"{'approved' if k.approved else 'not approved'}  {'REVOKED' if k.revoked else 'not revoked'}  {today}  {addr}", markup=False)
    if not held:
        out.print("The second verifier holds no key on this cluster.")
    for addr, (name, kid, issuer) in published.items():
        k = held.get(addr)
        usable, why = oidc.key_usable(k, now)
        if not usable and issuer != oidc.GITHUB and k is not None and _waiting(k, now):     # a new key of another issuer: its delay is the design, not a fault
            waiting.append(f"{name}'s key {kid} is waiting out its delay: it can be used from {_when(k.active_at)}"
                           + ("" if k.approved or k.genesis else ", once the guardian has approved it") + ".")
        elif not usable:
            wrong.append(f"{name}'s key {kid}: {why}")
        elif k is not None and k.expires_at - now < 7 * 86_400:
            wrong.append(f"{name}'s key {kid} expires {_when(k.expires_at)}, in less than 7 days. Run the rotate workflow, so that Refresh is sent for it.")
    for line in [*waiting, *wrong]:
        out.print(line, markup=False)
    if wrong:
        raise typer.Exit(1)
    if waiting:
        github = sum(1 for _n, _k, issuer in published.values() if issuer == oidc.GITHUB)
        out.print(f"Every key GitHub publishes today ({github}) verifies on chain. {len(waiting)} of another issuer's "
                  f"{'is' if len(waiting) == 1 else 'are'} waiting out {'its' if len(waiting) == 1 else 'their'} delay, as listed above.")
        return
    out.print(f"Every key the issuers publish today ({len(published)}) verifies on chain.")


balance_app = typer.Typer(add_completion=False, help="Money a wallet sets aside for bounties in one GitHub owner's repositories, spent by "
                                                     "GitHub-signed comments (/knos fund). The wallet is a Solana keypair file: --keypair, or KNOS_WALLET_KEY.")
_app.add_typer(balance_app, name="balance")
_KEYPAIR = typer.Option(None, "--keypair", help="the wallet: a Solana keypair file (default: KNOS_WALLET_KEY)")
_MINT = typer.Option(None, "--mint", help="the token's mint (default: test USDC, Circle's devnet mint)")
_OWNER = typer.Argument(..., help="the GitHub user or organisation whose repositories spend it: a login, or its numeric id")


def _balance(ledger, wallet, owner: str, mint):
    """(the Balance's address, what is there) for this wallet, owner and mint. Refuses when there is none."""
    from .settle.v2 import pay
    at = pay.balance_pda(_owner(owner), wallet.pubkey(), mint)
    b = pay.read_balance(ledger.account(at))
    if b is None:
        raise Stop(f"This wallet has no balance for {owner} in that mint.", f"Open one: knos balance open {owner}")
    return at, b


@balance_app.command("show")
def balance_show(owner: str = _OWNER) -> None:
    """Every balance set aside for one GitHub owner's repositories: what it holds, who opened it, who may spend it."""
    from .settle.v2 import pay
    from .settle.v2 import relay as second
    ledger = _ledger()
    oid = _owner(owner)
    got = second.balances_for(ledger, oid)
    if not got:
        out.print(f"No balance is set aside for GitHub owner id {oid}. A wallet opens one: knos balance open {owner} --keypair FILE", markup=False)
        return
    mints = dict(zip([b.mint for _a, b, _h in got], ledger.accounts([b.mint for _a, b, _h in got])))
    for addr, b, holds in got:
        decimals = mints[b.mint][44] if mints.get(b.mint) else 6
        who = "the devnet faucet (any commenter in the owner's repositories spends it; nobody withdraws it)" if b.faucet else f"wallet {b.authority}"
        cap = f"at most {_money(b.cap_per_job, b.mint, decimals)} for one bounty" if b.cap_per_job else "no cap per bounty"
        out.print(f"{_money(holds, b.mint, decimals)}  balance {addr}  opened by {who}", markup=False)
        out.print(f"  {cap}; spenders besides the owner (GitHub ids): {', '.join(map(str, b.spenders)) or 'none'}; "
                  f"{_money(b.spent, b.mint, decimals)} put into bounties so far; add money by sending that token to {pay.baltok_pda(addr)}", markup=False)


@balance_app.command("open")
def balance_open(owner: str = _OWNER, cap: str = typer.Option(None, "--cap", help="the most one bounty may take (default: no cap)"),
                 spender: list[str] = typer.Option(None, "--spender", help="a GitHub login or id that may spend it by comment, besides the owner (up to 4)"),
                 mint: str = _MINT, keypair: Path = _KEYPAIR) -> None:
    """Open a balance for the repositories of one GitHub owner. It starts empty; `knos balance deposit` fills it."""
    from .settle.v2 import pay
    wallet, ledger = _wallet(keypair), _ledger()
    m, program, decimals = _mint(ledger, mint)
    oid, ids = _owner(owner), [_owner(s) for s in spender or []]
    at = pay.balance_pda(oid, wallet.pubkey(), m)
    if ledger.account(at) is not None:
        raise Stop(f"This wallet already has a balance for {owner} in that mint: {at}.", "Change its limits with: knos balance set")
    if len(ids) > 4:
        raise Stop("A balance has at most 4 spenders besides its owner.")
    sig = _send(ledger, [pay.open_balance_ix(wallet.pubkey(), oid, m, _units(cap, decimals) if cap else 0, ids, program)], wallet)
    out.print(f"Opened balance {at} for the repositories of GitHub owner id {oid}. It is empty.", markup=False)
    out.print(f"Fill it: knos balance deposit {owner} <amount>   (or send that token to {pay.baltok_pda(at)})", markup=False)
    out.print(_tx(sig), markup=False)


@balance_app.command("deposit")
def balance_deposit(owner: str = _OWNER, amount: str = typer.Argument(..., help="how much, like 100 or 12.5"), mint: str = _MINT, keypair: Path = _KEYPAIR) -> None:
    """Move money from the wallet's token account into its balance for that owner."""
    from solders.instruction import AccountMeta, Instruction

    from .settle.v2 import pay
    wallet, ledger = _wallet(keypair), _ledger()
    m, program, decimals = _mint(ledger, mint)
    at, _b = _balance(ledger, wallet, owner, m)
    units, source = _units(amount, decimals), pay.ata(wallet.pubkey(), m, program)
    held = ledger.account(source)
    if held is None or int.from_bytes(held[64:72], "little") < units:
        raise Stop(f"The wallet's token account ({source}) holds less than {_money(units, m, decimals)}.")
    transfer = Instruction(program, bytes([12]) + units.to_bytes(8, "little") + bytes([decimals]),      # TransferChecked
                           [AccountMeta(source, False, True), AccountMeta(m, False, False), AccountMeta(pay.baltok_pda(at), False, True),
                            AccountMeta(wallet.pubkey(), True, False)])
    sig = _send(ledger, [transfer], wallet)
    out.print(f"{_money(units, m, decimals)} added to balance {at}.", markup=False)
    out.print(_tx(sig), markup=False)


@balance_app.command("set")
def balance_set(owner: str = _OWNER, cap: str = typer.Option(None, "--cap", help="the most one bounty may take; 0 for no cap"),
                spender: list[str] = typer.Option(None, "--spender", help="who may spend it besides the owner: these replace the list (up to 4)"),
                no_spenders: bool = typer.Option(False, "--no-spenders", help="empty the list: only the owner spends it"),
                mint: str = _MINT, keypair: Path = _KEYPAIR) -> None:
    """Change a balance's cap per bounty and who may spend it. What is not named stays as it is."""
    from .settle.v2 import pay
    wallet, ledger = _wallet(keypair), _ledger()
    m, _program, decimals = _mint(ledger, mint)
    at, b = _balance(ledger, wallet, owner, m)
    if cap is None and not spender and not no_spenders:
        raise Stop("Say what to change: --cap AMOUNT (0 for none), --spender LOGIN (once for each), or --no-spenders.")
    ids = [] if no_spenders else [_owner(s) for s in spender] if spender else list(b.spenders)
    if len(ids) > 4:
        raise Stop("A balance has at most 4 spenders besides its owner.")
    units = _units(cap, decimals) if cap is not None else b.cap_per_job
    sig = _send(ledger, [pay.set_balance_ix(wallet.pubkey(), at, units, ids)], wallet)
    out.print(f"Balance {at}: {'at most ' + _money(units, m, decimals) + ' for one bounty' if units else 'no cap per bounty'}; "
              f"spenders besides the owner (GitHub ids): {', '.join(map(str, ids)) or 'none'}.", markup=False)
    out.print(_tx(sig), markup=False)


@balance_app.command("withdraw")
def balance_withdraw(owner: str = _OWNER, amount: str = typer.Argument(None, help="how much (default: everything unspent)"), mint: str = _MINT,
                     keypair: Path = _KEYPAIR) -> None:
    """Take unspent money back to the wallet that opened the balance. Money already in a bounty comes back to the
    balance when the bounty is refunded."""
    from .settle.v2 import pay
    wallet, ledger = _wallet(keypair), _ledger()
    m, program, decimals = _mint(ledger, mint)
    at, _b = _balance(ledger, wallet, owner, m)
    held = ledger.account(pay.baltok_pda(at))
    holds = int.from_bytes(held[64:72], "little") if held else 0
    units = _units(amount, decimals) if amount else holds
    if not units or units > holds:
        raise Stop(f"The balance holds {_money(holds, m, decimals)}." + ("" if holds else " There is nothing to withdraw."))
    me = wallet.pubkey()
    sig = _send(ledger, [pay.create_ata_ix(me, me, m, program), pay.withdraw_ix(me, at, m, units, token_program=program)], wallet)
    out.print(f"{_money(units, m, decimals)} back in the wallet's token account {pay.ata(me, m, program)}.", markup=False)
    out.print(_tx(sig), markup=False)


RELEASES = "drexthealpha/Knos"      # where each release's examples/ are published, at its tag v<version>
ORDER_SEQS = 8                       # how many orders one wallet may hold on one issue at once (web/anyissue.js SEQ_TRIES)


def _given_pin(given: str) -> tuple[str, str]:
    import re
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)@([0-9a-f]{40})", given)
    if not m:
        raise Stop("--workflow is owner/name@<40-character commit>: the repository and commit of the workflows whose signed run may pay this bounty.")
    return m.group(1), m.group(2)


def _file_pin(name: str, ref: str, path: str, called: str) -> tuple[str, str] | None:
    """(owner/name, commit) of the `called` workflow the file `path` of repository `name` at `ref` names at a full
    commit, or None when there is no such file or it names none."""
    import base64
    import re
    try:
        text = base64.b64decode(_github(f"repos/{name}/contents/{path}?ref={ref}").get("content", "")).decode("utf-8", "replace")
    except (Stop, AttributeError):
        text = ""
    m = re.search(rf"uses:\s*([\w.-]+/[\w.-]+)/\.github/workflows/{re.escape(called)}@([0-9a-f]{{40}})\b", text)
    return (m.group(1), m.group(2)) if m else None


def _pinned(name: str, branch: str, given: str | None) -> tuple[str, str]:
    """(the repository that holds the workflows a job pins, their commit): as given (owner/name@commit), else what the
    repository's own .github/workflows/knos.yml calls prove.yml from."""
    if given:
        return _given_pin(given)
    found = _file_pin(name, branch, ".github/workflows/knos.yml", "prove.yml")
    if found is None:
        raise Stop(f"{name} has no .github/workflows/knos.yml that calls prove.yml at a pinned commit, so no run there could pay this bounty.",
                   "Install Knos in the repository first, or name the workflows yourself: --workflow owner/name@<commit>")
    return found


def _release_pin() -> tuple[str, str]:
    """The workflows a NEUTRAL order of this release names: the commit of attest.yml that this release's
    examples/knos-attest.yml (the file a seller commits to run `knos attest`) calls, read at the release's tag. The
    site's "Fund any issue" names the same commit (the Protect view's files are the same release's examples)."""
    tag = f"v{version()}"
    found = _file_pin(RELEASES, tag, "examples/knos-attest.yml", "attest.yml")
    if found is None:
        raise Stop(f"{RELEASES} at {tag} has no examples/knos-attest.yml that calls attest.yml at a pinned commit, so this copy of knos cannot "
                   "tell which workflows a work order would name.",
                   "Name them yourself: --workflow owner/name@<commit> (the commit the knos-attest.yml you run calls attest.yml at).")
    return found


@_app.command("fund-wallet")
def fund_wallet(where: str = typer.Argument(..., metavar="OWNER/REPO#ISSUE"), amount: str = typer.Argument(..., help="how much, like 20 or 12.5"),
                checks: str = typer.Option(None, "--checks", help="the checks that must pass, comma-separated; `none` for none (default: the repository's own)"),
                paths: str = typer.Option(None, "--paths", help="globs the pull request's files must match, comma-separated"),
                days: int = typer.Option(14, "--days", help="days until an unpaid bounty goes back to the wallet (1 to 90)"),
                reserve: int = typer.Option(7, "--reserve", help="days a `/knos take` reservation lasts"),
                workflow: str = typer.Option(None, "--workflow", metavar="OWNER/NAME@COMMIT", help="the workflows whose signed runs may pay it (default: the ones the repository installed, or for a repository with none, the ones this release's knos-attest.yml calls)"),
                mint: str = _MINT, keypair: Path = _KEYPAIR) -> None:
    """Put a bounty on an issue straight from a wallet: anyone can add their own to any issue. It is paid when the
    pull request that closes the issue is merged and meets the terms shown; unpaid, it goes back to the wallet. On an
    issue of a repository that runs no Knos workflow it is a neutral work order (the fee on top), which the person
    who did the work has paid after the merge with `knos settle --neutral`."""
    from . import commands, fees, judge, terms
    from .settle.v2 import pay
    from .settle.v2 import relay as second
    name, n = _issue(where)
    if not 1 <= days <= commands.MAX_DAYS:
        raise Stop(f"--days is from 1 to {commands.MAX_DAYS}.")
    wallet, ledger = _wallet(keypair), _ledger()
    m, program, decimals = _mint(ledger, mint)
    units = _units(amount, decimals)
    if not pay.MIN_AMOUNT <= units <= pay.MAX_AMOUNT:
        raise Stop(f"A bounty is from {_money(pay.MIN_AMOUNT, m, decimals)} to {_money(pay.MAX_AMOUNT, m, decimals)}.")
    repo = _github(f"repos/{name}")
    branch = str(repo["default_branch"])
    # A repository that runs Knos's workflow pays a job from its own prove.yml. One that runs none can pay nothing that
    # waits for its own run: on knos-pay 2.1 the money becomes a NEUTRAL work order, as the site's "Fund any issue"
    # makes it, and after the merge the seller's own knos-attest.yml has it paid (`knos settle --neutral`).
    installed = _file_pin(name, branch, ".github/workflows/knos.yml", "prove.yml")
    live = second.version(ledger, wallet)          # 1: knos_pay 2.1; 2: 2.2, whose fee is one rate (knos.fees)
    order = installed is None and live >= 1
    if order:
        wf_repo, wf_sha = _given_pin(workflow) if workflow else _release_pin()
        if units < pay.units(pay.ORDER_MIN_AMOUNT, decimals):
            raise Stop(f"{name} runs no Knos workflow, so this is a work order, and a work order holds at least "
                       f"{_money(pay.units(pay.ORDER_MIN_AMOUNT, decimals), m, decimals)}.")
        reserve = 0      # a reservation is a `/knos take` comment, and nothing in that repository answers one
    else:
        wf_repo, wf_sha = _given_pin(workflow) if workflow else _pinned(name, branch, None)
    named = None if checks is None else () if checks.strip().lower() == "none" else tuple(c.strip() for c in checks.split(",") if c.strip())
    fund = commands.Fund(units, named, tuple(p.strip() for p in (paths or "").split(",") if p.strip()), days, reserve)
    try:
        head = judge.github(f"repos/{name}/branches/{branch}")["commit"]["sha"] if named is None or named else ""
        runs, statuses = terms.head_checks(name, head, judge.github, events=True) if head else ([], [])
        built = terms.build(fund, terms.required_checks(name, branch, judge.github) if head else [], runs, statuses)
        raw = terms.canonical(built.terms)
    except terms.Refused as why:
        raise Stop(str(why)) from None
    except (OSError, KeyError, TypeError) as why:
        raise Stop(f"GitHub did not answer for {name}'s checks ({ghwords.first_line(why)}), so the bounty's terms could not be fixed. "
                   + (f"It refused the request: {ghwords.RATE}." if ghwords.code_of(why) in (403, 429) else "Try again.")) from None
    me, repo_id = wallet.pubkey(), int(repo["id"])
    source = pay.ata(me, m, program)
    if order:
        scope = pay.scope_of(repo_id, n)
        seq = next((s for s in range(ORDER_SEQS) if ledger.account(pay.order_pda(scope, me, s)) is None), None)
        if seq is None:
            raise Stop(f"This wallet has already funded {where} {ORDER_SEQS} times. Use another wallet, or wait until one of those orders is paid or sent back.")
        fee = fees.rule(live).order(units, decimals=decimals)       # what the program that is live takes on top
        need, made = units + fee, pay.order_pda(scope, me, seq)
        ix = pay.fund_order_wallet_ix(me, source, m, repo_id, n, units, wf_repo, wf_sha, raw, pay.MERGE, days * 86_400, seq,
                                      pay.opts(pay.F_NEUTRAL), token_program=program)
    else:
        job = pay.job_pda(repo_id, n, me)
        if ledger.account(job) is not None:
            raise Stop(f"This wallet already has a bounty on {where}: job {job}.")
        need, ix = units, pay.fund_wallet_ix(me, source, m, repo_id, n, units, wf_repo, wf_sha, raw, pay.MERGE, days * 86_400, program)
    held = ledger.account(source)
    if held is None or int.from_bytes(held[64:72], "little") < need:
        raise Stop(f"The wallet's token account ({source}) holds less than {_money(need, m, decimals)}"
                   + (f" ({_money(units, m, decimals)} and the fee of {_money(fee, m, decimals)} on top)." if order else "."))
    sig = _send(ledger, [ix], wallet)
    after = f"  Unpaid after {days} day{'s' if days != 1 else ''}, it goes back to this wallet."
    if order:
        out.print(f"{_money(units, m, decimals)} is in escrow for {where}, and Knos's fee of {_money(fee, m, decimals)} was paid on top. "
                  f"Work order {made}.", markup=False)
    else:
        out.print(f"{_money(units, m, decimals)} is in escrow for {where}. Job {job}.", markup=False)
    for line in [*terms.describe(built.terms, built.source), *built.notes]:
        out.print(f"  {line}", markup=False)
    if order:
        out.print(f"{after} {name} needs no Knos file: after the merge, whoever did the work runs `knos settle --neutral <pull request URL>`, "
                  f"which starts `knos attest` in their own repository knos-attest. Only a signed run of attest.yml of {wf_repo} at {wf_sha[:12]} can pay it.",
                  markup=False)
    else:
        out.print(f"{after} Only a signed run of prove.yml of {wf_repo} at {wf_sha[:12]} can pay it.", markup=False)
    out.print(_tx(sig), markup=False)


@_app.command()
def bounty(where: str = typer.Argument(..., metavar="OWNER/REPO#ISSUE")) -> None:
    """What is in escrow for an issue, read from Solana devnet."""
    from . import fees
    from .settle import relay as first
    from .settle.v2 import relay as second
    name, n = _issue(where)
    repo_id = int(_github(f"repos/{name}")["id"])
    ledger = _ledger()
    now = ledger.now()
    jobs, old = second.jobs_for(ledger, repo_id, n), first.jobs_for(ledger, repo_id, n)
    if not jobs and not old:
        out.print(f"No bounty is in escrow for {where}. A maintainer funds one by commenting on the issue: /knos fund 20", markup=False)
        return
    rule = fees.live(ledger) if jobs else fees.rule()   # a job's fee is taken when it is paid: by the build that is live (asked only when a job is there)
    for addr, j in jobs:
        net = j.amount - rule.job(j.amount)
        state = (f"open: paid when the pull request that closes it is merged and meets its terms; goes back to its funder {_when(j.deadline)}" if j.state == "open"
                 else f"held for GitHub user id {j.payee_id}, who has named no wallet yet: {_money(net, j.mint)} waits for `knos claim <address>` until {_when(j.hold_until)}")
        out.print(f"{_money(j.amount, j.mint)}  {state}  job {addr}", markup=False)
    for addr, j1 in old:
        how = "paid when a maintainer merges the pull request that closes it" if j1.mode == 0 else \
              "paid when its acceptance checks pass, after the review window"
        state = "open" if j1.state == "open" else f"proven for GitHub user {j1.author_id}; released in {max(0, j1.pay_after - now)} s unless vetoed"
        out.print(f"{_usdc(j1.amount)} test USDC  {state}  ({how}; refundable in {max(0, j1.deadline - now) // 3600} h)  job {addr}  (first deployment)", markup=False)


@_app.command()
def due(login: str = typer.Argument(..., help="a GitHub login")) -> None:
    """Where a GitHub account is paid, what is held for it, its record, and what the first deployment still owes it."""
    from . import fees
    from .settle import pay as pay1
    from .settle import relay as first
    from .settle.v2 import pay
    from .settle.v2 import relay as second
    user = _github(f"users/{login}")
    uid = int(user["id"])
    ledger = _ledger()
    bound, rep = pay.read_bind(ledger.account(pay.bind_pda(uid))), pay.read_rep(ledger.account(pay.rep_pda(uid)))
    out.print(f"{login} (GitHub user id {uid}) is paid at {bound.wallet}." if bound else
              f"{login} (GitHub user id {uid}) has named no wallet: a payment whose pull request gives no address is held for them.", markup=False)
    held = second.held_for(ledger, uid)
    rule = fees.live(ledger) if held else fees.rule()   # a held job's fee is taken when it is paid: by the build that is live (asked only when one is held)
    for addr, j in held:
        out.print(f"{_money(j.amount - rule.job(j.amount), j.mint)} is held for issue #{j.issue} of repository id {j.repo_id} until {_when(j.hold_until)}  job {addr}", markup=False)
    s = lambda n: "" if n == 1 else "s"  # noqa: E731
    if rep.paid:
        out.print(f"Its record: paid for {rep.paid} pull request{s(rep.paid)} by {rep.funders} funder{s(rep.funders)}, {_usdc(rep.total)} in all, "
                  f"from {_when(rep.first)} to {_when(rep.last)}.", markup=False)
    if rep.test_paid:
        out.print(f"{rep.test_paid} payment{s(rep.test_paid)} in the faucet's test USDC, {_usdc(rep.test_total)} in all: test money, kept apart from the record.", markup=False)
    if rep.self_paid:
        out.print(f"{rep.self_paid} payment{s(rep.self_paid)} from bounties this account funded itself: kept apart from the record.", markup=False)
    owed = [(m, a) for m, a in first.dues_for(ledger, uid) if a]
    for m, a in owed:
        out.print(f"The first deployment holds {_usdc(a)} of {m} for {login}.", markup=False)
    old = pay1.read_rep(ledger.account(pay1.rep_pda(uid)))
    if old.paid_jobs:
        out.print(f"On the first deployment: paid for {old.paid_jobs} pull request(s) in {old.repositories} repositor{'y' if old.repositories == 1 else 'ies'}, "
                  f"{_usdc(old.total_paid)} in all.", markup=False)
    if not bound:
        out.print("Name a wallet, and what is held is sent there: knos claim <address>   (or in the browser: https://drexthealpha.github.io/Knos/#claim)", markup=False)
    if owed:
        out.print("Send what the first deployment holds to any address: knos claim --v1 <address>", markup=False)


@_app.command()
def claim(address: str = typer.Argument(..., help="the Solana address your GitHub account is paid at"),
          v1: bool = typer.Option(False, "--v1", help="send what the first deployment holds for your account to this address instead"),
          repo: str = typer.Option(None, "--repo", help="with --v1: a repository you own to run the claim in (default: <you>/knos-claim)"),
          org: str = typer.Option(None, "--org", metavar="ORGANISATION", help="name the address an organisation you are a member of is paid at "
                                                                              "(a bot's or a vendor's pull requests), in <organisation>/knos-claim"),
          wait: int = typer.Option(600, "--wait", help="seconds to wait for a relayer")) -> None:
    """Name the Solana address your GitHub account is paid at. Uses your `gh` login: GitHub signs the claim in your own
    repository named knos-claim (made from a template with one workflow file if you have none), a relayer carries it
    to Solana, and what was held for you is sent to the address. With --org the same for an organisation, in its own
    repository named knos-claim, started by you as its member."""
    from . import claim as claiming
    say = lambda s: out.print(s, markup=False)  # noqa: E731
    try:
        if org and (v1 or repo):
            raise Stop("--org is the second deployment's, in <organisation>/knos-claim: it goes with neither --v1 nor --repo.")
        if org:
            if not claiming.bind_org(org, address, wait, say=say)["bound"]:
                raise typer.Exit(1)
        elif v1:
            claiming.claim(address, repo, wait, say=say)
        elif not claiming.bind(address, wait, say=say)["bound"]:
            raise typer.Exit(1)
    except claiming.Cannot as why:
        raise Stop(str(why)) from None


# ---- end of the money block ---------------------------------------------------------------------------------------


@_app.command("mainnet-check")
def mainnet_check_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
    """Every gate that must hold before Knos moves real money, each with the evidence it was judged on. Exit 1
    while any gate fails."""
    from . import mainnet_check
    raise typer.Exit(mainnet_check.main(lambda s: out.print(s, markup=False), as_json=as_json))


# ---- knos status: the second deployment's health (one block, so it merges cleanly) ----------------

@_app.command("status")
def status_cmd(as_json: bool = typer.Option(False, "--json", help='print the checks as data instead of lines: {"cluster", "checks": [{"check", "pass", "evidence", "next"}], "overall", "passed", "of"}; the exit code is the same')) -> None:
    """Is the second deployment running as designed? Reads Solana (KNOS_RPC, default devnet) and GitHub's key list, and
    says for each of twelve things whether it holds and, when it does not, what to do. Exit 1 while any fails. With
    --json the same answer is one JSON document: each check's name, whether it passes, what was read, and its next step."""
    from . import mainnet_check
    raise typer.Exit(mainnet_check.status_main(lambda s: out.print(s, markup=False), as_json=as_json))


# ---- end of knos status ------------------------------------------------------------------------


# ---- records: receipts, statements, the SIEM export, invoices ----------------------------------------------------------------
# For the person who signs off spend. Everything is recomputed from the escrows' log lines on devnet (knos.records), never
# from a database; a transaction the public RPC would not give is said, and the totals are then a lower bound.

def _days(first: str, last: str) -> tuple[str, str]:
    from . import records
    try:
        a, b = (records.day_of(first, "--from") if first else ""), (records.day_of(last, "--to") if last else "")
    except ValueError as why:
        raise Stop(str(why)) from None
    if a and b and a > b:
        raise Stop(f"--from {a} is after --to {b}.")
    return a, b


def _month(month: str) -> str:
    from . import records
    try:
        records.month_days(month)
    except ValueError as why:
        raise Stop(str(why)) from None
    return month


def _history(limit: int):
    """Both escrows' history from the cluster; what could not be read goes to stderr."""
    from . import chain, records
    if limit < 1:
        raise Stop("--limit is a number of transactions, at least 1.")
    try:
        got = records.read(_ledger().url, min(limit, 1000))
    except (chain.Refused, OSError, ValueError) as why:
        raise Stop(f"Solana did not give the escrows' history: {ghwords.first_line(why)}.") from None
    for note in got.notes():
        err.print(note, markup=False)
    return got


def _names(no_names: bool):
    from . import records
    return records.Names(None if no_names else _fetch)


def _said(names) -> None:
    for problem in names.problems:
        err.print(f"{problem} Names it could not get are left empty.", markup=False)


_FIRST = typer.Option("", "--from", help="first UTC day, like 2026-09-01")
_LAST = typer.Option("", "--to", help="last UTC day, like 2026-09-30 (inclusive)")
_LIMIT = typer.Option(1000, "--limit", help="how many of each escrow's newest transactions to read (at most 1000)")
_NO_NAMES = typer.Option(False, "--no-names", help="do not ask GitHub for repository and account names: ids only")


@_app.command("receipt")
def receipt_check(path: str = typer.Argument(..., help="an acceptance receipt (JSON), as docs/RECEIPT.md specifies it; - reads standard input")) -> None:
    """Check an acceptance receipt against the specification (its shape, that shares and amounts add up, that the judge
    fits the order) and print its digest. Anyone can rebuild a receipt from the chain and compare digests."""
    from . import receipt
    try:
        doc = json.loads(sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        typer.echo(f"not a receipt: {e}")
        raise typer.Exit(2)
    why = receipt.check(doc)
    if why:
        typer.echo(f"not a valid receipt: {why}")
        raise typer.Exit(1)
    verdict = receipt.verdict_of(doc)
    pays = "it authorises payment" if receipt.authorises_payment(doc) else "it authorises no payment"
    typer.echo(f"valid. verdict: {verdict.replace('_', ' ')}; {pays}. digest sha256:{receipt.digest(doc)}")


@_app.command()
def receipts(owner: str = typer.Option(..., "--owner", help="the GitHub login or id whose money paid"), first: str = _FIRST, last: str = _LAST,
             fmt: str = typer.Option("csv", "--format", help="csv or jsonl"), limit: int = _LIMIT, no_names: bool = _NO_NAMES,
             to_file: Path = typer.Option(None, "--out", help="write the rows here instead of printing them")) -> None:
    """One row per payment out of an owner's money, recomputed from the escrows' log lines: date, repository, issue, pull request, who was paid and where, amount, fee, the terms' hash, the transaction. The columns are listed in knos.records."""
    from . import records
    if fmt not in ("csv", "jsonl"):
        raise Stop(f"--format is csv or jsonl; {fmt!r} is neither.")
    a, b = _days(first, last)
    who = _owner(owner)
    names = _names(no_names)
    rows = records.select(records.payments(_history(limit).events), owner_id=who, first=a, last=b, names=names)
    _said(names)
    text = records.receipts_csv(rows) if fmt == "csv" else records.receipts_jsonl(rows)
    if to_file:
        to_file.write_text(text, encoding="utf-8", newline="")
        out.print(f"Wrote {len(rows)} payment{'' if len(rows) == 1 else 's'} to {to_file}.", markup=False)
    else:
        sys.stdout.write(text)
        if not rows:
            err.print(f"No payment out of {owner}'s money in that range.", markup=False)


def _meter_statement(buyer: str, seller: str, month: str, fmt: str) -> None:
    """`knos statement --meter`: one buyer's and one seller's month at knos_meter, printed like the escrow's statement."""
    from . import chain, records
    try:
        st = records.meter_statement(_ledger(), _owner(buyer), buyer, _owner(seller), seller, month)
    except (chain.Refused, OSError, ValueError) as why:
        raise Stop(f"Solana did not give the meter's history: {ghwords.first_line(why)}.") from None
    if fmt == "csv":
        sys.stdout.write(records.meter_statement_csv(st))
    elif fmt == "json":
        sys.stdout.write(json.dumps(st, indent=1) + "\n")
    else:
        for line in records.meter_statement_lines(st):
            out.print(line, markup=False)


def statement(ctx: typer.Context,
              seller: str = typer.Option(None, "--seller", help="the GitHub login or id that was paid (with --meter: whose work was evaluated)"),
              month: str = typer.Option(None, "--month", help="like 2026-09"),
              fmt: str = typer.Option("text", "--format", help="text, csv or json"), limit: int = _LIMIT, no_names: bool = _NO_NAMES,
              meter: bool = typer.Option(False, "--meter", help="the meter's statement instead: the evaluations knos_meter billed --buyer for, of --seller's work, in "
                                                                "--month (how many, accepted and rejected, their declared value, the fees), with the count the program keeps"),
              buyer: str = typer.Option(None, "--buyer", help="with --meter: the GitHub login or id of the owner whose credits paid")) -> None:
    """What one seller was paid in a month: each payment with its transaction, and the totals, recomputed from the escrows' log lines. With --meter and --buyer: what knos_meter counted for that buyer and that seller in the month."""
    if ctx.invoked_subcommand:      # `knos statement make | approve | pay | show | export | verify` (src/knos/statement.py)
        return
    from . import records
    if not seller or not month:
        raise Stop("Say whose month: knos statement --seller X --month YYYY-MM", "An invoice's statement for accounts payable: knos statement make --help")
    if fmt not in ("text", "csv", "json"):
        raise Stop(f"--format is text, csv or json; {fmt!r} is none of them.")
    _month(month)
    if meter != bool(buyer):
        raise Stop("The meter's statement is for one buyer and one seller: knos statement --meter --buyer X --seller Y --month YYYY-MM" if meter else
                   "--buyer goes with --meter: knos statement --meter --buyer X --seller Y --month YYYY-MM")
    if meter:
        return _meter_statement(buyer, seller, month, fmt)
    who = _owner(seller)
    names = _names(no_names)
    st = records.statement(records.payments(_history(limit).events), who, seller, month, names)
    _said(names)
    if fmt == "csv":
        sys.stdout.write(records.receipts_csv(st["payments"]))
    elif fmt == "json":
        sys.stdout.write(json.dumps({k: ([{c: r[c] for c in records.RECEIPT_COLUMNS} for r in v] if k == "payments" else v) for k, v in st.items()}, indent=1) + "\n")
    else:
        for line in records.statement_lines(st):
            out.print(line, markup=False)


@_app.command()
def export(siem: bool = typer.Option(False, "--siem", help="JSON Lines, one escrow event per line: time, actor, action, repository, issue, amount, transaction (fields: knos.records.SIEM_FIELDS)"),
           first: str = _FIRST, last: str = _LAST, limit: int = _LIMIT, no_names: bool = _NO_NAMES,
           to_file: Path = typer.Option(None, "--out", help="write the lines here instead of printing them")) -> None:
    """Every event the escrows logged, as JSON Lines for a SIEM: time, actor, repository, action, amount, transaction (and the fields a line has)."""
    from . import records
    if not siem:
        raise Stop("Say what to export: knos export --siem   (JSON Lines, one escrow event per line)")
    a, b = _days(first, last)
    names = _names(no_names)
    text = records.siem_lines(_history(limit).events, names, a, b)
    _said(names)
    if to_file:
        to_file.write_text(text, encoding="utf-8", newline="")
        out.print(f"Wrote {text.count(chr(10))} events to {to_file}.", markup=False)
    else:
        sys.stdout.write(text)


@_app.command()
def invoice(owner: str = typer.Option(..., "--owner", help="the GitHub login or id whose money paid"), month: str = typer.Option(..., "--month", help="like 2026-09"),
            folder: Path = typer.Option(Path("."), "--out", help="the folder to write the .html and the .csv in"), limit: int = _LIMIT, no_names: bool = _NO_NAMES) -> None:
    """An owner's month as a plain HTML invoice and a CSV of its lines: every payment made out of their money, with the fee and the transaction. The evaluations knos_meter billed the owner for that month are listed after them, and in a CSV of their own."""
    from . import records
    _month(month)
    who = _owner(owner)
    names = _names(no_names)
    events = _history(limit).events
    inv = records.invoice(records.payments(events), who, owner, month, names, evals=records.evaluations(events))
    _said(names)
    counted = inv["evaluations"]
    try:
        folder.mkdir(parents=True, exist_ok=True)
        page, sheet, evals = folder / f"{inv['number']}.html", folder / f"{inv['number']}.csv", folder / f"{inv['number']}-evaluations.csv"
        page.write_text(records.invoice_html(inv), encoding="utf-8")
        sheet.write_text(records.invoice_csv(inv), encoding="utf-8", newline="")
        if counted:
            evals.write_text(records.evaluations_csv(counted), encoding="utf-8", newline="")
    except OSError as why:
        raise Stop(f"Could not write the invoice in {folder}: {ghwords.first_line(why)}.") from None
    out.print(f"Wrote {page} and {sheet}: " + ("; ".join(f"{t['payments']} payment(s), {records.money_text(t['total_units'], c)} out of escrow" for c, t in inv["totals"].items()) or "no payment that month") + ".", markup=False)
    if counted:
        out.print(f"Wrote {evals}: {len(counted)} evaluation(s) knos_meter counted for this owner, {records.units_text(inv['meter']['fee_units'])} in fees from their credits.", markup=False)


# ---- accept: the acceptance checks a bounty can be paid on ----------------------------------------------------------------

accept_app = typer.Typer(add_completion=False, no_args_is_help=True, help="The acceptance checks a bounty can be paid on, without a merge.")
_app.add_typer(accept_app, name="accept")


@accept_app.command("init")
def accept_init(issue: int = typer.Option(..., "--issue", help="the issue the bounty is on: the bundle goes in .knos/acceptance/<issue>/"),
                reference: str = typer.Option(..., "--from", help="a command that answers right: it gets one input line on stdin and prints the answer"),
                cases: int = typer.Option(30, "--cases", help="how many inputs to generate and record (1 to 200)"),
                kind: str = typer.Option("text", "--input", help="the kind of input to generate: text, int or ints"),
                run: str = typer.Option(None, "--run", help="the command the pull request's code must answer to, run in its tree (default: the --from command)"),
                seed: int = typer.Option(None, "--seed", help="generate the same inputs again (default: a random seed, recorded in cases.json)"),
                inputs: Path = typer.Option(None, "--inputs", help="your own inputs, one per line, instead of generated ones"),
                root: Path = typer.Option(None, "--in", help="the repository (default: the one you are in)"),
                force: bool = typer.Option(False, "--force", help="replace a bundle that is already there")) -> None:
    """Make a black-box acceptance bundle from a reference implementation: the reference is run on generated inputs, its answers
    are recorded, and a judge compares the pull request's code with them, running that code as a separate process so nothing it does can
    forge the verdict. The reference must pass the bundle and an echo must fail it, or nothing is written."""
    from . import accept
    if inputs is not None and cases != 30:
        raise Stop("Give --inputs or --cases, not both: --inputs is the cases.")
    where = _repo(str(root) if root else None)
    try:
        made = accept.scaffold(where, issue, reference, run, cases, kind, seed, inputs, force)
    except accept.Refused as why:
        raise Stop(str(why)) from None
    here = made.folder.relative_to(where).as_posix()
    out.print(f"Wrote {here}/ ({', '.join(made.files)}): {made.cases} case{'' if made.cases == 1 else 's'} recorded from the reference command"
              + (f", seed {made.seed}." if made.seed is not None else "."), markup=False)
    out.print("The reference passes its own bundle, and a command that only echoes its input does not.", markup=False)
    out.print(f"Commit it to the default branch before issue #{issue} is funded (/knos fund <amount>): it is black-box, so Knos pays on this check alone.", markup=False)


# ---- the help: four commands for a person, then two groups ----------------------------------------------------------------

WORKFLOWS, MONEY = "For a repository's workflows", "For money"
_HELP = [    # (command or group, its panel (None: the first, "Commands"), the one line `knos --help` shows)
    ("check", None, "Does what a pull request says agree with GitHub's record of its checks?"),
    ("init", None, "Install the free Stop hook, and register `knos mcp`, with the coding agents on this machine."),
    ("claim", None, "Name the Solana address your GitHub account is paid at; `claim --org`: an organisation's."),
    ("status", None, "Is the second deployment running as designed? `--json` prints the same as data."),
    ("command", WORKFLOWS, "A workflow's job: act on a comment's `/knos` line and reply."),
    ("settle", WORKFLOWS, "A workflow's job: pay what each merged pull request earned."),
    ("review", WORKFLOWS, "A workflow's job: one comment on a pull request saying what it would earn."),
    ("attest", WORKFLOWS, "A workflow's job, in anyone's repository: ask GitHub to sign that a work order's terms were met."),
    ("canary", WORKFLOWS, "One timed round on devnet: fund, pull request, merge, payment."),
    ("relay", WORKFLOWS, "Carry GitHub-signed tokens to Solana (the always-on worker runs this; anyone can)."),
    ("mcp", WORKFLOWS, "Paid bounties and claim checks for a coding agent, over MCP on stdio."),
    ("agent", WORKFLOWS, "A coding agent's payout key: `agent init`, `show`, `rotate`. The key is never printed."),
    ("work", WORKFLOWS, "`work list`: open, funded, unreserved work, largest first."),
    ("proof", WORKFLOWS, "The same checks by hand, and the judge GitHub runs on a bounty's pull request."),
    ("judge", WORKFLOWS, "`judge rerun`: judge a verdict's artifact again in the same image, and say agree or disagree."),
    ("accept", WORKFLOWS, "Scaffold a black-box acceptance bundle from a reference implementation."),
    ("bounty", MONEY, "What is in escrow for an issue, and its state."),
    ("due", MONEY, "Where a GitHub account is paid, what is held for it, and its record."),
    ("fund-wallet", MONEY, "Put a bounty on an issue straight from a wallet."),
    ("terms", MONEY, "Terms from a template: the comment to post, and the exact terms it funds."),
    ("balance", MONEY, "Money a wallet sets aside for one GitHub owner's repositories."),
    ("keys", MONEY, "The signing keys the verifier holds, and whether GitHub's all verify."),
    ("receipt", MONEY, "Check an acceptance receipt against the specification and print its digest."),
    ("record", MONEY, "A payee's record as the program keeps it: paid, distinct funders, test money and self-paid apart."),
    ("badge", MONEY, "Write a \"paid on proof\" badge (SVG) for a repository or a pull request, and its Markdown."),
    ("receipts", MONEY, "One row per payment for an owner, from the chain's log (csv or jsonl)."),
    ("statement", MONEY, "What one seller was paid in a month; `statement --meter`: evaluations billed. `statement make`: an invoice's statement."),
    ("export", MONEY, "Every escrow event as JSON Lines for a SIEM."),
    ("invoice", MONEY, "An owner's month as a plain HTML invoice and a CSV."),
    ("mainnet-check", MONEY, "Every gate that must hold before mainnet, with its evidence."),
]


def _arrange() -> None:
    """Order the commands as _HELP says, with a panel and a one-line summary each; anything not named keeps its place
    after them. Typer shows the first panel, then the others in the order they first appear."""
    rank = {name: i for i, (name, _p, _s) in enumerate(_HELP)}
    by = {name: (panel, short) for name, panel, short in _HELP}

    def name_of(info) -> str:
        return info.name or (info.callback.__name__.replace("_", "-") if info.callback else "")
    info: Any       # the record of a command or of a group: both have the panel, each its own field for the summary
    for info in (*_app.registered_commands, *_app.registered_groups):
        got = by.get(name_of(info))
        if got:
            info.rich_help_panel = got[0]
            if hasattr(info, "short_help"):
                info.short_help = got[1]
            elif hasattr(info, "help") and not getattr(info, "help", None):
                info.help = got[1]
    _app.registered_commands.sort(key=lambda i: rank.get(name_of(i), len(rank)))
    _app.registered_groups.sort(key=lambda i: rank.get(name_of(i), len(rank)))


# ---- the command modules, loaded when a command of theirs is asked for ------------------------------------------------
# Each of these modules costs tens of milliseconds to import (knos.records, solders, the judge), and `knos bounty x`
# needs none of them. So a command line that names one command loads that command's module and no other; `knos --help`,
# a command nobody knows, and anything that reads `cli.app` (the tests, a script) load them all. Whatever the order they
# were loaded in, the commands and the help come out as they did when every module was imported here.

def _mod(name: str):
    import importlib
    return importlib.import_module(f"knos.{name}")


def _statements() -> None:
    """`knos statement make | approve | pay | show | export | verify` beside the month's statement that was always
    here: the group is the module's, and with no subcommand it is the command it always was."""
    _mod("statement").register(_app, None)
    group = next(g.typer_instance for g in _app.registered_groups if g.name == "statement" and g.typer_instance is not None)
    group.callback(invoke_without_command=True)(statement)


_MODULES = (    # (the commands it adds, how); in the order they were always registered, which `load` keeps
    (("judge",), lambda: _mod("judge").register(_app, out, Stop)),                 # knos judge rerun
    (("terms",), lambda: _mod("terms_templates").register(_app)),                  # knos terms list | show | diff | cite | verify
    (("meter",), lambda: _mod("ledger").register(_app, out, Stop, _HELP, MONEY)),  # knos meter: batch, verify, prove, reconcile, export
    (("bundle", "receipt"), lambda: _mod("bundle").register(_app, _HELP)),         # `knos bundle`, and `knos receipt` with mirror and verify in place of the file-only command
    (("audit",), lambda: _mod("audit").register(_app, _HELP)),                     # knos audit export | verify | show | owed (src/knos/audit.py)
    (("agent", "work"), lambda: _mod("agentkey").register(_app)),                  # knos agent init | show | rotate, knos work list
    (("budget",), lambda: _mod("controls").register(_app, _HELP)),                 # knos budget show | set | check | who (src/knos/controls.py)
    (("observe",), lambda: _mod("observe").register(_app, _HELP)),                 # knos observe: what an outsider can infer from public data
    (("reproduce",), lambda: _mod("reproduce").register(_app, _HELP)),             # knos reproduce: an outside reproduction in one command
    (("shadow",), lambda: _mod("shadow").register(_app, _HELP)),                   # knos shadow: an invoice against GitHub's record (src/knos/shadow.py)
    (("events",), lambda: _mod("events").register(_app, _HELP)),                   # knos events: one log under every recording mode (src/knos/events.py)
    (("statement",), _statements),                                                 # knos statement make | approve | pay | show | export | verify (src/knos/statement.py)
    (("bill",), lambda: _mod("billing").register(_app, _HELP)),                    # knos bill estimate | explain (src/knos/billing.py)
    (("preflight", "keep"), lambda: _mod("preflight").register(_app, _HELP)),      # knos preflight, knos keep (src/knos/preflight.py)
    (("appeal",), lambda: _mod("appeal").register(_app, _HELP)),                   # knos appeal (src/knos/appeal.py)
    (("approve",), lambda: _mod("approvals").register(_app, _HELP)),               # knos approve: approval chains of a procurement object (src/knos/approvals.py)
    (("vault",), lambda: _mod("vault").register(_app, _HELP)),                     # knos vault: sealed evidence, export, retention, restore (src/knos/vault.py)
    (("decide",), lambda: _mod("decide").register(_app, _HELP)),                   # knos decide: a provisional receipt the moment the evidence arrives (src/knos/decide.py)
    (("net",), lambda: _mod("netting").register(_app, _HELP)),                     # knos net: small outcomes netted into one release (src/knos/netting.py)
    (("advance",), lambda: _mod("advance").register(_app, _HELP)),                 # knos advance: a third party's advance against a funded order (src/knos/advance.py)
    (("faucet",), lambda: _mod("faucet").register(_app, _HELP)),                   # knos faucet: test USDC for a first task (src/knos/faucet.py)
    (("controls",), lambda: _mod("enforce").register(_app, _HELP)),                # knos controls matrix: what stops money on each route (src/knos/enforce.py)
    (("recall",), lambda: _mod("recall").register(_app, _HELP)),                   # knos recall exception: how the same exception ended before (src/knos/recall.py)
    (("archive",), lambda: _mod("archive").register(_app, _HELP)),                 # knos archive make | verify | compare | policy (src/knos/archive.py)
    (("task",), lambda: _mod("tasks").register(_app, _HELP)),                      # knos task list | show | take | submit | why (src/knos/tasks.py)
)
_OWN = frozenset(name for name, _p, _s in _HELP) | {"hook", "badge", "record", "proof"}     # commands this module (or one it imports anyway) defines
_loaded: set[int] = set()


def load(command: str | None = None) -> None:
    """Register the module that defines `command`, or every module when it is None or a name nobody defines here."""
    mine = [i for i, (names, _how) in enumerate(_MODULES) if command in names]
    if not mine and (command is None or command not in _OWN):
        mine = list(range(len(_MODULES)))
    for i in mine:
        if i not in _loaded:
            _loaded.add(i)
            _MODULES[i][1]()
    tail = [row for name in ("meter", "audit", "budget", "observe", "reproduce", "shadow", "events", "bill", "preflight", "keep", "appeal", "vault", "archive", "approve", "decide", "net", "advance", "faucet", "controls", "recall", "task") for row in _HELP if row[0] == name]   # the lines modules append: in this order always
    _HELP[:] = [row for row in _HELP if row not in tail] + tail
    _arrange()


def __getattr__(name: str):
    if name == "app":       # the whole command line, for whoever asks for it by name
        load()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main(argv: list[str] | None = None) -> int:
    """The console script. Errors are one line, never a traceback."""
    args = list(sys.argv[1:] if argv is None else argv) or ["--help"]       # no argument: the four commands to start with
    from .__main__ import FLOW_FIRST
    if args[0] in FLOW_FIRST:       # only these can be a workflow's job: knos.flow (and solders) is not imported to ask about any other
        from . import flow
        if flow.takes(args):        # read without typer or rich (the console script comes this way before importing them)
            return flow.main(args)
    load(None if args[0].startswith("-") else args[0])
    try:
        rc = _app(args=args, standalone_mode=False, prog_name="knos")
        return int(rc) if isinstance(rc, int) else 0
    except Stop as why:
        out.print(why.said, markup=False)
        if why.fix:
            out.print(why.fix, markup=False)
        return 1
    except typer.Exit as e:
        return int(e.exit_code or 0)
    except typer.Abort:
        out.print("Stopped.")
        return 1
    except KeyboardInterrupt:
        out.print("Stopped.")
        return 130
    except Exception as e:  # usage errors and anything unforeseen: one line
        if type(e).__name__ == "NoArgsIsHelpError":     # `knos accept` alone: its help is already printed, and that is a success
            return 0
        if hasattr(e, "format_message") and type(e).__name__.endswith(("UsageError", "BadParameter", "NoSuchOption",
                                                                       "MissingParameter", "BadOptionUsage",
                                                                       "ClickException", "BadArgumentUsage")):
            out.print(e.format_message(), markup=False)
            out.print("See:  knos --help", markup=False)
            return 2
        out.print(f"knos stopped: {type(e).__name__}: {e}", markup=False)
        return 1


def _entry() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    _entry()
