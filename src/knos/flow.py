"""What a repository's one workflow file runs: four commands, one per job (and two more that run elsewhere: `knos
attest` in anyone's repository, `knos canary` in a repository kept for it). The YAML only starts them. Everything a
maintainer and a contributor read is decided and written here, and every outcome ends in a comment or in the job's
summary: none is silent.

    knos command   a comment on an issue or a pull request, or a new issue. Acts on its `/knos` line and replies:
                   fund and tip put money in escrow on Solana, take and release change the issue's assignee, the
                   rest is an answer. A comment with no `/knos` line gets no reply.
    knos settle    a push to the default branch (every pull request it merged), a `/knos settle` or `/knos tip`
                   comment, or a workflow_dispatch that names a pull request. For each open job the pull request
                   could take: its terms from the chain, GitHub's record of its last commit, who is paid and where;
                   then GitHub's signed token, the relay, and one comment. Nothing is signed while anything it
                   rests on could not be read. With `--tests --pull N --head SHA` it is the job that signs for a
                   bounty paid by its acceptance checks, after the sandboxed judge passed in a job of its own.
    knos review    the "knos check" workflow finished for a pull request: the same decision without a token, in one
                   comment that later runs edit in place; what the judge learned goes to the knos-memory issue.
    knos check     a pull request, with a read-only token (it may come from a fork): the description's claims, the
                   repository's rules and, for a funded issue, the terms so far. It writes the job's summary and
                   exits 1 only for a false claim or a broken rule.
    knos attest    attest.yml, started by hand in any repository: reads GitHub's public record of another repository's
                   merged pull request and a work order on Solana, applies settle's own rules, and asks GitHub to
                   sign a pay, take, revert or rule token only when that record supports it; or, in a buyer's
                   repository, an evaluation for knos_meter (eval: merged is accepted, closed unmerged rejected).
    knos canary    one full round on devnet (fund, pull request, merge, payment), each leg timed.

Where knos_pay is 2.1 (`Run.version()`), `/knos fund` opens a WORK ORDER instead of a job: its funder pays the fee on
top, it may hold a share back for a warranty, name an arbiter, pay up to four people, and be paid on a token the
seller asks for himself (neutral). The repository's .knos/policy.yml (knos.policy) is read at funding and at payout,
and every address is screened (knos.screen) before a payout. Where it is 2.0, everything is as it was.

PRIVATE work orders (see "the attestor", below): `knos command` and `knos settle` with `--attestor [--target owner/name]`,
or started by hand or on a schedule in the repository a policy names as its attestor, fund and pay the orders of other
repositories of the organisation, which they read through KNOS_READ_TOKEN and never check out.

Environment: GH_TOKEN; ACTIONS_ID_TOKEN_REQUEST_URL and ACTIONS_ID_TOKEN_REQUEST_TOKEN where a token is minted;
KNOS_RELAY_KEY (this job relays its own tokens; without it the token is posted as a comment and Knos's public worker
relays it); KNOS_RELAY_LOG_REPO; KNOS_RPC and KNOS_CLUSTER; GITHUB_OUTPUT, GITHUB_STEP_SUMMARY, GITHUB_RUN_ID,
GITHUB_RUN_ATTEMPT and GITHUB_SHA as GitHub sets them. No job checks the repository out: what is read of it (the
CONTRIBUTING file, an issue's acceptance checks) is read through GitHub's API at a named commit.

Everything that reaches outside goes through a `Run`, so the tests hand it a GitHub, a chain and a relay of their
own. Who may spend a Balance and which signed token pays a job are the chain's rules (programs-v2/knos_pay). What is here
decides only what this repository's own workflow asks GitHub to sign, which is as much as a funder's repository may
decide about the funder's own money.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

from . import badge, closing, commands, fees, ghwords, playground, policy, terms, terms3, who
from .settle.v2 import order_auto, pay

MARK = "<!-- knos-review -->"       # the first line of the one comment `knos review` keeps up to date
LOG_REPO = "drexthealpha/Knos"      # where the public worker writes what it relayed (KNOS_RELAY_LOG_REPO)
RELAY_WAIT = 600                    # seconds the public worker is waited for
RETRIES, RETRY_AFTER = 3, 20        # this job's own relay: a refusal that may clear (the faucet's minute) is tried again
CHECKS_WAIT = 120                   # settle: how long a required check that has not finished is waited for
CLAIMS_WAIT = 600                   # check: how long the commit's other checks are waited for, so the review sees them
MAX_COMMITS, MAX_ISSUES = 100, 10   # of one push; of one pull request
MAX_CASES = 12                      # bounties looked at for one pull request, and jobs listed for one issue: anyone can fund a
MAX_BALANCES = 24                   # job or open a Balance from a wallet, and one run and one comment have to stay small
MAX_BUNDLE = 200                    # files of one acceptance bundle, each read through GitHub's API
HOLD_DAYS = pay.HOLD // 86_400
TERMS_LOG = "knos2:terms "          # what knos-pay logs before a job's terms when it is funded
ORDER_LOG = "knos3:terms "          # and before a work order's (knos_pay 2.1)
NOTICE_DAYS = 7                     # a cancelled order still pays what is accepted within this many days
MARKER = {"fund": "fund", "pay": "proof", "proof": "proof", "bind": "bind",     # the comment a token travels in: knos-<marker>: <jwt>
          "cancel": "cancel", "take": "take", "revert": "revert", "rule": "rule"}
WORD = "knosrelay"                  # the one word every token comment carries: the public worker finds them by it
TOKENS = "knos tokens"              # the title of the issue, in the repository a run is in, on which `knos attest` posts what GitHub signed
TOKENS_BODY = (ghwords.MACHINE + "Knos posts here the tokens GitHub signed for runs of `knos attest` in this repository, one comment each. A token is no "
               "secret: it names one action on Solana and works once. Anyone may carry it there; Knos's public relay finds it here and does.")
NEUTRAL_WAIT, NEUTRAL_EVERY = 180, 5    # `knos settle --neutral` looks this long, this often, for the comment the run it started posts
RECORD = re.compile(r"<!-- knos-private-order (\{[^\n]*?\}) -->")      # on a private issue: what Solana does not keep of its order
ANSWER = "<!-- knos-answer {} -->"      # the first line of an attestor's reply: the comment with this id is answered
ANSWERED = re.compile(r"<!-- knos-answer (\d+) -->|<!-- knos-private-order \{\"answers\":(\d+),")
SCAN_DAYS = 3                           # how far back an attestor's run looks for funding comments and merges
MAX_ASKED = 20                          # of each, how many one run acts on in one repository
BIND = "`knos claim <their Solana address>` in a terminal, or https://drexthealpha.github.io/Knos/#claim in the browser"
OPEN = ("A wallet opens one for that id with `knos balance open`, lists the GitHub ids that may spend it, and adds money "
        "with `knos balance deposit`.")
WRITERS = "people with write access to this repository"
AGAIN = {False: "comment `/knos settle`",      # how a payment is tried again: after a merge; for a bounty paid by acceptance checks
         True: "run the `knos check` workflow again on this pull request"}
_SAID = {"passed": "passed", "failed": "failed", "skipped": "was skipped, which does not count as passing",
         "pending": "has not finished", "absent": "did not run on this commit", "unreadable": "could not be read from GitHub"}


class Run:
    """One command's world: the repository, the event GitHub handed the workflow, and every door to the outside.

        github(path, data=None, method=None)   knos.judge.github: the one function GitHub is reached through (GET; POST
                                               with `data`, GraphQL among them; PATCH and DELETE where Knos rewrites)
        ledger                                 knos.chain.ledger(): account, program_accounts, log_of, now
        relay                                  knos.settle.v2.relay: submit(ledger, payer, jwt, terms)
        ghrelay                                knos.proof.ghrelay: token_id(jwt), and wait_for(...) the public worker's line
        mint(audience)                         GitHub's signed token for this run
        clock(), sleep(seconds), env           this machine's clock, waiting, and the job's environment
        version()                              which knos_pay is live: 0 (2.0, jobs), 1 (2.1, work orders) or 2 (2.2, the 0.3.18 fee); asked of the relay
        screen(address), spent(owner_id)       knos.screen.check; knos.records.month_spent for a policy's monthly budget
        gh(*args)                              the GitHub CLI, on a person's own machine (`knos settle --neutral`)
        reads(repo, att)                       an attestor's second Run, for a repository it reads with KNOS_READ_TOKEN
        salt()                                 32 random bytes: a private order's salt

    Each is made on first use, so a command that never needs the chain never opens it."""

    def __init__(self, repo: str, event: dict, *, github=None, ledger=None, relay=None, ghrelay=None, mint=None, key=None,
                 env=None, clock=time.time, sleep=time.sleep, scratch: str | Path | None = None, version=None, screen=None,
                 spent=None, gh=None, reader=None, salt=None) -> None:
        self.repo, self.event = repo, event if isinstance(event, dict) else {}
        self.env = os.environ if env is None else env
        self.clock, self.sleep = clock, sleep
        self._github, self._ledger, self._relay, self._ghrelay, self._mint, self._key = github, ledger, relay, ghrelay, mint, key
        self._scratch = Path(scratch) if scratch else None
        self._version, self._screen, self._spent, self._gh = version, screen, spent, gh
        self._program: int | None = None
        self._policy: tuple | None = None
        self.began = clock()
        self.outputs: dict[str, str] = {}
        self.failed = False              # something could not be done: the job ends 1
        self.relayed = 0                 # how many signed tokens left this job
        self._files: dict[int, list | None] = {}
        self._left_out: dict[int, int] = {}      # per pull request: how many more bounties wait than one run looks at
        self._edited: dict[int, float | bool | None] = {}    # per pull request: knos.closing.edited_late
        self._chain_time: tuple[int, float] | None = None
        self._reader, self._salt = reader, salt
        self.attestor, self.only = False, ""     # `--attestor`, `--target owner/name`: this run is an attestor's (for that one repository)
        self.judged_at = ""                      # `knos attest` after a re-execution: the commit whose acceptance checks were run
        self.att: Any = None                     # on the Run an attestor reads a target with (`reads`): the attestor
        self.private = False                     # that Run's words are about a private repository: none goes to this job's log
        self._hidden: dict[str, tuple[bytes, bytes]] = {}    # a private order's address -> (its salt, its terms JSON), from its issue

    def github(self, path: str, data: dict | None = None, method: str | None = None):
        if self._github is None:
            from . import judge
            self._github = judge.github
        return self._github(path, data, method) if method else self._github(path, data)

    @property
    def ledger(self):
        if self._ledger is None:
            from . import chain
            self._ledger = chain.ledger()
        return self._ledger

    @property
    def relay(self):
        if self._relay is None:
            from .settle.v2 import relay
            self._relay = relay
        return self._relay

    @property
    def ghrelay(self):
        if self._ghrelay is None:
            from .proof import ghrelay
            self._ghrelay = ghrelay
        return self._ghrelay

    def mint(self, audience: str) -> str:
        return self._mint(audience) if self._mint else mint(audience, self.env)

    def version(self) -> int:
        """Which knos_pay answers on this cluster: 1 when 2.1 is live (work orders), 2 when 2.2 is (work orders at
        the 0.3.18 fee: `fees.rule` of this number is the fee every comment states), 0 when it is 2.0, or when nobody
        could say (bounties are then jobs, as before: 2.1 keeps every 2.0 instruction). Asked once a run: of the
        function a caller hands in (`version=`), else of the relay's `version(ledger)` when the relay has one."""
        if self._program is None:
            try:
                ask = self._version
                if ask is None:
                    probe = getattr(self.relay, "version", None)
                    ask = (lambda: probe(self.ledger)) if callable(probe) else (lambda: 0)
                self._program = int(ask() or 0)
            except Exception:  # noqa: BLE001
                self._program = 0
        return self._program

    def screen(self, address) -> tuple[bool | None, str]:
        """knos.screen.check: may a payout go to this address? (True, why) screened and not listed; (False, why)
        listed; (None, "not screened: ...") the list could not be had."""
        try:
            if self._screen is None:
                from . import screen
                self._screen = lambda a: screen.check(a, now=self.clock())
            return self._screen(str(address))
        except Exception as why:  # noqa: BLE001 - not knowing is said, and is not "listed"
            return None, f"not screened: {_short(why)}"

    def spent(self, owner_id: int):
        """Whole units this owner's money funded in this calendar month (UTC) and did not get back: what a policy's
        monthly budget is held to (knos.records.month_spent, over the escrows' own log lines). Raises when the
        cluster cannot be asked."""
        if self._spent is not None:
            return self._spent(owner_id)
        from . import chain, records
        url = self.env.get("KNOS_RPC") or chain.CLUSTERS[self.env.get("KNOS_CLUSTER", "devnet")]
        return records.month_spent(records.read(url).events, owner_id, time.strftime("%Y-%m", time.gmtime(self.now())))

    def salt(self) -> bytes:
        return bytes(self._salt()) if self._salt is not None else os.urandom(32)

    def reads(self, repo: str, att) -> "Run":
        """The Run an attestor looks at one of its targets with. Its `github` is the organisation's own token
        (KNOS_READ_TOKEN), held to the one repository: it reads, and of all writes it sends only Knos's comments on that
        repository's issues and pull requests. Everything else is this run's: the chain, the relay, GitHub's signature
        (the token is minted in the attestor repository), the clock, and the attestor's policy, which is the target's.
        What it would write to the job's log it does not: that log is the attestor's and may be public."""
        if self._reader is not None:
            get = self._reader(repo)
        else:
            token = self.env.get("KNOS_READ_TOKEN")
            if not token:
                raise OSError("this job has no KNOS_READ_TOKEN: the secret that lets the attestor read the repositories it attests for")
            from . import judge
            get = lambda path, data=None, method=None: judge.github(path, data, method, token=token)  # noqa: E731
        comments = re.compile(rf"repos/{re.escape(repo)}/issues/\d+/comments")

        def github(path: str, data: dict | None = None, method: str | None = None):
            reads = (data is None and method in (None, "GET")) or (path == "graphql" and method in (None, "POST"))
            if not reads and not (method in (None, "POST") and comments.fullmatch(path)):
                raise OSError("an attestor writes nothing in a repository it reads but its own comments")
            return get(path, data, method) if method else get(path, data)
        view = Run(repo, {}, github=github, ledger=self.ledger, relay=self._relay, ghrelay=self._ghrelay, mint=self.mint, key=self._key,
                   env=self.env, clock=self.clock, sleep=self.sleep, scratch=self._scratch, version=self.version, screen=self._screen,
                   spent=self._spent, salt=self._salt)
        view.att, view.private, view.began, view._policy = att, True, self.began, (att.rules, "")
        return view

    def gh(self, *args: str) -> str:
        """The GitHub CLI on a person's own machine (`knos settle --neutral`): its output. Raises OSError with its words."""
        if self._gh is not None:
            return self._gh(*args)
        import subprocess
        try:
            got = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120, check=False)  # noqa: S603, S607
        except (OSError, subprocess.SubprocessError) as why:
            raise OSError(f"the GitHub CLI (`gh`) could not be run: {_short(why)}") from None
        if got.returncode:
            raise OSError(_short(got.stderr or got.stdout or f"gh ended {got.returncode}"))
        return got.stdout

    def payer(self):
        """The key that pays this job's own relay fees (KNOS_RELAY_KEY). It holds nobody's money and decides nothing."""
        if self._key is None:
            from . import chain
            self._key = chain.key
        return self._key()

    def now(self) -> int:
        """The time the programs see: the chain's clock, read once a run and carried forward by this machine's. A
        deadline is the chain's to judge, and a cluster's clock can be minutes away from GitHub's. This machine's
        clock alone when the chain does not say."""
        if self._chain_time is None:
            try:
                self._chain_time = (int(self.ledger.now()), self.clock())
            except Exception:  # noqa: BLE001 - a guide for what is said; the chain itself refuses what is late
                self._chain_time = (int(self.clock()), self.clock())
        at, read = self._chain_time
        return int(at + self.clock() - read)

    def scratch(self) -> Path:
        """A folder for this run's small files: the judge's Sibyl store and the base's rules."""
        if self._scratch is None:
            self._scratch = Path(tempfile.mkdtemp(prefix="knos-", dir=self.env.get("RUNNER_TEMP") or None))
        self._scratch.mkdir(parents=True, exist_ok=True)
        return self._scratch

    def output(self, name: str, value) -> None:
        """One `name=value` line for the workflow's next job or step: in $GITHUB_OUTPUT, and in the job's log."""
        self.outputs[name] = str(value)
        self._append("GITHUB_OUTPUT", f"{name}={value}\n")
        print(f"{name}={value}", flush=True)

    def note(self, text: str) -> None:
        """What happened, on the run's page ($GITHUB_STEP_SUMMARY) and in the job's log. Nothing, for a repository an
        attestor reads: its names, numbers and words stay in its own comments."""
        if self.private:
            return
        self._append("GITHUB_STEP_SUMMARY", text + "\n\n")
        print(text, flush=True)

    def _append(self, variable: str, text: str) -> None:
        if self.env.get(variable):
            with open(self.env[variable], "a", encoding="utf-8") as f:
                f.write(text)

    def say(self, number, body: str) -> bool:
        """Post one comment on an issue or a pull request. When GitHub will not take it the words go to the job's
        summary instead of nowhere, and the job fails. While a settlement keeps its one comment on that pull request
        (`_Status`: posted at "received", edited as the payment moves), these words go into that comment, not under it."""
        st = getattr(self, "_status", None)
        if st is not None and int(number) == st.number and st.write(body):
            self.note(f"Commented on #{number}:\n\n{body}")
            return True
        try:
            self.github(f"repos/{self.repo}/issues/{number}/comments", {"body": body})
        except Exception as why:  # noqa: BLE001 - a read-only token, or GitHub did not answer
            self.failed = True
            self.note(f"GitHub did not take this comment on #{number} ({_short(why)}):\n\n{body}")
            return False
        self.note(f"Commented on #{number}:\n\n{body}")
        return True


# ---- small things ----------------------------------------------------------------------------------------------------

def _short(why) -> str:
    """Someone else's words, on one line and short enough for a comment."""
    return re.sub(r"\s+", " ", str(why)).strip()[:200]


def _plain(text) -> str:
    """A name, safe between backticks."""
    return re.sub(r"[`\r\n]", "'", str(text))[:120]


def _amount(units) -> str:
    """Millionths as money is written, with two decimals or as many as it takes: 20.00, 12.50, 4.875."""
    whole, part = divmod(int(units), 1_000_000)
    return f"{whole}.{f'{part:06d}'.rstrip('0').ljust(2, '0')}"


def _devnet(run: Run) -> bool:
    return run.env.get("KNOS_CLUSTER", "devnet") != "mainnet"


def _money(run: Run, mint) -> str:
    """What a job's money is called. On devnet all of it is test money: the faucet's mint and Circle's devnet USDC
    are both "test USDC", so an amount reads "20.00 test USDC". Any other mint is named."""
    if _devnet(run):
        return commands.MONEY if str(mint) in (str(pay.faucet_mint()), str(pay.USDC_DEVNET)) else f"of the test token `{mint}`"
    return f"of the token `{mint}`"


def _sum(run: Run, jobs) -> str:
    """The money of some jobs, added up by what it is: "20.00 test USDC"."""
    by: dict[str, int] = {}
    for _address, j in jobs:
        by[_money(run, j.mint)] = by.get(_money(run, j.mint), 0) + j.amount
    return " and ".join(f"{_amount(units)} {money}" for money, units in by.items())


def _until(run: Run, j) -> str:
    """How long an open job still has. Past its deadline it stays on chain until someone sends the refund, and pays
    nobody."""
    return (f"until {who.when(j.deadline)}" if run.now() <= j.deadline else
            f"until its time ran out on {who.when(j.deadline)}: it pays nobody now and goes back to where it came from")


def _link(run: Run, text: str, kind: str, at) -> str:
    return f"[{text}](https://explorer.solana.com/{kind}/{at}{'?cluster=devnet' if _devnet(run) else ''})"


def _read(run: Run, path: str):
    """GitHub's answer; None when it said no or did not answer."""
    try:
        return run.github(path)
    except Exception:  # noqa: BLE001
        return None


def _repo(run: Run) -> dict | None:
    """The repository as the chain keys it ({"id", "owner", "branch"}: its id, its owner's id, its default branch):
    from the event, else asked of GitHub. None when neither says."""
    r = run.event.get("repository")
    if not (isinstance(r, dict) and r.get("id") and (r.get("owner") or {}).get("id") and r.get("default_branch")):
        r = _read(run, f"repos/{run.repo}")
    try:
        return {"id": int(r["id"]), "owner": int(r["owner"]["id"]), "branch": str(r["default_branch"])}
    except (KeyError, TypeError, ValueError):
        return None


def _repo_known(run: Run) -> dict:
    """`_repo`, for a caller that cannot go on without it and is inside a `try`: raises, in words, when GitHub did not say."""
    rp = _repo(run)
    if rp is None:
        raise OSError("GitHub did not answer for this repository")
    return rp


def _pull(run: Run, number) -> dict | None:
    got = _read(run, f"repos/{run.repo}/pulls/{number}")
    return got if isinstance(got, dict) and got.get("number") else None


def _changes(run: Run, number: int) -> list | None:
    """GitHub's list of the files a pull request changes, read once a run. None when it could not be read whole."""
    if number not in run._files:
        run._files[number] = terms.pages(f"repos/{run.repo}/pulls/{number}/files", run.github, cap=30)
    return run._files[number]


# ---- the chain, read: Ledger.program_accounts, account and log_of are all this needs of it ---------------------------

def _u64(n: int) -> bytes:
    return int(n).to_bytes(8, "little")


def _jobs(run: Run, repo_id: int, issue: int) -> list:
    """[(address, Job)] of every job on one issue that holds money: open, or held for its payee. An issue
    can have several: each Balance and each wallet funds its own. Raises when the chain does not answer."""
    found = run.ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {8: _u64(repo_id) + _u64(issue)})
    jobs = ((address, pay.read_job(data)) for address, data in found)
    return sorted(((a, j) for a, j in jobs if j is not None and j.state in ("open", "held") and (j.repo_id, j.issue) == (repo_id, issue)),
                  key=lambda x: str(x[0]))


def _orders(run: Run, repo_id: int, issue: int) -> list:
    """[(address, Order)] of every work order (knos_pay 2.1) on one issue that holds money: open, held for its payee,
    or in its warranty. None while this cluster's knos_pay is 2.0. Raises when the chain does not answer."""
    if not run.version():
        return []
    found = run.ledger.program_accounts(pay.PAY_ID, pay.ORDER_LEN, {8: _u64(repo_id) + _u64(issue)})
    got = ((address, pay.read_order(data)) for address, data in found)
    return sorted(((a, o) for a, o in got if o is not None and o.state in ("open", "held", "warranty") and (o.repo_id, o.issue) == (repo_id, issue)),
                  key=lambda x: str(x[0]))


def funded(run: Run, repo_id: int, issue: int) -> bool:
    """Whether an issue holds money on chain: a job or a work order that is open, held or in its warranty, read the
    way a settlement reads them. Raises when the chain does not answer: not knowing is not "there is none"."""
    return bool(_jobs(run, int(repo_id), int(issue)) or _orders(run, int(repo_id), int(issue)))


def _policy(run: Run, rp: dict) -> tuple:
    """(the repository's policy, "") from .knos/policy.yml on its default branch, read once a run; (None, "") when it
    has none; (None, why) when the file is there and cannot be used or GitHub did not give it. A policy that does
    not load stops what it would have governed: it never means "anything goes"."""
    if run._policy is None:
        try:
            got = run.github(f"repos/{run.repo}/contents/{policy.PATH}?ref={urllib.parse.quote(str(rp['branch']), safe='')}")
            text = base64.b64decode(got["content"]).decode("utf-8") if isinstance(got, dict) and got.get("encoding") == "base64" else None
            run._policy = (policy.load(text), "") if text is not None else (None, f"GitHub's copy of `{policy.PATH}` was not understood")
        except policy.Refused as why:
            run._policy = (None, f"this repository's policy cannot be used ({_short(why).rstrip('.')})")
        except (KeyError, TypeError, ValueError):
            run._policy = (None, f"GitHub's copy of `{policy.PATH}` was not understood")
        except OSError as why:
            run._policy = (None, "" if getattr(why, "code", None) == 404 else f"this repository's policy (`{policy.PATH}`) could not be read from GitHub ({_short(why)})")
    return run._policy


def _balances(run: Run, owner_id: int) -> list:
    """[(address, Balance)] of every Balance set aside on chain for the repositories of one GitHub owner."""
    found = run.ledger.program_accounts(pay.PAY_ID, pay.BALANCE_LEN, {8: _u64(owner_id)})
    got = ((address, pay.read_balance(data)) for address, data in found)
    return sorted(((a, b) for a, b in got if b is not None and b.owner_id == owner_id), key=lambda x: str(x[0]))


def _holds(run: Run, balance) -> int:
    """What a Balance's token account holds now (either token program keeps the amount at byte 64)."""
    data = run.ledger.account(pay.baltok_pda(balance))
    return int.from_bytes(data[64:72], "little") if data and len(data) >= 72 else 0


def _logged(run: Run, address, digest: bytes, logged: str = TERMS_LOG) -> bytes | None:
    """The terms a job's funding transaction logged (`knos2:terms <json>`), as the bytes that were funded. Anyone can
    name a job's address in a transaction of their own and log a line of that shape, so the ledger is asked for the
    line whose JSON hashes to what the job stores (`digest`); a ledger whose `log_of` takes no such check gives its
    one line, and the caller holds it to the hash."""
    def of(line) -> bytes:
        text = line.decode("utf-8", "replace") if isinstance(line, (bytes, bytearray)) else str(line)
        return text.split(logged, 1)[-1].strip().encode("utf-8")

    def funded(line) -> bool:
        return hashlib.sha256(of(line)).digest() == digest
    for marker in (logged, "Program log: " + logged):      # a ledger may match the line with or without the runtime's prefix
        try:
            line = run.ledger.log_of(address, marker, funded)
        except TypeError:
            line = run.ledger.log_of(address, marker)
        if line:
            return of(line)
    return None


def _bundle(run: Run, ref: str, issue) -> tuple[str, dict]:
    """(the hash of .knos/acceptance/<issue>/ at one commit, its files as {path inside the folder: content}), read
    through GitHub's API. The hash is exactly what knos.judge.checks_hash computes from a checkout (sorted paths,
    each "path\\0sha256(content)\\n"); ("", {}) when that commit has no such folder. Raises OSError when GitHub does
    not answer, and terms.Refused, with the words for the funder, for a bundle that would not hash the same in a
    checkout."""
    try:
        listing = run.github(f"repos/{run.repo}/contents/.knos/acceptance?ref={urllib.parse.quote(str(ref), safe='')}")
    except OSError as why:
        if getattr(why, "code", None) == 404:
            return "", {}
        raise
    tree = next((e.get("sha") for e in listing if isinstance(e, dict) and e.get("name") == str(issue) and e.get("type") == "dir"),
                None) if isinstance(listing, list) else None
    if not tree:
        return "", {}
    got = run.github(f"repos/{run.repo}/git/trees/{tree}?recursive=1")
    if not isinstance(got, dict) or not isinstance(got.get("tree"), list):
        raise OSError("GitHub's listing of the acceptance checks was not understood")
    where, lines, held = f".knos/acceptance/{issue}/", [], {}
    files = sorted((e for e in got["tree"] if isinstance(e, dict) and e.get("type") != "tree"), key=lambda e: str(e.get("path")))
    if got.get("truncated") or len(files) > MAX_BUNDLE:
        raise terms.Refused(f"`{where}` holds more than {MAX_BUNDLE} files, too many for a bounty's acceptance checks. Keep the "
                            "checks themselves there and their data elsewhere.")
    for e in files:
        if e.get("type") != "blob" or e.get("mode") == "120000":     # a link's text is not the file a checkout would run
            raise terms.Refused(f"`{where}{_plain(e.get('path'))}` is a link or a submodule, and a bounty's acceptance checks "
                                "are plain files. Put the file itself there.")
        blob = run.github(f"repos/{run.repo}/git/blobs/{e.get('sha')}")
        try:
            content = base64.b64decode(blob["content"]) if blob.get("encoding") == "base64" else None
        except (AttributeError, KeyError, TypeError, ValueError):
            content = None
        if content is None:
            raise OSError("GitHub's copy of an acceptance check was not understood")
        lines.append(f"{e.get('path')}\0{hashlib.sha256(content).hexdigest()}\n")
        held[str(e.get("path"))] = content
    return (hashlib.sha256("".join(lines).encode()).hexdigest(), held) if lines else ("", {})


def _proof_toml(run: Run, ref: str) -> dict:
    """The commit's .knos/proof.toml, parsed ({} when it has none). Raises OSError when GitHub does not answer for
    that file: not knowing what runs the checks is not "they are black-box"."""
    from . import judge
    try:
        got = run.github(f"repos/{run.repo}/contents/.knos/proof.toml?ref={urllib.parse.quote(str(ref), safe='')}")
    except OSError as why:
        if getattr(why, "code", None) != 404:
            raise
        got = None
    text = None
    if got is not None:
        try:
            text = base64.b64decode(got["content"]).decode("utf-8") if got.get("encoding") == "base64" else None
        except (AttributeError, KeyError, TypeError, ValueError):
            text = None
        if text is None:
            raise OSError("GitHub's copy of .knos/proof.toml was not understood")
    return judge.proof_config(text)


def _not_black_box(run: Run, ref: str, files: dict, cfg: dict | None = None) -> str:
    """Why a bundle may not pay by its checks alone (knos.judge.black_box: the mechanical test, on the bundle's files
    and the same commit's .knos/proof.toml, `cfg` when the caller read it already); "" when it may."""
    from . import judge
    return judge.black_box(files, _proof_toml(run, ref) if cfg is None else cfg)


def _claims(jwt: str) -> dict:
    """A token's claims, unverified: GitHub handed the token to this very job, and the chain checks its signature."""
    try:
        body = jwt.split(".")[1]
        got = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:  # noqa: BLE001
        return {}
    return got if isinstance(got, dict) else {}


# ---- GitHub's signature, and the way to the chain --------------------------------------------------------------------

def mint(audience: str, env=None) -> str:
    """Ask GitHub for this run's OIDC token with one audience. The job needs `permissions: id-token: write`; a fork's
    pull_request run never has it. Raises OSError with the reason."""
    import urllib.request
    env = os.environ if env is None else env
    url, bearer = env.get("ACTIONS_ID_TOKEN_REQUEST_URL"), env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not bearer:
        raise OSError("this job may not ask GitHub for a signed token (it needs `permissions: id-token: write`)")
    req = urllib.request.Request(f"{url}{'&' if '?' in url else '?'}audience={urllib.parse.quote(audience, safe='')}",
                                 headers={"Authorization": f"bearer {bearer}", "Accept": "application/json", "User-Agent": "knos"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - the URL GitHub gave this job
        raw = resp.read()
    try:
        value = json.loads(raw)["value"]
    except (ValueError, KeyError, TypeError):
        value = None
    if not isinstance(value, str) or value.count(".") != 2:
        raise OSError("GitHub's answer held no token")
    return value


def deliver(kind: str, jwt: str, number: int, terms_json: bytes | None = None, *, run: Run, since: float | None = None,
            where: str | None = None) -> dict:
    """Carry one signed token to the chain and say what it did. `kind` is fund, proof (a pay token), bind, or what an
    order's token is called (take, cancel, revert, rule); `number` is the issue or pull request it is about;
    `terms_json` travels with a fund token.

    With KNOS_RELAY_KEY this job relays it (knos.settle.v2.relay.submit). Without, the token is posted as a comment
    on `number` (`knos-<kind>: <jwt>`, a fund token's terms on a `knos-terms:` line) of this repository, or of `where`
    when the job's own token writes somewhere else (`knos attest` runs in the seller's repository), Knos's public
    worker carries it and its log line is waited for, ten minutes at most; what the token did is then read back from
    the chain. Either way the answer has one shape:

        ok, why     whether the chain took it, and why not ("" when it did)
        sigs        the transactions, as far as the relay named them
        note        what happened, in a few words: the worker's own, or this job's
        seconds     from `since` (what started this: the comment, the merge; default: now) to the answer
        kind        fund, pay or bind, with the relay's detail for it:
                      fund  job, repo_id, issue, amount, mode, faucet, balance, deadline
                      pay   repo_id, issue, payee_id, head, paid: [{job, amount, fee, mint, to, held_until}]
        timeout     True when no relayer carried it in time
        already     True when the chain showed the outcome before this token was sent
        comment     the link of the comment the token was posted in, when it was posted and GitHub gave one

    Never raises."""
    began = run.clock() if since is None else since
    want = "pay" if kind == "proof" else kind
    run.relayed += 1
    try:
        r = _relay_here(run, jwt, terms_json, MARKER.get(want, want), number) if run.env.get("KNOS_RELAY_KEY") else _relay_there(run, want, jwt, number, terms_json, where)
    except Exception as why:  # noqa: BLE001 - whatever went wrong is said in the comment, never raised past it
        r = {"ok": False, "kind": want, "why": f"{type(why).__name__}: {_short(why)}"}
    ok = bool(r.get("ok"))
    return {**r, "ok": ok, "kind": r.get("kind") or want, "why": "" if ok else _short(r.get("why") or "the relay gave no reason"),
            "sigs": [str(x) for x in r.get("sigs") or []], "note": str(r.get("note") or (_note(r) if ok else "")),
            "seconds": max(0, round(run.clock() - began))}


def _relay_here(run: Run, jwt: str, terms_json: bytes | None, marker: str = "", number: int = 0) -> dict:
    """This job's own relay. A refusal the relay marks `retry` (the faucet serves a repository once a minute; the
    cluster dropped a transaction) is tried again while the token is good. The result carries what the public
    worker's log line carries: `times` (queued_at, seen_at, sent_at, confirmed_at, on this job's clock) and `line`,
    the worker's own line for this token (knos.proof.ghrelay.own_line), which goes to the run's page."""
    from .proof.ghrelay import Timed, own_line, times
    ledger, payer, seen = Timed(run.ledger, run.clock), run.payer(), run.clock()
    for left in range(RETRIES, -1, -1):
        r = dict(run.relay.submit(ledger, payer, jwt, terms_json))
        if r.get("ok") or not r.get("retry") or not left:
            break
        run.sleep(RETRY_AFTER)
    done = run.clock()
    try:
        if r.get("ok"):
            r["times"] = times(r, None, seen, done, ledger)
        if marker and r.get("ok"):
            r["line"] = own_line(marker, run.repo, int(number), jwt, r, None, seen, done, ledger)
            run.note(f"`{r['line']}`")
    except Exception:  # noqa: BLE001, S110 - the times are a record of the payment, never a reason for it to fail
        pass
    return r


def _relay_there(run: Run, kind: str, jwt: str, number: int, terms_json: bytes | None, where: str | None = None) -> dict:
    """Someone else's relay: the token goes on the issue or pull request as a comment (of `where`; default: this
    repository), where Knos's public worker (or anyone) finds it by one word, and the worker's public log says what
    became of it. The token is no secret: its audience names one action, and the chain takes it once."""
    c = _claims(jwt)
    aud = str(c.get("aud") or "").split(":")
    before = _open_for(run, aud) if kind == "pay" and aud[0] != "knos3" else []
    lines = [f"knos-{MARKER.get(kind, kind)}: {jwt}", *([f"knos-terms: {bytes(terms_json).decode('ascii')}"] if kind == "fund" and terms_json else [])]
    posted = run.github(f"repos/{where or run.repo}/issues/{int(number)}/comments",
                        {"body": "\n".join(lines) + f"\n\n<sub>{WORD}: GitHub signed this token for the one action it names. Anyone may carry it "
                                                       "to Solana; Knos's public relay does.</sub>"})
    tid = str(run.ghrelay.token_id(jwt))
    r = _verdict(run.ghrelay.wait_for(tid, run.env.get("KNOS_RELAY_LOG_REPO") or LOG_REPO, RELAY_WAIT, get=run.github), kind, tid)
    if r["ok"]:
        r.update(_seen(run, kind, c, aud, before))
    if isinstance(posted, dict) and posted.get("html_url"):
        r["comment"] = str(posted["html_url"])
    return r


def _tokens_issue(github, here: str) -> int:
    """The open issue titled "knos tokens" in the repository `here`, made the first time: its number. `github(path,
    data=None)` reads and writes GitHub's API as whoever may write `here`'s issues. Raises what GitHub answered."""
    listed = github(f"repos/{here}/issues?state=open&per_page=100")
    for i in listed if isinstance(listed, list) else []:
        if isinstance(i, dict) and i.get("title") == TOKENS and "pull_request" not in i:
            ghwords.say_machine(github, f"repos/{here}/issues/{int(i['number'])}", i.get("body"))      # one opened before 0.3.18: edited once to say it is a log
            return int(i["number"])
    return int(github(f"repos/{here}/issues", {"title": TOKENS, "body": TOKENS_BODY})["number"])


def _verdict(line: str | None, kind: str, tid: str) -> dict:
    """The public worker's log line about a token, as a relay result. The line names the token and then says
    `ok sig=<s1>[,<s2>...] note=<words> t=<seconds>` or `fail <why>`. None: nobody carried it in time."""
    if not line:
        return {"ok": False, "kind": kind, "timeout": True, "why": f"no relayer carried it within {RELAY_WAIT // 60} minutes"}
    m = re.search(r"(?:^|\s)(ok|fail)\b[ \t]*(.*)", str(line).split(tid, 1)[-1], re.S)
    if not m:
        return {"ok": False, "kind": kind, "why": f"the relay's log line was not understood: {_short(line)}"}
    if m.group(1) == "fail":
        return {"ok": False, "kind": kind, "why": _short(m.group(2)) or "the relay gave no reason"}
    sig, note = re.search(r"\bsig=(\S+)", m.group(2)), re.search(r"\bnote=(.*?)(?:\s+t=[0-9.]+)?\s*$", m.group(2), re.S)
    at = {k: float(v) for k, v in re.findall(r"\b(queued_at|seen_at|sent_at|confirmed_at)=(\d+(?:\.\d+)?)(?= )", re.split(r"(?:^| )note=", m.group(2), maxsplit=1)[0])}
    quorum = ghwords.quorum_read(note.group(1)) if note and kind == "pay" else None     # an order's judge recorded, nothing paid: how many count, and why not more
    return {"ok": True, "kind": kind, "sigs": [x for x in (sig.group(1).split(",") if sig else []) if x and x != "none"],
            "note": _short(note.group(1)) if note else "", **({"times": at} if at else {}), **({"quorum": quorum, "paid": []} if quorum else {})}


def _note(r: dict) -> str:
    """What a token this job relayed did, in a few words."""
    if r.get("kind") == "fund":
        return f"{'order ' + str(r['order']) if r.get('order') else 'job ' + str(r.get('job'))} holds {_amount(r.get('amount') or 0)} for #{r.get('issue')}"
    if r.get("kind") == "pay":
        rows = r.get("paid") or []
        sent = sum(1 for x in rows if x.get("to"))
        return f"{sent} paid, {len(rows) - sent} held for #{r.get('issue')}"
    return "relayed"


def _open_for(run: Run, aud: list[str]) -> list:
    """The open jobs a pay audience is for, as the chain shows them before the token is sent."""
    return [(a, j) for a, j in _jobs(run, int(aud[2]), int(aud[3]))
            if j.state == "open" and bytes(j.terms).hex() == aud[6] and str(j.mode) == aud[7]]


def _seen(run: Run, kind: str, c: dict, aud: list[str], before: list) -> dict:
    """What a token another job's relayer carried did, read back from the chain: the rest of the relay's result.
    Empty when the chain cannot be read; the caller then says what it asked for."""
    try:
        if aud[0] == "knos3":       # a work order: its address is in the audience, or follows from it
            if kind != "fund":
                return {"order": aud[2]}
            if bytes.fromhex(aud[9])[0] & pay.F_PRIVATE:      # its address is made of a scope only its funding run knows: that run reads it
                return {}
            repo_id, issue, balance = int(c["repository_id"]), int(aud[2]), aud[7]
            order = pay.order_pda(pay.scope_of(repo_id, issue), Pubkey.from_string(balance), int(aud[8]))
            o = pay.read_order(run.ledger.account(order))
            return {"order": str(order), "repo_id": repo_id, "issue": issue, "amount": o.amount if o else int(aud[3]), "mode": int(aud[4]),
                    "faucet": o.faucet if o else balance == str(pay.faucet_balance_pda(int(c.get("repository_owner_id") or 0))),
                    "balance": balance, "deadline": o.deadline if o else run.now() + int(aud[6]), **({"fee": o.fee} if o else {})}
        if kind == "fund":
            repo_id, issue, balance = int(c["repository_id"]), int(aud[2]), aud[7]
            job = pay.job_pda(repo_id, issue, Pubkey.from_string(balance))
            j = pay.read_job(run.ledger.account(job))
            faucet = j.faucet if j else balance == str(pay.faucet_balance_pda(int(c.get("repository_owner_id") or 0)))
            return {"job": str(job), "repo_id": repo_id, "issue": issue, "amount": j.amount if j else int(aud[3]), "mode": int(aud[4]),
                    "faucet": faucet, "balance": balance, "deadline": j.deadline if j else run.now() + int(aud[6])}
        if kind != "pay":
            return {}
        payee = int(aud[4])
        bind = pay.read_bind(run.ledger.account(pay.bind_pda(payee)))
        to = str(bind.wallet) if bind else None if aud[8] == "-" else aud[8]
        paid = []
        for address, j in before:
            now = pay.read_job(run.ledger.account(address))
            row = {"job": str(address), "amount": j.amount, "fee": fees.rule(run.version()).job(j.amount), "mint": str(j.mint)}
            if now is None and to:                                      # the job is closed: paid, where the chain pays
                paid.append({**row, "to": to, "held_until": None})
            elif now is not None and now.state == "held" and now.payee_id == payee:     # met its terms, and waiting for a wallet
                paid.append({**row, "to": None, "held_until": now.hold_until})
        return {"repo_id": int(aud[2]), "issue": int(aud[3]), "payee_id": payee, "head": aud[5], "paid": paid}
    except Exception:  # noqa: BLE001
        return {}


def _pin(jwt: str) -> tuple[bytes, str] | None:
    """The workflow a token is from, as a job pins it: (sha256 of the repository that holds it, its commit)."""
    c = _claims(jwt)
    ref, sha = str(c.get("job_workflow_ref") or ""), str(c.get("job_workflow_sha") or "")
    if "/.github/workflows/" not in ref or not sha:
        return None
    return pay.wf_repo_hash(ref.split("/.github/workflows/", 1)[0]), sha


# ---- the decision: what a pull request could take, and whether it does -------------------------------------------------

@dataclass
class Case:
    """The open jobs on one issue that share their terms (one signed token pays them all), against one pull request."""
    issue: int
    tip: bool                                       # a tip: a job on the pull request's own number
    jobs: list                                      # [(address, Job)], open
    terms: dict | None = None                       # as funded, read from the chain; None when that could not be done
    raw: bytes = b""
    checks: dict = field(default_factory=dict)      # {required check: state at the head commit}
    scope: list = field(default_factory=list)       # what the pull request changed that the terms do not allow
    why: list = field(default_factory=list)         # what else stands in the way, for certain
    unread: list = field(default_factory=list)      # what could not be read: nothing is decided on it
    fix: list = field(default_factory=list)         # what someone can do about `why`
    paid: dict = field(default_factory=dict)        # knos.who.payee
    where: dict = field(default_factory=dict)       # knos.who.payout_address
    result: dict | None = None                      # the relay's answer, once a token was sent
    order: bool = False                             # a work order (knos_pay 2.1): `jobs` holds the one (address, Order)
    payees: list = field(default_factory=list)      # an order's: [(id, basis points, the address the token names or None, login, where it goes)]
    listed: str = ""                                # a payee's address is on the sanctions list: the words; nothing is sent
    said: list = field(default_factory=list)        # what the comment adds after the outcome ("not screened")

    def verdict(self) -> str:
        """no (it is not paid as things stand), unread (something could not be read: nothing is decided), wait (a
        required check has not finished) or yes (everything holds). A certain no is said even when something else
        could not be read."""
        states = set(self.checks.values())
        if self.scope or self.why or self.listed or states & {"failed", "skipped", "absent"}:
            return "no"
        if self.unread or "unreadable" in states:
            return "unread"
        return "wait" if "pending" in states else "yes"


def _terms_of(run: Run, c: Case) -> None:
    """The terms the jobs were funded with: the bytes the funding transaction logged, held to the hash in the job."""
    address, job = c.jobs[0]
    kept = run._hidden.get(str(address))
    if kept is not None:        # a private order: its terms are in its issue and never on chain (`_kept` held them to the order's hash)
        try:
            c.terms, c.raw = terms.parse(kept[1]), kept[1]
        except terms.Refused:
            c.why.append("its terms are not in a form Knos reads, so Knos cannot check it")
        return
    try:
        raw = _logged(run, address, bytes(job.terms), ORDER_LOG if c.order else TERMS_LOG)
    except Exception:  # noqa: BLE001
        raw = None
    if not raw:
        c.unread.append("the bounty's terms could not be read from Solana")
    elif hashlib.sha256(bytes(raw)).digest() != bytes(job.terms):
        c.unread.append("the terms Solana gave are not the ones this job was funded with")
    else:
        try:
            c.terms, c.raw = terms.parse(bytes(raw)), bytes(raw)
        except terms.Refused:
            c.why.append("its terms are not in a form Knos reads, so Knos cannot check it")


def _find(run: Run, rp: dict, pull: dict, tips_only: bool = False) -> tuple[list[Case], list[int], list | None, list[int], list]:
    """What a pull request could take: for each issue it closes, and for its own number (tips), the open jobs on
    chain, grouped by their terms. Returns (cases, the issues it closes, GitHub's own list of them or None, the
    numbers the chain did not answer for, the jobs already held)."""
    number = int(pull["number"])
    listed, run._edited[number] = (None, None) if tips_only else closing.facts(run.repo, number, run.github)
    closes = [] if tips_only else closing.closed_by(pull, listed)[:MAX_ISSUES]
    cases, blind, held = [], [], []
    for n, tip in [*((n, False) for n in closes if n != number), (number, True)]:
        try:
            if run.att is not None:     # a repository an attestor reads: only the private orders it funded there. A job or a public
                live, orders = [], [] if tip else _kept(run, rp, n)     # order someone put on its id would name it in a token
            else:
                live = _jobs(run, rp["id"], n)
                orders = [] if tip else _orders(run, rp["id"], n)
        except Exception:  # noqa: BLE001 - the chain did not answer: whether #n has a job is not known
            blind.append(n)
            continue
        groups: dict = {}
        for address, j in live:
            if j.state == "open":
                groups.setdefault((bytes(j.terms), j.mode), []).append((address, j))
            else:
                held.append((n, address, j))
        cases += [Case(n, tip, jobs) for jobs in groups.values()]
        cases += [Case(n, False, [(address, o)], order=True) for address, o in orders if o.state == "open"]      # one token pays one order
        held += [(n, address, o) for address, o in orders if o.state == "held"]
    run._left_out[number] = max(0, len(cases) - MAX_CASES)
    if len(cases) > MAX_CASES:      # what this repository's own comments funded (from a Balance) first, then the largest
        cases = sorted(cases, key=lambda c: (not any(j.from_balance for _a, j in c.jobs), -sum(j.amount for _a, j in c.jobs)))[:MAX_CASES]
    for c in cases:
        _terms_of(run, c)
    return cases, closes, listed, blind, held[:MAX_CASES]


def _left_out(run: Run, number: int) -> list[str]:
    """What to say when a pull request could take more bounties than one run looks at."""
    more = run._left_out.get(number, 0)
    if not more:
        return []
    return [f"{more} more job{'s wait' if more > 1 else ' waits'} on what this pull request closes and {'were' if more > 1 else 'was'} "
            f"not looked at: one run looks at {MAX_CASES}, those funded by this repository's own comments first, then the largest."]


def _record(run: Run, sha: str, cases: list[Case], wait: float = 0, every: bool = False) -> tuple[list | None, list | None]:
    """GitHub's record of one commit, (check runs, commit statuses): read again every 15 seconds for up to `wait`
    seconds while a check a bounty requires (with `every`: any check that is not Knos's own) has not finished or
    the record cannot be read."""
    end = run.clock() + wait
    while True:
        runs, statuses = terms.head_checks(run.repo, sha, run.github)
        states = {s for c in cases if c.terms for s in terms.evidence(c.terms, runs, statuses).values()}
        busy = bool(states & {"pending", "unreadable"}) or (
            every and (runs is None or any(r.get("status") != "completed" for r in runs if not terms.ours(r))))
        if not busy or run.clock() >= end:
            return runs, statuses
        run.sleep(15)


def _judge(run: Run, pull: dict, cases: list[Case], listed: list | None, strict: bool, runs, statuses, payee: bool = True,
           tests: bool = False) -> None:
    """Fill in each case: every required check's state at the head commit, what was changed out of scope, and (with
    `payee`) who is paid and where. `strict`: money moves on this (the merge has happened, or with `tests` the
    sandboxed judge has passed), so nothing is decided on a read that failed, and a pull request merged before a
    job was funded does not take it."""
    if not cases:
        return
    number, head, author = int(pull["number"]), (pull.get("head") or {}).get("sha") or "", pull.get("user") or {}
    files = _changes(run, number)
    changed = None if files is None else sorted({str(n) for f in files if isinstance(f, dict)
                                                 for n in (f.get("filename"), f.get("previous_filename")) if n})
    facts: dict
    permission, user, message, facts = who.permission_of(run.repo, run.github), who.user_of(run.github), "", {}
    if payee and author.get("type", "User") != "User" and head:      # what a bot's head commit says is a hint to show
        message = str(((_read(run, f"repos/{run.repo}/commits/{head}") or {}).get("commit") or {}).get("message") or "")
    for c in cases:
        try:
            if c.terms:
                c.checks = terms.evidence(c.terms, runs, statuses)
                if changed is None:
                    c.unread.append("the pull request's changed files could not be read from GitHub")
                else:
                    c.scope = terms.scope(c.terms, changed)
            late = max(j.deadline for _a, j in c.jobs)
            if run.now() > late:      # the chain refuses a signed token after the deadline, whatever it says
                c.why.append(f"its time ran out on {who.when(late)}: the money goes back to where it came from")
            if strict and not c.tip:
                _timing(run, c, pull, tests)
            if payee:
                _payee(run, pull, c, facts, permission, user, message, listed, strict)
        except Exception as why:  # noqa: BLE001 - one job's trouble is its own: the others are still decided
            c.unread.append(f"Knos stopped while reading this one ({type(why).__name__}: {_short(why)})")


def _by_tests(c: Case) -> bool:
    """Whether a case's jobs are paid by their acceptance checks (tests mode) and not by the merge."""
    return c.jobs[0][1].mode == pay.TESTS or bool(c.terms and c.terms["mode"] == "tests")


def _timing(run: Run, c: Case, pull: dict, tests: bool) -> None:
    """A bounty pays work merged after it was funded: without this, anyone could fund an issue and point at a pull
    request merged long ago. (A tip is the opposite: it is funded for a pull request that is already merged.) One
    signed token pays every job with the same terms, so the case is held to its earliest job: a job someone adds after the
    merge cannot hold back the ones that were there before it. And each bounty is paid the way it was funded: on
    the merge, or (`tests`) on its acceptance checks, which must be the very files the funder's money was put on."""
    funded = min(j.not_before for _a, j in c.jobs)
    if pull.get("merged_at") or not tests:      # an open pull request judged by its acceptance checks has no merge to be early
        at = who._ts(pull.get("merged_at"))
        if at is None:
            c.unread.append("GitHub did not say when this pull request was merged")
        elif at < funded:
            c.why.append(f"it was merged on {who.when(at)}, before this bounty was funded ({who.when(funded)}): a bounty pays work "
                         "merged after it was funded")
    if not tests:
        if _by_tests(c):
            c.why.append(f"this bounty is paid by its acceptance checks (.knos/acceptance/{c.issue}/), which Knos runs on a pull "
                         "request before the merge; the merge itself does not pay it")
        return
    if c.terms:
        try:    # the commit the judge job checked out as the base: this run's own (GITHUB_SHA), on the default branch
            ref = str(run.judged_at or run.env.get("GITHUB_SHA") or _repo_known(run)["branch"])
            have, files = _bundle(run, ref, c.issue)
            fooled = _not_black_box(run, ref, files) if c.terms["mode"] == "tests" and have == c.terms["accept"] else ""
        except terms.Refused as why:
            c.why.append(_short(why))
        except Exception:  # noqa: BLE001
            c.unread.append(f"the acceptance checks (.knos/acceptance/{c.issue}/ on the default branch) could not be read from GitHub")
        else:
            if c.terms["mode"] != "tests" or have != c.terms["accept"]:
                c.why.append(f"the acceptance checks in .knos/acceptance/{c.issue}/ on the default branch are not the ones this "
                             "bounty was funded with")
            elif fooled:    # the second deployment has no veto window, so checks a pull request can fool from inside never pay alone
                c.why.append(f"the acceptance checks in .knos/acceptance/{c.issue}/ are not black-box (they {fooled}), and a "
                             "bounty is paid without a merge only by black-box checks")


def _payee(run: Run, pull: dict, c: Case, facts: dict, permission, user, message: str, listed, strict: bool) -> None:
    """Who the case pays (knos.who.payee) and where (the wallet bound on chain first, else their `/knos address`)."""
    key = "" if c.tip else c.issue
    if key not in facts:
        facts[key] = who.read(run.repo, int(pull["number"]), key, run.github)
    f = facts[key]
    # the merge accepted what the description said then: one edited since closes nothing (anyone with a merged pull
    # request could otherwise add `Fixes #N` to it and take the bounty on N), and not knowing is not "it was not"
    c.paid = who.payee(pull, f["issue"], f["events"], f["pull_comments"], f["issue_comments"], permission, c.terms, run.clock(),
                       message, user, strict=strict, closes=listed, tip=c.tip, edited=run._edited.get(int(pull["number"])), auto=_auto(c, pull))
    if not c.paid.get("id"):
        if c.paid.get("kind") == "unread":
            c.unread.append(c.paid["why"])
        else:
            c.why.append(c.paid["why"])
            c.fix += [c.paid["fix"]] if c.paid.get("fix") else []
        return
    try:
        bind = pay.read_bind(run.ledger.account(pay.bind_pda(int(c.paid["id"]))))
        bound = str(bind.wallet) if bind else None
    except Exception:  # noqa: BLE001 - not knowing is not "none bound": the signed token would name the wrong place
        bound = None
        c.unread.append(f"Solana did not say whether a wallet is bound to @{c.paid.get('login')}'s GitHub account")
    c.where = who.payout_address(c.paid, f["pull_comments"], bound)


# ---- the words -------------------------------------------------------------------------------------------------------

def _again(run: Run, tests: bool = False) -> str:
    """How a payment is tried again: by a comment, where the repository runs Knos; through its attestor, where it does not."""
    if run.att is not None:
        return f"run the knos workflow of {run.att.run.repo} by hand with this repository and this pull request's number, or wait for its next scheduled run"
    return AGAIN[tests]


def _what(run: Run, c: Case) -> str:
    money = _sum(run, c.jobs) + (f" in {len(c.jobs)} jobs" if len(c.jobs) > 1 else "")
    if c.order:
        o = c.jobs[0][1]
        if o.flags & pay.F_STANDING:
            return f"the standing offer on issue #{c.issue} ({_amount(o.rate)} {_money(run, o.mint)} for each accepted change)"
        return f"the work order on issue #{c.issue} ({money})"
    return f"the tip for this pull request ({money})" if c.tip else f"the bounty on issue #{c.issue} ({money})"


def _rows(c: Case) -> str:
    """One line per required check with its state, then everything else that stands in the way."""
    rows = [f"- `{_plain(name)}`: {_SAID.get(state, state)}" for name, state in c.checks.items()]
    return "".join(f"\n{row}" for row in [*rows, *(f"- {w}" for w in [*c.scope, *c.why, *c.unread])])


def _pays(c: Case, pays: str = "would pay") -> str:
    """Who a case pays and where, as one or two sentences; empty when nobody is (the rows say why)."""
    if not c.paid.get("id"):
        return ""
    login, where = c.paid.get("login"), c.where
    hint = f" ({c.paid['hint'][0].upper()}{c.paid['hint'][1:]}.)" if c.paid.get("hint") else ""
    if where.get("address"):
        at = "the wallet bound to their GitHub account" if where.get("from") == "bound" else "the address in their `/knos address` comment"
        return f"\nIt {pays} @{login} ({c.paid.get('why')}) at `{where['address']}`, {at}.{hint}"
    return f"\nIt {pays} @{login} ({c.paid.get('why')}). {where.get('why', 'No address is known for them')}.{hint}"


def _before(run: Run, c: Case, pull: dict) -> str:
    """One case before the merge: whether the pull request takes it as things stand, each check, who would be paid."""
    name, v, how = _what(run, c), c.verdict(), "its acceptance checks pass" if _by_tests(c) else "it is merged"
    lead = {"yes": f"this pull request takes {name} when {how}, as things stand.",
            "wait": f"this pull request takes {name} when {how}, once the checks below have passed.",
            "unread": f"whether this pull request takes {name} is not known yet: something could not be read.",
            "no": f"this pull request does not take {name} as it stands."}[v]
    states, fixes = set(c.checks.values()), []
    if "failed" in states:
        fixes.append("A check that failed needs a new commit that passes it.")
    if states & {"skipped", "absent"}:
        fixes.append("A check that was skipped or did not run has to run and pass on the pull request's last commit.")
    if c.scope:
        fixes.append("Take the files it may not change out of the pull request.")
    return lead + _rows(c) + _pays(c) + ("\n" + " ".join([*fixes, *c.fix]) if fixes or c.fix else "")


def _after(run: Run, c: Case, pull: dict, after: str, tests: bool = False) -> str:
    """One case where money moves (after the merge; with `tests`, after the acceptance checks passed): paid, held,
    refused by the chain, or not paid with what would change that and how it is tried again."""
    how = _again(run, tests)
    if c.result is not None:
        return _relayed(run, c, c.result, after, how)
    name, v, sha = _what(run, c), c.verdict(), f"`{str((pull.get('head') or {}).get('sha') or '')[:7]}`"
    states = set(c.checks.values())
    if c.listed and not (c.scope or c.why):
        until = min(j.deadline for _a, j in c.jobs)
        return (f"held, not paid. {name[0].upper()}{name[1:]} met its terms, but {c.listed} The money stays in escrow until "
                f"{who.when(until)}, then goes back to where it came from. If the payee binds another wallet ({BIND}), {how} to try again.")
    if v == "yes":
        return f"everything {name} asks for holds.{_rows(c)}{_pays(c, 'pays')}\n{how[0].upper()}{how[1:]} to have it paid."
    if v == "unread":
        return (f"nothing was decided about {name}: something could not be read, and nothing is signed on a guess."
                f"{_rows(c)}\nNothing was paid. {how[0].upper()}{how[1:]} to try again.")
    if v == "wait":
        return (f"not paid yet. {name[0].upper()}{name[1:]} needs every check below to pass at this pull request's last commit "
                f"({sha}), and one has not finished.{_rows(c)}\n{how[0].upper()}{how[1:]} when it has.")
    fixes = [f"If a check that did not pass is run again on that commit and passes, {how}."] \
        if states & {"failed", "skipped", "absent"} else []
    fixes += [f"{f} Then {how}." for f in c.fix]
    if not c.tip and run.att is None:
        fixes.append("A maintainer can pay this work anyway with `/knos tip <amount>`" + (" once it is merged." if tests else "."))
    until = min(j.deadline for _a, j in c.jobs)
    stays = f" The money stays in escrow until {who.when(until)}, then goes back to where it came from." if run.now() <= until else ""
    return (f"not paid. This pull request does not take {name} as it stands; its checks are read at its last commit ({sha})."
            f"{_rows(c)}\n{' '.join(fixes)}{stays}")


def _relayed(run: Run, c: Case, r: dict, after: str, how: str) -> str:
    """What a signed token did on the chain: paid (how much, the fee, where), held (until when, and how to receive it), or
    why the chain did not take it."""
    name, payee = _what(run, c), f"@{c.paid.get('login')}"
    took = f"{r.get('seconds', 0)} s after {after}"
    if not r.get("ok"):
        if r.get("timeout"):
            return (f"not confirmed yet. {name[0].upper()}{name[1:]} met its terms for {payee} and GitHub signed the token (it is posted "
                    f"{'in ' + run.att.run.repo if run.att is not None else 'below' if _status_of(run) is not None else 'above'}), but no relayer carried it to Solana within {RELAY_WAIT // 60} minutes. Solana takes the signed token "
                    f"until an hour after it expires: if one carries it, the payment is made, and `/knos status` shows it. Otherwise "
                    f"{how} for a new token.")
        return (f"not paid yet. {name[0].upper()}{name[1:]} met its terms for {payee} and GitHub signed the token, but Solana did not take "
                f"it: {_short(r.get('why') or 'no reason was given').rstrip('. ')}. {how[0].upper()}{how[1:]} to try again.")
    tx = _link(run, "transaction", "tx", r["sigs"][-1]) if r.get("sigs") else "an earlier token had carried it"
    if c.order and r.get("quorum"):         # an order with a quorum, before its last judge: a marker was written, nothing was paid
        q = r["quorum"]
        # why a judge who spoke is not one more (knos_pay 2.2 counts owners), and whose word of before the upgrade has to be given again
        same = "".join(f" It counts {q.get('have')} because {_short(w).rstrip('. ')}." for w in q.get("uncounted") or [])
        again = (f" {' and '.join(q['again'])[0].upper()}{' and '.join(q['again'])[1:]} passed this commit before the escrow's upgrade to knos_pay 2.2, and "
                 "a word recorded before it names no run, so it counts for nothing now: that judge signs again (run its workflow once more) and is "
                 "counted then.") if q.get("again") else ""
        return (f"not paid yet. {name[0].upper()}{name[1:]} met its terms for {payee}, and Solana recorded this judge's word ({tx}, {took}): "
                f"{q.get('have')} of the {q.get('of')} different judges its funder asked for have passed this commit, so nothing is paid until "
                f"{q.get('of')} have.{same}{again} A neutral run is one more: someone who is not its funder"
                + (" and owns no repository that judged it" if same else "") + " runs `knos settle --neutral <this pull request's "
                "URL>`, which starts the pinned attest workflow in a repository of their own.")
    if c.order:
        return _paid_order(run, c, r, tx, took)
    out = []
    for held in (False, True):
        rows = [x for x in r.get("paid") or [] if bool(x.get("to")) != held]
        if not rows:
            continue
        gross, fee = sum(x["amount"] for x in rows), sum(x["fee"] for x in rows)
        money = " and ".join(dict.fromkeys(_money(run, x.get("mint") or c.jobs[0][1].mint) for x in rows))
        for_ = "as a tip for this pull request" if c.tip else f"for issue #{c.issue}"
        kind = ("tip" if c.tip else "bounty") + (f" ({len(rows)} jobs)" if len(rows) > 1 else "")
        if not held:
            to = rows[0]["to"]
            src = {"bound": f", the wallet bound to {payee}'s GitHub account", "comment": f", the address in {payee}'s `/knos address` comment"}
            out.append(f"paid. {payee} received {_amount(gross - fee)} {money} {for_}: the {kind} of {_amount(gross)} less Knos's fee "
                       f"of {_amount(fee)}. It went to `{to}`{src.get(c.where.get('from', ''), '') if to == c.where.get('address') else ''} "
                       f"({tx}, {took}).")
        else:
            until = who.when(max(x.get("held_until") or 0 for x in rows))
            out.append(f"held for {payee}. {_amount(gross)} {money} {for_} waits for them until {until}, because no "
                       f"wallet is known for them: none is bound to their GitHub account and no `/knos address` comment counted. To "
                       f"receive it, {payee} binds a wallet: {BIND}. It is then paid, less Knos's fee of {_amount(fee)}; "
                       f"after that date it goes back to where it came from ({tx}, {took}).")
    if not out:
        return (f"the signed token for {name} was relayed ({tx}, {took}), but Solana does not show the payment yet. `/knos status` shows "
                "what is in escrow.")
    left = len(c.jobs) - len(r.get("paid") or [])
    if left > 0:
        out.append(f"{left} other job{'s' if left > 1 else ''} on this issue did not take this token (funded through another commit "
                   "of Knos's workflows); `/knos status` shows what is still in escrow.")
    return " ".join([*out, *c.said])


# A Balance's side account refuses a funding for one of these (knos.settle.v2.relay._limits, and knos_pay error 100), and
# the same comment is refused the same way until the Balance's wallet changes them. The words reach a reply the same
# from this job's own relay and from the public worker's log line, so they are matched here, not flagged by the relay.
_BALANCE_LIMITS = (pay.ERRORS[100], "that balance lists the repositories that may spend it", "that balance is spent only by the workflows")


def _assigned(run: Run, c: Case, to) -> bool:
    """Whether the one payee of an order was paid at `to` because they assigned this order's payment there (knos_pay
    Assign): the program pays an assignee before the bound wallet and the address, and the assignment stays on chain."""
    address, o = c.jobs[0]
    try:
        data = run.ledger.account(pay.assign_pda(Pubkey.from_string(str(address)), int(c.payees[0][0])))
        return str(pay.read_assign(data, o)) == str(to)
    except Exception:  # noqa: BLE001 - not read: the reply names the wallet and gives no reason, as before
        return False


def _days(n: int) -> str:
    """`n` whole days, as a reply says it: "1 day", "14 days"."""
    return f"{n} day{'' if n == 1 else 's'}"


def _paid_order(run: Run, c: Case, r: dict, tx: str, took: str) -> str:
    """What a pay token did to a work order: each payee's full share (the funder paid the fee on top), what is held
    back for the warranty, and for a standing offer what is left. The relay's rows ({"id", "to", "held_until"}) say
    where each share went; without them, where this job asked for it to go."""
    _address, o = c.jobs[0]
    standing, money = bool(o.flags & pay.F_STANDING), _money(run, o.mint)
    gross = o.rate if standing else o.amount
    back = gross * o.holdback_bps // 10_000
    rows = {int(x.get("id") or 0): x for x in r.get("paid") or [] if isinstance(x, dict)}
    fee = "its funder pays Knos's fee on top" if standing else f"its funder paid Knos's fee of {_amount(o.fee)} on top"
    people = []
    for pid, bps, _named, login, dest in c.payees:
        row = rows.get(pid, {})
        people.append((login, (gross - back) * bps // 10_000, bps, row.get("to", dest), row.get("held_until")))
    if len(people) == 1 and not people[0][3]:
        login, share, _bps, _to, until = people[0]
        out = [f"held for @{login}. {_amount(share)} {money} for issue #{c.issue} waits for them until {who.when(until or run.now() + pay.HOLD)}, "
               f"because no wallet is known for them: none is bound to their GitHub account and no `/knos address` comment counted. To "
               f"receive it, @{login} binds a wallet: {BIND}. It is then paid in full ({fee}); after that date it goes back to where "
               f"it came from ({tx}, {took})."]
    elif len(people) == 1:
        login, share, _bps, to, _until = people[0]
        src = {"bound": f", the wallet bound to @{login}'s GitHub account", "comment": f", the address in @{login}'s `/knos address` comment"}
        why = (src.get(c.where.get("from", ""), "") if to == c.where.get("address") else
               f", the wallet @{login} assigned this order's payment to (knos_pay Assign: whoever advanced them the money is paid in their place)"
               if _assigned(run, c, to) else "")
        out = [f"paid. @{login} received {_amount(share)} {money} for issue #{c.issue}, in full: {fee}. It went to `{to}`{why} ({tx}, {took})."]
    else:
        each = ", ".join(f"@{login} {_amount(share)} ({bps // 100}%) to `{to}`" for login, share, bps, to, _u in people)
        out = [f"paid. The work order on issue #{c.issue} paid {_amount(gross - back)} {money} in full ({fee}): {each} ({tx}, {took})."]
    if back:
        out.append(f"{_amount(back)} more ({o.holdback_bps / 100:g}%) is held back as the warranty for {_days(o.warranty_s // 86_400)}: after that "
                   "anyone can release it to the same people; if the work is reverted before then, it goes back to the funder.")
    if order_auto.quorum_of(o.flags) and r.get("sigs"):       # a quorum whose judges share a controller is said, from the payment's receipt
        from . import statement
        made = r.get("receipt") or _quorum_receipt(run, str(r["sigs"][-1]))
        shared = statement.not_independent(made)
        if shared:
            out.append(f"Its quorum: {shared}.")
            if run.version() < fees.NEW_VERSION:      # 2.1 counts markers, so it paid; 2.2 counts owners and would have recorded one judge
                seen = (made.get("evaluator_observed") or {}).get("evaluators") if isinstance(made, dict) else None
                said = ghwords.one_owner(len(seen) if isinstance(seen, list) and len(seen) > 1 else order_auto.quorum_of(o.flags))
                out.append(f"{said[0].upper()}{said[1:]}.")
    if standing:
        left = max(0, o.amount - o.paid - gross)
        out.append(f"The offer stays open: {_amount(left)} of {_amount(o.amount)} is left for further accepted changes until {who.when(o.deadline)}."
                   if left >= o.rate else "That was the last of the offer's budget.")
    return " ".join([*out, *c.said])


def _quorum_receipt(run: Run, signature: str) -> dict | None:
    """The receipt of the payment a quorum order just made, rebuilt from the cluster the run reads (knos.receipt: chain
    facts only, with who controls each judge that spoke). None when there is no cluster address to ask or it cannot be
    built: the comment then says nothing of the quorum's independence, and the payment is what it was."""
    url = getattr(run.ledger, "url", None)
    if not isinstance(url, str) or not url:
        return None
    try:
        from . import receipt as rc
        return rc._receipt_of(url, signature, 200)
    except Exception:  # noqa: BLE001
        return None


def _join(parts: list[str], lead: str = "Knos: ") -> str:
    """Several outcomes as one comment: the first says who is speaking, each of the others starts its own paragraph."""
    return lead + "\n\n".join(p if lead and i == 0 else p[0].upper() + p[1:] for i, p in enumerate(parts))


# ---- knos command ----------------------------------------------------------------------------------------------------

def command(run: Run) -> int:
    """`knos command`: one comment (or one new issue). Acts on its `/knos` line and always replies; a comment with no
    such line, and a comment that was edited rather than written, gets nothing. A new issue whose description has a
    `/knos fund` line is funded by its author, and its description gives no other command. Returns the job's exit
    status: 1 when something could not be done for a reason that is not the commenter's (GitHub, Solana, the relay)."""
    if _attestor(run):
        return _attestor_command(run)
    ev = run.event
    on: dict = ev["issue"] if isinstance(ev.get("issue"), dict) else {}
    said = ev["comment"] if "comment" in ev else on
    fresh = ev.get("action") == ("created" if "comment" in ev else "opened")      # an edit does not say it again
    on_pull = "pull_request" in on
    cmd = commands.parse(said.get("body") or "", on_pull) if fresh and on.get("number") and isinstance(said, dict) else None
    if cmd is None or ("comment" not in ev and not isinstance(cmd, (commands.Fund, commands.FundTerms)) and getattr(cmd, "command", "") != "fund"):
        return 0
    if isinstance(cmd, commands.Faucet):
        # a request for test USDC is knos.faucet's to answer, in a job of its own (worker.yml, `faucet`): on the playground's
        # faucet issue this job says nothing, so the request has one reply; anywhere else it says where the faucet is
        repo: dict = ev["repository"] if isinstance(ev.get("repository"), dict) else {}
        there = (playground.is_playground(str(repo.get("full_name") or run.repo), (repo.get("owner") or {}).get("id"), _devnet(run))
                 and any(isinstance(lb, dict) and lb.get("name") == commands.FAUCET_LABEL for lb in on.get("labels") or []))
        if not there:
            run.say(on["number"], commands.FAUCET_ELSEWHERE)
        return 1 if run.failed else 0
    try:
        if isinstance(cmd, commands.FundTerms):     # `/knos fund terms`: the order the repository's Knos Terms 3 document describes
            cmd = _fund_terms(run)
        reply = cmd if isinstance(cmd, str) else _act(run, cmd, said, on, on_pull)
    except Exception as why:  # noqa: BLE001 - whatever it was, the commenter is told
        run.failed = True
        reply = (f"Knos: this stopped before it was finished ({type(why).__name__}: {_short(why)}). `/knos status` shows what is in "
                 "escrow now; post the comment again to retry.")
    run.say(on["number"], reply)
    return 1 if run.failed else 0


def _fund_terms(run: Run):
    """`/knos fund terms` as the Fund it stands for (knos.commands.cite of `.knos/terms.json` on the default branch), or
    the reply that says why nothing is funded."""
    stop = "Knos: nothing was funded. "
    try:
        rp = _repo(run)
        doc = _terms3(run, rp["branch"]) if rp is not None else None
    except terms3.Refused as why:
        return (stop + f"`{TERMS3}` on the default branch says it is a Knos Terms 3 document, and it is not one an order can be funded on: "
                f"{_short(why).rstrip('. ')}. Fix the file (`knos terms verify` reads it the same way), then post the comment again.")
    except OSError as why:
        run.failed = True
        return stop + f"GitHub did not answer for this repository's terms (`{TERMS3}` on the default branch: {_short(why)}). Post the comment again."
    if rp is None:
        run.failed = True
        return stop + "GitHub did not answer for this repository. Post the comment again."
    if doc is None:
        return (stop + f"`/knos fund terms` funds the order this repository's terms describe, and it has none: there is no `{TERMS3}` on the "
                "default branch. `knos terms propose` writes one from the repository's own checks; or comment `/knos fund <amount>`.")
    try:
        if not terms3.built(doc):
            raise terms3.Refused(f"`{doc['name']}` describes work nothing can be paid for yet ({terms3.NOT_BUILT})")
        cmd = commands.cite(doc)
    except terms3.Refused as why:
        return stop + f"These terms cannot fund an order: {_short(why).rstrip('. ')}."
    return cmd.reply if isinstance(cmd, commands.Error) else cmd


def _act(run: Run, cmd, said: dict, on: dict, on_pull: bool) -> str:
    """Do what one command asks and return the reply. knos.who.answer decides who may and what is left to do."""
    number, commenter, name = int(on["number"]), said.get("user") or {}, getattr(cmd, "name", "")
    pull, bought, permission, user, agent = None, None, None, None, False
    facts = dict.fromkeys(("issue", "events", "pull_comments", "issue_comments"))
    if name in ("raise", "cancel", "split"):
        return _order_word(run, cmd, said, on)
    if name == "offer":
        return _fund(run, cmd, said, on, None)
    if name == "appeal":
        return _appeal(run, cmd, said, on)
    if name in ("take", "release"):        # the issue is in the event; its bounty, and who assigned whom, are not
        try:
            bought = _bounty(run, _repo(run), number)
        except Exception as why:  # noqa: BLE001 - not knowing whether it has a bounty is not "it has none"
            run.failed = True
            return f"Knos: whether issue #{number} has a bounty could not be read just now ({_short(why)}), so nothing was changed. Post the comment again."
        facts.update(issue=on, events=terms.pages(f"repos/{run.repo}/issues/{number}/events", run.github))
        if name == "take" and commenter.get("type") == "Bot":      # an agent's own account takes work only on an order funded `auto`
            try:
                agent = any(o.state == "open" and o.flags & order_auto.F_AUTO for _a, o in _orders(run, _repo_known(run)["id"], number))
            except Exception as why:  # noqa: BLE001
                run.failed = True
                return f"Knos: Solana could not be read just now ({_short(why)}), so nothing was reserved. Post the comment again."
    elif on_pull and name not in ("", "status", "help"):
        pull = _pull(run, number)
        if pull is None:
            run.failed = True
            return "Knos: GitHub did not answer for this pull request, so nothing was done. Post the comment again."
        permission, user = who.permission_of(run.repo, run.github), who.user_of(run.github)
        if name not in ("tip", "settle"):
            facts, bought = _context(run, pull)
    o = who.answer(cmd, commenter, pull, facts["issue"], facts["events"], facts["pull_comments"], facts["issue_comments"],
                   permission, bought, run.clock(), user, auto=agent)
    if o is None:       # (knos.who.answer says None only of a comment with no command, and this one has one)
        raise ValueError("no command was read in this comment")
    if o.then in ("fund", "tip"):
        return _fund(run, cmd, said, on, pull)
    if o.then == "status":
        return _status(run, on, on_pull)
    if o.then == "settle":
        run.output("settle", number)
    if o.assign or o.unassign:
        reply = _assign(run, number, o)
        return reply + (_reserve(run, number, commenter) if name == "take" and o.assign and reply == o.reply else "")
    if isinstance(cmd, commands.Address) and o.reply == commands.reply("understood", cmd, login=commenter.get("login")):
        return o.reply + _bound_note(run, commenter, cmd.address)
    return o.reply


def _appeal(run: Run, cmd, said: dict, on: dict) -> str:
    """`/knos appeal <reason>` on a pull request (knos.appeal): its author contests a rejection. The verdict the pull
    request has is what the judge's memory holds of its settlement (the knos-memory issue): paid is accepted, a work
    order it did not take is rejected, and with neither there is nothing to appeal. The appeal is remembered there
    too, so it is opened once. Nothing is moved: the reply says where the money is and who decides next."""
    from . import appeal
    from .proof import history, memory
    number, commenter = int(on["number"]), said.get("user") or {}
    pull = _pull(run, number)
    if pull is None:
        run.failed = True
        return "Knos: GitHub did not answer for this pull request, so no appeal was opened. Post the comment again."
    store = _memory(run)
    if store is None:
        run.failed = True
        return "Knos: the judge's memory (the knos-memory issue) could not be read, so no appeal was opened. Post the comment again."
    mine = [b for _name, b in store.rows("settlement") if isinstance(b, dict) and b.get("repo") == history.repo_key(run.repo) and b.get("pull") == number]
    verdict = "accepted" if any(b.get("paid") for b in mine) else "rejected" if any(b.get("refused") for b in mine) else ""
    if not verdict:         # nothing settled yet, which is not an accepted verdict (appeal.nothing)
        return appeal.refused_reply(appeal.Refused("appeal.unjudged"))
    facts, bought = _context(run, pull)
    contract = str((bought or {}).get("contract") or "")
    if verdict == "rejected" and contract:       # an order under Knos Terms 3: its terms say how long a rejection can be appealed
        try:
            doc = _terms3_cited(run, contract)
        except Exception as why:  # noqa: BLE001
            run.failed = True
            return f"Knos: the terms this order was funded under could not be read from GitHub ({_short(why)}), so no appeal was opened. Post the comment again."
        at = max((float(b.get("at") or 0) for b in mine if b.get("refused")), default=0.0)
        late = appeal.window_closed(doc, at, run.clock()) if doc is not None and at else ""
        if late:
            return late
    issue = (facts.get("issue") or {}).get("number") if isinstance(facts.get("issue"), dict) else None
    thash = hashlib.sha256(terms.canonical(bought)).hexdigest() if bought else ""
    head = str((pull.get("head") or {}).get("sha") or "")
    record, reply = appeal.from_comment(cmd.reason, repo=run.repo, pull=pull, commenter=str(commenter.get("login") or ""), now=run.clock(), verdict=verdict,
                                        store=store, scope=thash, key=issue or number, artifact=head, evaluator="knos", run=head or number, terms_hash=thash,
                                        mode=str((bought or {}).get("mode") or "tests"), arbiter=str((bought or {}).get("arbiter") or ""),
                                        order_state="paid" if verdict == "accepted" else "open" if bought else "none")
    if record is not None and memory.push(run.repo, store, run.github, run.github, str(run.env.get("GITHUB_RUN_ID") or "")) is None:
        run.note("Knos: the appeal was opened, and could not be written to the knos-memory issue; a second comment would open it again.")
    return reply


def _bounty(run: Run, rp: dict | None, n: int) -> dict | None:
    """The terms of an issue's bounty (its largest open job); None when it has none. Raises when the repository, the
    chain or the terms on it cannot be read: "no bounty" is never said on a guess."""
    if rp is None:
        raise OSError("GitHub did not answer for this repository")
    live = [(a, j, False) for a, j in _jobs(run, rp["id"], n) if j.state == "open"]
    live += [(a, o, True) for a, o in _orders(run, rp["id"], n) if o.state == "open"]
    for address, j, order in sorted(live, key=lambda x: -x[1].amount):
        c = Case(n, False, [(address, j)], order=order)
        _terms_of(run, c)
        if c.terms:
            return c.terms
        if c.unread:
            raise OSError(c.unread[0])
    return None


def _context(run: Run, pull: dict) -> tuple[dict, dict | None]:
    """For a comment on a pull request: the issue whose bounty it is for (the first funded one it closes, else the
    one it closes), what GitHub says about both, and that bounty's terms. What cannot be had is left out, and
    knos.who then holds nothing against anyone on it."""
    number, rp = int(pull["number"]), _repo(run)
    closes = closing.closed_by(pull, closing.read(run.repo, number, run.github))[:MAX_ISSUES]
    issue, bought = (closes[0] if len(closes) == 1 else ""), None
    for n in closes:
        try:
            bought = _bounty(run, rp, n)
        except Exception:  # noqa: BLE001
            bought = None
        if bought:
            issue = n
            break
    return who.read(run.repo, number, issue, run.github), bought


def _bound_note(run: Run, commenter: dict, address: str) -> str:
    """After a `/knos address`: when a wallet is already bound to that account, where the money will really go."""
    try:
        bind = pay.read_bind(run.ledger.account(pay.bind_pda(int(commenter["id"]))))
    except Exception:  # noqa: BLE001 - the reply already says a bound wallet comes first
        return ""
    if bind is None or str(bind.wallet) == address:
        return ""
    return f" A wallet is bound to @{commenter.get('login')}'s GitHub account already (`{bind.wallet}`), so the payment goes there."


def _assign(run: Run, number: int, o) -> str:
    """Do what a take or a release asks of the issue's assignees, and only then say it was done: GitHub quietly
    ignores a login it will not assign."""
    path = f"repos/{run.repo}/issues/{number}/assignees"
    try:
        if o.unassign:
            run.github(path, {"assignees": list(o.unassign)}, "DELETE")
        if o.assign:
            now = run.github(path, {"assignees": list(o.assign)})
            have = {str(a.get("login") or "").lower() for a in (now or {}).get("assignees") or [] if isinstance(a, dict)}
            missing = [x for x in o.assign if str(x).lower() not in have]
            if missing:
                return (f"Knos: GitHub did not assign @{missing[0]} to issue #{number}, so nothing was reserved. A maintainer can "
                        "assign them with GitHub's own assignee control.")
    except Exception as why:  # noqa: BLE001
        run.failed = True
        return (f"Knos: GitHub did not change who issue #{number} is assigned to ({_short(why)}), so nothing was "
                f"{'reserved' if o.assign else 'released'}. Post the comment again.")
    return o.reply


def _can_write(run: Run, rp: dict, account: dict) -> bool | None:
    """Whether this account may fund here: the repository's owner, and whoever GitHub answers write, maintain or admin
    for (GET /repos/{repo}/collaborators/{login}/permission), never the label on a comment. None: GitHub did not
    answer. The chain then holds the commenter to the Balance: its owner's, or a spender its wallet listed."""
    if account.get("id") and account["id"] == rp["owner"]:
        return True
    return who.is_maintainer(account.get("login"), who.permission_of(run.repo, run.github))


def _fund(run: Run, cmd, said: dict, on: dict, pull: dict | None, att=None) -> str:
    """`/knos fund` and `/knos tip`: only for someone who can write to the repository. Fix the terms, choose the
    Balance, have GitHub sign exactly that, carry it to the chain, and say what is now in escrow. Every way it can
    stop says what was not done and what to type.

    With `att` it is an attestor's run funding a PRIVATE order: `run` is the Run that reads the private repository
    (`Run.reads`), and every rule is the same one, asked of that repository: its commenter must be able to write
    there, the policy (the attestor's) must allow them, the terms are built from its default branch. What differs is
    what is signed and where it goes: the Balance is one of the attestor repository's owner that lists whoever
    started the attestor's run; the audience names issue 0 and a hash of the order's scope and terms; the salt and
    the terms are written on the private issue BEFORE GitHub is asked to sign (an order whose salt was lost could not
    be paid); and the token is posted in the attestor repository."""
    number, commenter, tip, offer = int(on["number"]), said.get("user") or {}, isinstance(cmd, commands.Tip), isinstance(cmd, commands.Offer)
    by_comment = "comment" in run.event or att is not None
    again = "post the comment again" if by_comment else "post the `/knos fund` line as a comment here"
    retry = again.capitalize()                     # the same words, to start a sentence with
    since = who._ts(said.get("created_at")) or run.began
    after = "the comment" if by_comment else "the issue was opened"
    rp = _repo(run)
    if rp is None:
        run.failed = True
        return f"Knos: GitHub did not answer for this repository, so nothing was funded. {retry}."
    may = _can_write(run, rp, commenter)
    if may is None:
        run.failed = True
        return (f"Knos: GitHub did not answer whether @{commenter.get('login')} can write to this repository, so nothing was "
                f"funded. {retry}.")
    # the playground (knos.playground): one repository where an account that cannot write may fund a test task, from the faucet only
    stranger = not may and att is None and isinstance(cmd, commands.Fund) and playground.is_playground(run.repo, rp["owner"], _devnet(run))
    if stranger:
        no = playground.refuses(run.github, run.repo, run.event, cmd.units, run.now())
        if no:
            return no
    elif not may:
        return commands.reply("not_allowed", cmd, who=WRITERS)
    if str(run.env.get("GITHUB_RUN_ATTEMPT") or "1") != "1":      # the chain refuses it: a re-run keeps the first actor's name
        return f"Knos: nothing was funded. This is a re-run, and money moves only on the first run of a comment. {retry}."
    if not tip and on.get("state") == "closed":
        return f"Knos: issue #{number} is closed, so nothing was funded. Reopen it and {again}."
    asked = cmd         # as the funder wrote it: what they left unsaid is what memory may propose
    plan: dict | None = None    # a work order's options (knos_pay 2.1); None: a job, as before
    if not tip and (offer or run.version() or att is not None):
        planned = _order_plan(run, rp, cmd, commenter, again, att, on)
        if isinstance(planned, str):
            return planned
        plan = planned
        cmd = plan["cmd"]
    elif getattr(cmd, "auto", False) or getattr(cmd, "quorum", None) or getattr(cmd, "judge", None):
        return ("Knos: nothing was funded. `auto`, `quorum` and `judge` are options of a work order, and the escrow on this cluster does not hold "
                f"work orders yet (knos_pay 2.1 is not live here). Leave them out, then {again}.")
    elif getattr(cmd, "grace", False):
        return ("Knos: nothing was funded. `grace` is an option of a work order, and the escrow on this cluster does not hold work orders yet "
                f"(knos_pay 2.2 is not live here). Leave it out, then {again}.")
    try:
        paused = pay.read_pause(run.ledger.account(pay.pause_pda()))
        if paused > run.now():
            return (f"Knos: nothing was funded. New funding is paused on Solana until {who.when(paused)} (a pause lasts "
                    f"{pay.PAUSE_MAX // 86_400} days at most); payments, refunds and withdrawals go on. {retry} after that.")
        pays = att.rp if att is not None else rp      # whose money: the repository the fund token is minted in, and its owner
        if plan is not None:    # the funder pays the fee on top, as the program that is live takes it: the Balance has to hold both
            rule = fees.rule(run.version())
            plan["fee"] = rule.order(cmd.units, rule.plan_bps(pay.read_plan(run.ledger.account(pay.plan_pda(pays["owner"]))), run.now()))
        balance, mint_, faucet, no = _balance(run, pays, att.actor if att is not None else commenter, cmd, number, again,
                                              plan["fee"] if plan else 0, plan is not None)
        if stranger and balance is not None and not faucet:
            return "Knos: nothing was funded. In the playground only the devnet faucet pays."
        if att is not None:
            balance, no = _listed_for(run, att, balance, faucet, no, again)
        elif plan is not None and balance is not None:
            plan["seq"] = max([o.seq + 1 for _a, o in _orders(run, rp["id"], number) if str(o.source) == str(balance)], default=0)
    except Exception as why:  # noqa: BLE001 - the chain did not answer
        run.failed = True
        return f"Knos: Solana could not be read just now ({_short(why)}), so nothing was funded. {retry}."
    if balance is None:
        return no
    payee = ""
    if tip:     # money that could reach nobody is not put in escrow
        comments = terms.pages(f"repos/{run.repo}/issues/{number}/comments", run.github)
        paid = who.payee(pull or {}, None, None, comments, None, who.permission_of(run.repo, run.github), None, run.clock(), "",
                         who.user_of(run.github), strict=True, tip=True)
        if not paid.get("id"):
            fix = f"{retry}." if paid.get("kind") == "unread" else f"{paid.get('fix', '')} Then {again}."
            return f"Knos: no tip was sent: {paid['why']}. {fix.strip()}"
        payee = str(paid.get("login") or "")
    try:
        built = _built(run, cmd, rp, number, merge_only=att is not None)
        data = terms.canonical({**built.terms, **(plan["terms"] if plan else {})})
    except terms.Refused as why:
        return f"Knos: {why}"
    except OSError as why:      # the acceptance checks: not knowing whether there are any is not "there are none"
        run.failed = True
        return (f"Knos: GitHub did not answer for this issue's acceptance checks (.knos/acceptance/{number}/ on the default "
                f"branch: {_short(why)}), so the bounty's terms could not be fixed and nothing was funded. {retry}.")
    doc = None          # the repository's Knos Terms 3 document (`.knos/terms.json`), when it has one: the order is then held to it
    if not tip and not offer and att is None:
        try:
            doc = _terms3(run, rp["branch"])
        except terms3.Refused as why:
            return (f"Knos: nothing was funded. `{TERMS3}` on the default branch says it is a Knos Terms 3 document, and it is not one an order can "
                    f"be funded on: {_short(why).rstrip('. ')}. Fix the file (`knos terms verify` reads it the same way), then {again}.")
        except OSError as why:
            run.failed = True
            return (f"Knos: GitHub did not answer for this repository's terms (`{TERMS3}` on the default branch: {_short(why)}), so nothing was "
                    f"funded. {retry}.")
    if getattr(cmd, "cited", False) and doc is None:
        return (f"Knos: nothing was funded. `/knos fund terms` funds the order this repository's terms describe, and it has none: there is no "
                f"`{TERMS3}` on the default branch. `knos terms propose` writes one from the repository's own checks; or comment "
                "`/knos fund <amount>`.")
    if doc is not None and not run.version():
        return (f"Knos: nothing was funded. This repository's terms (`{TERMS3}`, Knos Terms 3) describe a work order, and the escrow on this "
                "cluster does not hold work orders yet (knos_pay 2.1 is not live here).")
    if doc is not None and plan is not None:        # terms 3, enforced: an order that says anything the document does not is not funded
        built, differs = _terms3_order(doc, cmd, plan, built)
        if differs:
            return (f"Knos: nothing was funded. This repository's terms (`{TERMS3}`: {doc['name']} version {doc['version']}) and this order "
                    f"do not say the same thing. {' '.join(differs)} Comment `/knos fund terms` to fund exactly what the terms say, or "
                    "publish a new version of the terms first.")
        try:
            data = terms.canonical({**built.terms, **plan["terms"]})
        except terms.Refused as why:
            return f"Knos: {why}"
    if plan is None:        # a tip, and a job where the escrow holds no work orders: no order plan asked the procurement gate, so it is asked here
        refused = _gated(run, rp, cmd, commenter, number, again, "Knos: no tip was sent. " if tip else "Knos: nothing was funded. ")
        if refused:
            return refused
    work = (terms.TIP_DAYS if tip else cmd.days) * 86_400
    mode = pay.TESTS if built.terms["mode"] == "tests" else pay.MERGE
    if plan and plan.get("auto") and mode != pay.TESTS:     # the chain refuses it too: AUTO goes with mode 1 and nothing else
        told = [n for n in built.notes if "acceptance checks" in n]
        return ("Knos: nothing was funded. `auto` pays the first pull request that passes the acceptance checks, without a merge, so "
                "those checks must be black-box. " + (f"{' '.join(told)} Do that, or leave out `auto`; then {again}." if told else
                f"Issue #{number} has none: add `.knos/acceptance/{number}/` on the default branch with a `blackbox.sh` that runs the pull "
                f"request's code through `$KNOS_RUN` and compares its output, or leave out `auto`; then {again}."))
    hidden = order = None
    if att is not None:     # the audience is public: it names issue 0 and sha256(scope || terms hash), and the salt stays on the private issue
        salt = run.salt()
        hidden = pay.scope_of(rp["id"], number, salt) + hidden_terms(salt, data)
        order = pay.order_pda(hidden[:32], balance, 0)
        if not run.say(number, _keep(said, order, salt, data, att)):
            return ""           # the token cannot write here, so nothing can be said here either: the attestor's own log counts it
    try:
        jwt = run.mint(pay.fund_audience(number, cmd.units, mode, pay.terms_hash(data), balance, work) if plan is None else
                       pay.order_fund_audience(0, cmd.units, mode, pay.private_fund_terms(hidden[:32], hidden[32:]), balance, work, 0, plan["opts"])
                       if hidden else
                       pay.order_fund_audience(number, cmd.units, mode, pay.terms_hash(data), balance, work, plan["seq"], plan["opts"]))
    except Exception as why:  # noqa: BLE001
        run.failed = True
        return f"Knos: GitHub did not sign the request ({_short(why)}), so nothing was funded. {retry}."
    if hidden:
        r = _carried(run, "fund", jwt, since, hidden.hex().encode())
        made = pay.read_order(run.ledger.account(order)) if r["ok"] else None
        if made is not None:
            r.update(order=str(order), amount=made.amount, fee=made.fee, deadline=made.deadline, faucet=made.faucet)
            att.funded += 1
        elif r["ok"]:
            r.update(ok=False, why="the relay answered, and Solana does not show the order")
    else:
        r = deliver("fund", jwt, number, data, run=run, since=since)
    what = "the tip" if tip else "the bounty"
    if not r["ok"]:
        run.failed = True
        if r.get("timeout"):
            return (f"Knos: not confirmed yet. GitHub signed the request (it is posted {'in ' + att.run.repo if att is not None else 'above'}) and no relayer carried it to Solana "
                    f"within {RELAY_WAIT // 60} minutes. Solana takes the signed token until an hour after it expires: if one carries it, {what} is funded"
                    + (f", and {att.run.repo} pays it like any other. " if att is not None else ", and `/knos status` shows it. ") + f"Otherwise {again}.")
        cause = r["why"].rstrip(". ")
        if any(cause.startswith(x) for x in _BALANCE_LIMITS):     # the Balance's own limits: the same comment is refused the same way
            before = any(x in cause for x in _BALANCE_LIMITS[1:]) or "spent today" in cause     # the relay's check (relay._limits), before any transaction
            fix = "its wallet raises the limit" if cause.startswith(pay.ERRORS[100]) else "its wallet changes what it allows"
            return ("Knos: nothing was funded. GitHub signed the request, and "
                    + ("the relay refused it before anything was sent to Solana" if before else "Solana did not take it") + f": {cause}. Posting the "
                    f"comment again changes nothing until {fix} (it signs knos_pay's SetBalanceX: `knos.settle.v2.pay.set_balance_x_ix` builds "
                    "the instruction)" + (", or a smaller `/knos fund` fits under it." if cause.startswith(pay.ERRORS[100]) else "."))
        return (f"Knos: nothing was funded. GitHub signed the request and Solana did not take it: {cause}. To try "
                f"again, {again}.")
    money = f"{_amount(r.get('amount') or cmd.units)} {_money(run, mint_)}"
    took = f"{r['seconds']} s after {after}"
    if plan is not None:
        cited = f"\n\n{terms3.cite(doc)}." if doc is not None else ""       # the sentence a contract carries: these terms, this version, this hash
        return _funded_order(run, cmd, rp, number, balance, mint_, r.get("faucet", faucet), plan, built, r, money, took, work) + cited + (
            _proposed(run, asked, built) if att is None else "")     # (the judge's memory is an issue of the repository, and an attestor keeps none there)
    job = _link(run, "job on Solana", "address", r.get("job") or pay.job_pda(rp["id"], number, balance))
    if tip:
        run.output("settle", number)
        return (f"Knos: a tip of {money} for this pull request is in escrow ({job}), {took}. It is paid to @{payee} next; the "
                "result follows here.")
    told = _told(built)
    deadline = who.when(r.get("deadline") or run.now() + work)
    source = "the devnet faucet" if r.get("faucet", faucet) else f"the balance `{balance}`"
    return "\n\n".join((
        f"Knos: {money} from {source} is in escrow for issue #{number} ({job}), {took}.",
        " ".join([*told[:-1], *built.notes, f"If it is not paid by {deadline}, the money goes back to where it came from."]),
        f"To earn it: open a pull request whose description says `Fixes #{number}`. {told[-1]} For the money to reach you when it "
        "is paid, comment `/knos address <your Solana address>` on your pull request; without an address it waits for you "
        f"until you bind a wallet ({HOLD_DAYS} days at most).")) + _proposed(run, asked, built)


TERMS3 = ".knos/terms.json"             # the repository's Knos Terms 3 document (knos.terms3), on its default branch
TERMS3_HISTORY = 20                     # how many past versions of that file are looked through for the one an order cites


def _terms3(run: Run, ref: str) -> dict | None:
    """The repository's Knos Terms 3 document at one commit or branch, validated; None when it has no `.knos/terms.json`
    there, or that file is not Knos Terms 3 (an older format keeps its meaning). Raises OSError when GitHub does not
    answer for the file (not knowing is not "there is none"), and knos.terms3.Refused, with the words, for a file that
    says it is terms 3 and is not a document an order can cite."""
    try:
        got = run.github(f"repos/{run.repo}/contents/{TERMS3}?ref={urllib.parse.quote(str(ref), safe='')}")
    except OSError as why:
        if getattr(why, "code", None) != 404:
            raise
        return None
    if got is None:
        return None
    try:
        text = base64.b64decode(got["content"]).decode("utf-8") if got.get("encoding") == "base64" else None
    except (AttributeError, KeyError, TypeError, ValueError):
        text = None
    if text is None:
        raise OSError(f"GitHub's copy of {TERMS3} was not understood")
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return terms3.validate(data) if terms3.is_terms3(data) else None


def _terms3_order(doc: dict, cmd, plan: dict, built: terms.Built) -> tuple[terms.Built, list[str]]:
    """An order about to be funded, held to the Knos Terms 3 document of its repository: (the terms it is funded on,
    which carry `contract`, the document's hash, and the document's protected paths; what the order says that the
    document does not, one sentence each: knos.terms3.check_order). The checks, the acceptance suite and the image are
    still the repository's own as `_built` found them: when they are not the ones the document names, that is one of
    the sentences."""
    try:
        want = terms3.order_terms(doc)
    except terms3.Refused as why:
        return built, [f"{_short(why).rstrip('. ')}."]
    mine = {**built.terms, "deny": want["deny"], "contract": terms3.digest(doc)}
    held = plan["holdback"] // 100 if plan["holdback"] % 100 == 0 else plan["holdback"] / 100
    said = terms3.check_order(doc, units_=cmd.units, days=cmd.days, holdback=held, warranty=plan["warranty"], quorum=plan.get("quorum") or 1,
                              order_terms_=mine, arbiter=plan.get("arbiter") or "")
    if plan.get("grace") and doc["deadline"]["late"] == "refused":
        said.append("The order asks for `grace` (a token issued by the deadline is taken for a while after it); the terms say a token presented "
                    "late is refused.")
    return built._replace(terms=mine), said


def _declared(run: Run, order_terms: dict) -> list:
    """The accounts the order's Knos Terms 3 document declares to be one party (`evaluators.related`), for a receipt's
    assurance level. [] when the order cites no such document, when the version it cites is not found, or when
    GitHub does not answer: nothing is declared on a guess, and a receipt is written all the same."""
    contract = order_terms.get("contract") if isinstance(order_terms, dict) else None
    if not contract:
        return []
    try:
        doc = _terms3_cited(run, str(contract))
        return terms3.declared(doc) if doc is not None else []
    except Exception:  # noqa: BLE001 - best effort: the level is then computed from the ids alone
        return []


def _terms3_cited(run: Run, contract: str) -> dict | None:
    """The Knos Terms 3 document whose hash an order's terms carry (`contract`): the repository's `.knos/terms.json` on
    its default branch, or the past version of that file with that hash (a version never changes; a change is a new
    file with its own hash). None when none of the last TERMS3_HISTORY versions is it. Raises OSError when GitHub
    does not answer."""
    refs: list[str] = [str(_repo_known(run)["branch"])]
    try:
        past = run.github(f"repos/{run.repo}/commits?path={urllib.parse.quote(TERMS3, safe='')}&per_page={TERMS3_HISTORY}")
    except OSError as why:
        if getattr(why, "code", None) != 404:
            raise
        past = None
    refs += [str(c.get("sha")) for c in (past if isinstance(past, list) else []) if isinstance(c, dict) and c.get("sha")][:TERMS3_HISTORY]
    for ref in dict.fromkeys(refs):
        try:
            doc = _terms3(run, ref)
        except terms3.Refused:
            continue
        if doc is not None and terms3.digest(doc) == contract:
            return doc
    return None


def _terms3_signer(run: Run, c: "Case", jwt: str, pull: dict) -> bool:
    """Whether the run that GitHub just signed `jwt` for may judge this case. An order funded with no terms 3 (its
    terms carry no `contract`): yes, as before. One funded under Knos Terms 3: only when that document names an
    evaluator with the token's issuer, repository and workflow (knos.terms3.evaluator_allowed; an evaluator written as
    anyone's repository is never a party's: the order's owner, the pull request's author, a payee). Otherwise the
    case says why (`c.why`, or `c.unread` when the document could not be had) and nothing is sent."""
    contract = str((c.terms or {}).get("contract") or "")
    if not contract:
        return True
    try:
        doc = _terms3_cited(run, contract)
    except Exception as why:  # noqa: BLE001 - GitHub did not answer
        c.unread.append(f"the terms this order was funded under (`{TERMS3}`) could not be read from GitHub ({_short(why)})")
        return False
    if doc is None:
        c.unread.append(f"the terms this order was funded under (Knos Terms 3, sha256 {contract[:16]}) are not among the last versions of "
                        f"`{TERMS3}` in this repository, so who may judge it could not be checked")
        return False
    got = _claims(jwt)
    issuer, where, workflow = str(got.get("iss") or terms3.GITHUB), str(got.get("repository") or ""), str(got.get("job_workflow_ref") or "")
    parties = (run.repo.split("/")[0], str((pull.get("user") or {}).get("login") or ""), *(str(p[3] or "") for p in c.payees))
    if terms3.evaluator_allowed(doc, issuer, where, workflow, tuple(p for p in parties if p)) is not None:
        return True
    names = ", ".join(f"`{e['name']}`" for e in doc["evaluators"]["list"]) or "none"
    c.why.append(f"its terms (Knos Terms 3: {doc['name']} version {doc['version']}) name who may judge it ({names}), and this run is none of "
                 f"them: it ran `{_plain(workflow.split('@')[0]) or 'no workflow GitHub named'}` in {_plain(where) or 'a repository GitHub did not name'}")
    c.fix.append("A run of a workflow the terms name signs for it: the workflow file calls that workflow, in a repository the terms allow.")
    return False


PROCUREMENT = ".knos/procurement"         # knos.controls.PROCUREMENT: the buyer's rate cards, standing offers, envelopes, approval policy and approvals


def _procurement(run: Run, rp: dict) -> dict[str, str]:
    """{path: text} of every file under .knos/procurement/ on the default branch, one folder deep (the policy and the
    approvals log, and the rate cards, offers and envelopes in their folders); {} for a repository that has none.
    Raises OSError when GitHub says the folder is there and does not give a file of it: a gate nobody could read is
    not a gate that passed."""
    ref = urllib.parse.quote(str(rp.get("branch") or "main"), safe="")

    def listed(path: str) -> list | None:
        try:
            got = run.github(f"repos/{run.repo}/contents/{path}?ref={ref}")
        except OSError as why:
            if getattr(why, "code", None) != 404:
                raise
            return None
        return got if isinstance(got, list) else None
    top = listed(PROCUREMENT)
    if not top:
        return {}
    rows = [e for e in top if isinstance(e, dict)]
    for folder in [e for e in rows if e.get("type") == "dir"]:
        rows += [e for e in listed(str(folder.get("path"))) or [] if isinstance(e, dict)]
    files: dict[str, str] = {}
    for e in rows[:400]:
        path = str(e.get("path") or "")
        if e.get("type") != "file" or not path.startswith(PROCUREMENT + "/"):
            continue
        got = run.github(f"repos/{run.repo}/contents/{urllib.parse.quote(path)}?ref={ref}")
        try:
            files[path] = base64.b64decode(got["content"]).decode("utf-8")
        except (AttributeError, KeyError, TypeError, ValueError):
            raise OSError(f"GitHub's copy of {path} was not understood") from None
    return files


def _gated(run: Run, rp: dict, cmd, commenter: dict, number: int, again: str, stop: str = "Knos: nothing was funded. ") -> str:
    """The procurement gate, asked on every route by which this workflow sets money aside: "" when the funding may go
    on, else the reply. A repository with no file under .knos/procurement/ is held to nothing more (one question to
    GitHub, answered no). With files: a standing offer needs an approved offer file that names this vendor, rate and
    cap (knos.approvals.gate); a plain order, a private order and a tip need the commenter to hold the requester
    role and the policy's approvals for `issue:<number>` (a tip: `tip:<number>`) at exactly this amount
    (knos.approvals.gate_order). The files are those of the repository the comment is in, on its default branch."""
    try:
        files = _procurement(run, rp)
    except OSError as why:
        run.failed = True
        return stop + f"This repository has procurement files, and they could not be read from GitHub ({_short(why)}). {again.capitalize()}."
    if not files:
        return ""
    from . import approvals
    repo_, today = run.repo, time.strftime("%Y-%m-%d", time.gmtime(run.clock()))
    fetch = lambda cid: _read(run, f"repos/{repo_}/issues/comments/{int(cid)}") if cid else None  # noqa: E731
    if isinstance(cmd, commands.Offer):
        ok, said = approvals.gate(files, vendor=cmd.vendor, rate=cmd.rate, budget=cmd.units, on=today, fetch=fetch)
        how = ""
    else:
        subject = f"{'tip' if isinstance(cmd, commands.Tip) else 'issue'}:{number}"
        ok, said = approvals.gate_order(files, subject=subject, requester=str(commenter.get("login") or ""), amount=cmd.units, on=today, fetch=fetch)
        how = (f" An approver comments `{approvals.comment_line(subject)}`, and `knos approve record --subject {subject} --requester "
               f"{_plain(commenter.get('login'))} --amount {commands.amount(cmd.units)}` adds it to `{PROCUREMENT}/{approvals.LOG}`.")
    return "" if ok else stop + f"{said} The files under `{PROCUREMENT}/` on the default branch decide this; once they allow it, {again}.{how}"


def _judge_repo(run: Run, rp: dict, name: str, commenter: dict, on: dict | None, again: str) -> tuple[str, int] | str:
    """The judge repository a funding comment names (`judge: owner/repo`), as (its full name, its id): the id is what
    the order's options carry and what knos_pay holds a judge's token to (order_judge.rs, judge c). Or the words that
    say why it cannot be a third reader: GitHub does not know it, it is the buyer's own repository, or its owner is
    the buyer repository's owner, the funder, or whoever the issue is assigned to (the one who would be paid). Two
    repositories of one owner are one judge, and the chain cannot see who owns a repository: it is refused here."""
    shown = _plain(name)
    got = _read(run, f"repos/{name}")
    try:
        full, jid, owner = str(got["full_name"]), int(got["id"]), got["owner"]
        owner_id, login = int(owner["id"]), str(owner.get("login") or "")
    except (KeyError, TypeError, ValueError):
        return f"GitHub gave no repository named {shown} that this run can read (the judge). Check the name, then {again}."
    another = f"Name a repository that someone else owns, then {again}."
    if jid == rp["id"]:
        return (f"`judge: {shown}` is this repository, and its own run is already one of the readers: it would count once. {another}")
    sides = [(rp["owner"], "this repository's owner"), (commenter.get("id"), "you, the funder")]
    sides += [(a.get("id"), f"@{_plain(a.get('login'))}, who holds this issue and would be paid") for a in (on or {}).get("assignees") or []
              if isinstance(a, dict)]
    for uid, role in sides:
        if uid and int(uid) == owner_id:
            return (f"`judge: {shown}` belongs to @{_plain(login)}, and so does a side of this order ({role}). Two accounts of one owner are "
                    f"one judge, not two. {another}")
    return full, jid


def _order_plan(run: Run, rp: dict, cmd, commenter: dict, again: str, att=None, on: dict | None = None) -> dict | str:
    """What a funding comment fixes about a work order beside its amount and its terms, or the reply that says why
    nothing is funded. The repository's .knos/policy.yml speaks first (who may fund, the cap per order, the monthly
    budget, which vendors an offer may name; a policy that cannot be used stops funding), then gives the defaults
    (checks, warranty, holdback, arbiter), and the comment's own words override those. A public order is NEUTRAL
    unless the funder says `neutral off`. Returns {"cmd" (with the policy's checks when the funder named none),
    "opts" (the 48 bytes the audience carries), "terms" (what the terms say beside the usual: the policy's hash, an
    offer's vendor), "warranty", "holdback", "arbiter", "neutral", "vendor", "from_policy", "fee", "seq", "attestor"}.
    With `att` (an attestor's run) the order is PRIVATE: never neutral, its judge the attestor repository, its scope
    salted. A policy that says `private: true` funds nothing any other way."""
    offer, stop = isinstance(cmd, commands.Offer), "Knos: nothing was funded. "
    if not run.version():
        return (stop + "A standing offer is a work order, and the escrow on this cluster does not hold work orders yet (knos_pay 2.1 "
                "is not live here). `/knos fund <amount>` puts a bounty on this issue today.")
    low, high = pay.ORDER_MIN_AMOUNT, pay.MAX_AMOUNT
    if not low <= cmd.units <= high:
        form = (f"/knos offer @{cmd.vendor} rate {commands.amount(min(cmd.rate, high))} budget {commands.amount(high)}" if offer and cmd.units > high
                else f"/knos offer @{cmd.vendor} rate {commands.amount(cmd.rate)} budget {commands.amount(low)}" if offer else f"/knos fund {commands.amount(low)}")
        return (stop + f"A work order holds from {commands.amount(low)} to {commands.amount(high)}, and this one asks for "
                f"{commands.amount(cmd.units)}. Comment `{form}` instead.")
    rules, unusable = _policy(run, rp)
    if unusable:
        return stop + f"{unusable[0].upper()}{unusable[1:]}, and funding stops until it can be. Fix `{policy.PATH}` on the default branch, then {again}."
    d = policy.order_opts(rules, cmd.vendor if offer else None) if rules is not None else {}
    if rules is not None:
        try:
            spent = run.spent((att.rp if att is not None else rp)["owner"]) if rules.monthly_budget is not None else 0
        except Exception as why:  # noqa: BLE001 - a budget nobody could check is not a budget that holds
            run.failed = True
            return (stop + f"`{policy.PATH}` sets a monthly budget, and what was funded this month could not be read from Solana "
                    f"({_short(why)}). {again.capitalize()}.")
        ok, refusal = policy.allows(rules, commenter.get("id"), Decimal(cmd.units) / 10 ** 6, spent, str(commenter.get("login") or ""))
        if not ok:
            return stop + f"{refusal} Someone who can write to this repository changes that file on its default branch."
        if offer and rules.vendors is not None and cmd.vendor.lower() not in rules.vendors:
            return (stop + f"`{policy.PATH}` lists the vendors a standing offer may pay ({', '.join(rules.vendors)}), and @{cmd.vendor} is "
                    "not one of them. Add them to `vendors` there first.")
    # the buyer's own procurement files, when the repository has them: an offer funds only when they approve it
    # (knos.approvals.gate), and any other order only when its amount is approved (knos.approvals.gate_order)
    refused = _gated(run, rp, cmd, commenter, int((on or {}).get("number") or 0), again, stop)
    if refused:
        return refused
    if d.get("private") and att is None:
        how = (f"its attestor, {rules.attestor}, funds it: comment `/knos fund` in a repository that file lists under `targets`, and that "
               "repository's workflow answers there" if rules.attestor else
               "name the repository that funds and pays them as `attestor: owner/name` there, or set `private: false`")
        return (stop + f"`{policy.PATH}` says `private: true`, and a private order is not funded by this repository's own workflow: the "
                f"token it signs would name this repository and this issue in public. Instead, {how}.")
    if att is not None and offer:
        return stop + "A private order is funded with `/knos fund <amount>`; a standing offer is not private yet."
    warranty = cmd.warranty if getattr(cmd, "warranty", None) is not None else int(d.get("warranty_days") or 0)
    holdback = cmd.holdback * 100 if getattr(cmd, "holdback", None) is not None else int(d.get("holdback_bps") or 0)
    if holdback and not warranty:
        return stop + f"`holdback` keeps a share of each payment back until the warranty ends, so it needs one: add `warranty 14`, then {again}."
    ids = {}
    for role, login in (("arbiter", getattr(cmd, "arbiter", None) or d.get("arbiter")), ("vendor", cmd.vendor if offer else None)):
        if not login:
            continue
        user = _read(run, f"users/{login}")
        if not (isinstance(user, dict) and user.get("id")):
            return stop + f"GitHub gave no account named @{_plain(login)} (the {role}). Check the name, then {again}."
        ids[role] = (str(user.get("login") or login), int(user["id"]))
    neutral = getattr(cmd, "neutral", None) is not False and att is None      # no neutral run pays a private order: there is no public record to read
    from_policy = cmd.checks is None and bool(d.get("checks"))
    if from_policy:
        cmd = replace(cmd, checks=tuple(d["checks"]))
    # `auto` and `quorum N` are options of the order, not of its terms: the fund token signs them in the 48 bytes
    auto, quorum = bool(getattr(cmd, "auto", False)), int(getattr(cmd, "quorum", None) or 0)
    if (auto or quorum) and att is not None:
        return stop + f"`auto` and `quorum` are for a public order that pays one pull request, and this one is private. Leave them out, then {again}."
    grace = bool(getattr(cmd, "grace", False))
    if grace and run.version() < fees.NEW_VERSION:      # 2.1 refuses the byte (E_TERMS): said here, before GitHub is asked to sign anything
        return (stop + f"`grace` asks that a token GitHub issued by the deadline still pays for {_days(pay.GRACE // 3600).replace('day', 'hour')} after it, and the "
                f"escrow that is live on this cluster does not know that option yet (it comes with knos_pay 2.2). Leave out `grace`, then {again}.")
    named = getattr(cmd, "judge", None)
    if named and att is not None:
        return stop + f"A private order's judge is its attestor repository already. Leave out `judge:`, then {again}."
    if named and not quorum:        # with no quorum the judge repository's word alone would pay the order
        return (stop + "`judge:` names a reader of a quorum, and this comment asks for no quorum: on its own, that repository's run could "
                f"have the order paid. Add `quorum 2` or `quorum 3`, or leave out `judge:`, then {again}.")
    judge_repo = ("", 0)
    if named:
        found = _judge_repo(run, rp, named, commenter, on, again)
        if isinstance(found, str):
            return stop + found
        judge_repo = found
    if quorum > 1 + neutral + bool(named):      # the readers a public order can have: its own run, a neutral run, a judge repository
        return (stop + f"`quorum {quorum}` asks for {terms.JUDGES[quorum]} different judges, and this order can have {1 + neutral + bool(named)}: this "
                "repository's own run" + (", and a neutral run anyone can start" if neutral else " (you said `neutral off`)")
                + (f", and the judge repository {judge_repo[0]}" if named else "")
                + ". " + (("No judge repository is named for the third: add `judge: owner/repo`, a repository that neither you nor this "
                           "repository's owner owns, or comment it with `quorum 2`") if neutral and not named else
                          "Leave out `neutral off`" + ("" if named and quorum == 3 else ", or leave out `quorum`")) + f", then {again}.")
    flags = ((pay.F_NEUTRAL if neutral else 0) | (pay.F_STANDING if offer else 0) | (pay.F_PRIVATE if att is not None else 0)
             | (order_auto.F_AUTO if auto else 0) | order_auto.quorum_flags(quorum))
    return {"cmd": cmd, "opts": pay.opts(flags, holdback, warranty, 0, cmd.reserve, cmd.rate if offer else 0, ids.get("arbiter", ("", 0))[1],
                                         att.rp["id"] if att is not None else judge_repo[1], att is not None, grace=grace),
            "grace": grace, "attestor": att.run.repo if att is not None else "",
            "terms": {**({"policy": policy.digest(rules)} if rules is not None else {}), **({"vendor": ids["vendor"][1]} if offer else {})},
            "warranty": warranty, "holdback": holdback, "arbiter": ids.get("arbiter", ("", 0))[0], "neutral": neutral,
            "vendor": ids.get("vendor", ("", 0))[0], "from_policy": from_policy, "fee": 0, "seq": 0, "auto": auto, "quorum": quorum, "judge": judge_repo[0]}


def _funded_order(run: Run, cmd, rp: dict, number: int, balance, mint_, faucet: bool, plan: dict, built, r: dict, money: str, took: str,
                  work: int) -> str:
    """The reply to a funding that opened a work order: what is in escrow and the fee its funder pays on top, the
    terms, the warranty and the arbiter, the deadline, how to earn it, and who can have it paid after a merge."""
    order = _link(run, "order on Solana", "address", r.get("order") or pay.order_pda(pay.scope_of(rp["id"], number), balance, plan["seq"]))
    fee, source = _amount(r.get("fee") or plan["fee"]), "the devnet faucet" if faucet else f"the balance `{balance}`"
    told, deadline = _told(built), who.when(r.get("deadline") or run.now() + work)
    if plan["from_policy"]:
        told[0] = told[0].replace("(the checks you named)", f"(the checks `{policy.PATH}` names)")
    if plan.get("attestor") and built.terms.get("reserve"):     # nothing answers `/knos take` in a repository that runs no Knos workflow
        told[-1] = (f"A maintainer who assigns the issue to someone reserves it for them for {_days(built.terms['reserve'])}; `/knos take` is not "
                    "answered here, because this repository runs no Knos workflow.")
    warranty = (f"Warranty: {plan['holdback'] / 100:g}% of each payment is held back for {_days(plan['warranty'])} after it is paid; if the work "
                "is reverted in that time, that part goes back to the funder." if plan["holdback"] else
                f"Warranty: {_days(plan['warranty'])}, with nothing held back." if plan["warranty"] else
                "No warranty: a payment is final when it is made.")
    arbiter = f"Arbiter: @{plan['arbiter']} rules if a payment is disputed." if plan["arbiter"] else "No arbiter is named."
    neutral = ("After a merge the seller can have it paid without this repository's workflow: `knos settle --neutral <the pull request's "
               "URL>` asks GitHub to sign in a repository of their own." if plan["neutral"] else
               f"It is a private order: Solana shows its amount and, once it is paid, who was paid and the commit that was accepted, and "
               f"never this repository, this issue or these terms. {plan['attestor']}'s workflow pays it after the merge, on its schedule or "
               "started by hand with this repository and the pull request's number." if plan.get("attestor") else
               "Only this repository's workflow can have it paid (`neutral off`).")
    back = f"If it is not paid by {deadline}, the money and the fee go back to where they came from."
    if plan.get("grace"):
        back = (f"A token GitHub issued by {deadline} still pays for {_days(pay.GRACE // 3600).replace('day', 'hour')} after it (`grace`). If it is not paid "
                "by then, the money and the fee go back to where they came from.")
    if isinstance(cmd, commands.Offer):
        vendor = plan["vendor"]
        return "\n\n".join((
            f"Knos: a standing offer for @{vendor} is in escrow on issue #{number}: {money} from {source} ({order}), {took}. The funder pays "
            f"Knos's fee of {fee} on top.",
            " ".join([f"Each pull request of @{vendor}'s that says `Fixes #{number}` and is accepted is paid {_amount(cmd.rate)} in full, until "
                      f"the {_amount(cmd.units)} is spent.", *told[:-1], *built.notes, warranty, arbiter,
                      f"What is left on {deadline} goes back to where it came from."]),
            f"For the money to reach @{vendor}, they bind a wallet to their GitHub account: {BIND}. {neutral}"))
    return "\n\n".join((
        f"Knos: {money} from {source} is in escrow for issue #{number} as a {'private ' if plan.get('attestor') else ''}work order ({order}), {took}. The funder pays Knos's fee of "
        f"{fee} on top, so whoever is paid receives the full amount.",
        " ".join([*told[:-1], *terms.describe_options(plan.get("auto", False), plan.get("quorum", 0), plan["neutral"], plan.get("judge", "")), *built.notes, warranty, arbiter, back]),
        f"To earn it: open a pull request whose description says `Fixes #{number}`. {told[-1]} For the money to reach you when it "
        "is paid, comment `/knos address <your Solana address>` on your pull request; without an address it waits for you "
        f"until you bind a wallet ({HOLD_DAYS} days at most). {neutral}"))


def _order_word(run: Run, cmd, said: dict, on: dict) -> str:
    """`/knos raise`, `/knos cancel` and `/knos split`: what each does to a work order, or why it does nothing.
    A raise is never done by a comment (TopUp takes the signature of the wallet the money came from): the reply says
    how. A cancel is signed by this repository's run and gives seven days' notice. A split is a note a maintainer
    leaves before the merge; settle reads it."""
    number, commenter, name = int(on["number"]), said.get("user") or {}, cmd.name
    again, rp = "Post the comment again.", _repo(run)
    if rp is None:
        run.failed = True
        return f"Knos: GitHub did not answer for this repository, so nothing was done. {again}"
    if name != "raise":
        may = _can_write(run, rp, commenter)
        if may is None:
            run.failed = True
            return f"Knos: GitHub did not answer whether @{commenter.get('login')} can write to this repository, so nothing was done. {again}"
        if not may:
            return commands.reply("not_allowed", cmd)
    if name == "split":
        if not run.version():
            return ("Knos: nothing was noted. A split is for a work order, and the escrow on this cluster does not hold work orders yet "
                    "(knos_pay 2.1 is not live here). `/knos pay @login` names the one person a bounty pays.")
        pull = _pull(run, number)
        if pull is None:
            run.failed = True
            return f"Knos: GitHub did not answer for this pull request, so nothing was noted. {again}"
        if pull.get("merged_at"):
            return "Knos: this pull request is already merged, and `/knos split` counts only before the merge. Nothing was noted."
        shares = ", ".join(f"@{login} {percent}%" for login, percent in cmd.shares)
        return (f"Knos: noted. If this pull request is merged and takes a work order, the order pays {shares}. Each of them needs a wallet "
                f"bound to their GitHub account ({BIND}): a split is paid only when everyone in it has one. To change it, post a new "
                "`/knos split`; to undo it, delete that comment. Do not edit it: an edited comment does not count.")
    try:
        orders = [(a, o) for a, o in _orders(run, rp["id"], number) if o.state == "open"]
        jobs = [] if orders else [(a, j) for a, j in _jobs(run, rp["id"], number) if j.state == "open"]
    except Exception as why:  # noqa: BLE001
        run.failed = True
        return f"Knos: Solana could not be read just now ({_short(why)}), so nothing was done. {again}"
    verb = "raised" if name == "raise" else "cancelled"
    if jobs:
        return (f"Knos: nothing was {verb}. The bounty on issue #{number} ({_sum(run, jobs)}) is a job, which is neither raised nor "
                f"cancelled: it runs until {who.when(max(j.deadline for _a, j in jobs))}, then the money goes back to where it came from. "
                "`/knos status` shows it.")
    if not orders:
        return f"Knos: issue #{number} has no work order, so nothing was {verb}. A maintainer opens one with `/knos fund <amount>`."
    address, o = max(orders, key=lambda x: x[1].amount)
    link = _link(run, "order on Solana", "address", address)
    if name == "raise":
        second = f"`/knos fund {commands.amount(max(cmd.units, pay.ORDER_MIN_AMOUNT))}` opens a second order beside this one."
        if o.faucet:
            return (f"Knos: nothing was added. The work order on issue #{number} ({link}) holds test USDC from the devnet faucet, and the "
                    f"faucet tops nothing up. {second}")
        # TopUp charges the live build's fee on the new whole amount, at the order's own rate where that is lower, less
        # the fee already paid (order.rs top_up), not a fee on the part added
        rule = fees.rule(run.version())
        fee = max(rule.order(o.amount + cmd.units, min(o.fee_bps or rule.bps, rule.bps), o.decimals) - o.fee, 0)
        return (f"Knos: nothing was added by this comment. The work order on issue #{number} ({link}) was funded from "
                f"{'the balance' if o.from_balance else 'the wallet'} `{o.source}`, and only {'the wallet that opened that balance' if o.from_balance else 'that wallet'} "
                f"can add to it: it signs knos_pay's TopUp for {_amount(cmd.units)} {_money(run, o.mint)}, and pays Knos's fee of {_amount(fee)} on "
                f"top, from the same place (`knos.settle.v2.pay.top_up_ix` builds the instruction). A comment cannot sign for a wallet. {second}")
    if o.cancel_at:
        return (f"Knos: the work order on issue #{number} ({link}) was cancelled on {who.when(o.cancel_at)} already. It pays what is "
                f"accepted until {who.when(o.deadline)}; then the money and the fee go back to where they came from.")
    if not o.from_balance:          # knos_pay takes no token for it (relay: "only that wallet's own signature cancels it"): nothing to sign
        return (f"Knos: nothing was cancelled, and posting the comment again would change nothing. The work order on issue #{number} ({link}) "
                f"was funded from the wallet `{o.source}`, and only that wallet can cancel it: it signs knos_pay's Cancel "
                "(`knos.settle.v2.pay.cancel_ix` builds the instruction). A comment cannot sign for a wallet. `/knos status` shows the order.")
    if str(run.env.get("GITHUB_RUN_ATTEMPT") or "1") != "1":
        return f"Knos: nothing was cancelled. This is a re-run, and GitHub's signature counts only on the first run of a comment. {again}"
    try:
        jwt = run.mint(f"knos3:cancel:{address}")
    except Exception as why:  # noqa: BLE001
        run.failed = True
        return f"Knos: GitHub did not sign the request ({_short(why)}), so nothing was cancelled. {again}"
    r = deliver("cancel", jwt, number, run=run, since=who._ts(said.get("created_at")) or run.began)
    if not r["ok"]:
        run.failed = True
        return (f"Knos: the work order on issue #{number} is not cancelled. GitHub signed the request and "
                + (f"no relayer carried it to Solana within {RELAY_WAIT // 60} minutes" if r.get("timeout") else f"Solana did not take it: {r['why'].rstrip('. ')}")
                + f". `/knos status` shows the order. {again}")
    until = who.when(min(o.deadline, run.now() + NOTICE_DAYS * 86_400))
    tx = _link(run, "transaction", "tx", r["sigs"][-1]) if r.get("sigs") else "relayed"
    kill = (f" It is reserved, so {o.kill_bps / 100:g}% of it goes to the person who holds it first." if o.kill_bps and o.reserved_by
            and o.reserved_until > run.now() else "")
    return (f"Knos: the work order on issue #{number} ({_sum(run, [(address, o)])}, {link}) is cancelled with {NOTICE_DAYS} days' notice. A "
            f"pull request that is merged and meets its terms before {until} is still paid; after that the money and the fee go back to "
            f"where they came from.{kill} ({tx}, {r['seconds']} s after the comment)")


def _reserve(run: Run, number: int, commenter: dict) -> str:
    """After a `/knos take` that assigned the issue: record the reservation on its work order too, when the order takes
    reservations (token `knos3:take:<order>:<taker's id>:<days>`). What to add to the reply; nothing when the issue
    has no such order. The assignment on GitHub stands either way: it is what settle reads."""
    try:
        rp = _repo_known(run)
        free = [(a, o) for a, o in _orders(run, rp["id"], number)
                if o.state == "open" and o.reserve_days and (not o.reserved_by or o.reserved_until < run.now())]
    except Exception:  # noqa: BLE001
        return ""
    if not free:
        return ""
    address, o = max(free, key=lambda x: x[1].amount)
    try:
        jwt = run.mint(f"knos3:take:{address}:{int(commenter['id'])}:{o.reserve_days}")
    except Exception as why:  # noqa: BLE001
        return f" The work order on Solana does not record it: GitHub did not sign the request ({_short(why)}). The assignment here holds."
    r = deliver("take", jwt, number, run=run)
    if not r["ok"]:
        return f" The work order on Solana does not record it ({r['why'].rstrip('. ')}). The assignment here holds."
    tx = _link(run, "transaction", "tx", r["sigs"][-1]) if r.get("sigs") else "relayed"
    kill = f": if the order is cancelled while you hold it, {o.kill_bps / 100:g}% of it is yours" if o.kill_bps else ""
    return f" The work order on Solana records it too{kill} ({tx})."


def _told(built: terms.Built) -> list[str]:
    """terms.describe for the reply to a funding, with the judge's assurance (in-process, black-box or hermetic) said
    before the last sentence: the replies quote the last one, about reserving, on its own. Funding buys tests mode
    only for a black-box bundle (`_built`), so tests-mode terms built here are black-box, or hermetic with an image."""
    told = terms.describe(built.terms, built.source, black_box=True if built.terms["mode"] == "tests" else None)
    return [*told[:-2], told[-1], told[-2]] if terms.assurance(built.terms, True) else told


def _built(run: Run, cmd, rp: dict, number: int, merge_only: bool = False) -> terms.Built:
    """The terms a command buys. A tip asks for nothing. A bounty: the funder's words, the default branch's rules and
    what ran on its head; and in tests mode (the default branch holds .knos/acceptance/<issue>/, and that bundle is
    black-box by knos.judge.black_box) the hash of those checks, as the judge will compute it from its checkout. A
    bundle that is not black-box buys merge mode, and the note for the funder says why and what would change it.
    Raises terms.Refused with the words for the funder, and OSError when GitHub does not say whether the issue has
    acceptance checks or what runs them."""
    if isinstance(cmd, commands.Tip):
        return terms.Built(terms.tip(), "tip", [])
    head = (_read(run, f"repos/{run.repo}/commits/{urllib.parse.quote(rp['branch'], safe='')}") or {}).get("sha")
    accept, files = _bundle(run, str(head or rp["branch"]), number)
    # paid by its checks alone (mode 1) only when they are black-box: the second deployment has no veto window, and checks that
    # share a process with the pull request's code can be made to pass from inside (docs/TAMPER.md)
    cfg = _proof_toml(run, str(head or rp["branch"])) if accept else {}
    fooled = _not_black_box(run, str(head or rp["branch"]), files, cfg) if accept else ""
    required = runs = statuses = None
    if cmd.checks != () and head:        # `checks: none` asks nothing of the repository
        required = terms.required_checks(run.repo, rp["branch"], run.github)
        runs, statuses = terms.head_checks(run.repo, str(head), run.github, events=True)
    from . import judge         # the image .knos/proof.toml names for the judge is fixed at funding: the terms' hash covers it
    built = terms.build(cmd, required, runs, statuses, "" if fooled or merge_only else accept, image=judge.image_of(cfg))
    if merge_only and accept:
        built.notes.append(f"Its acceptance checks (.knos/acceptance/{number}/) are not run for a private order: the attestor never "
                           "checks this repository out, so only your merge pays it.")
    elif fooled:
        built.notes.append(f"Its acceptance checks (.knos/acceptance/{number}/) {fooled}, so only your merge pays this bounty (a "
                           "pull request can fool such checks). To have the checks alone pay, add a `blackbox.sh` there that runs "
                           "the pull request's code through `$KNOS_RUN` and compares its output.")
    return built


def _ours(run: Run, ids: list):
    """Whether a comment may spend a Balance, as a function of the Balance. Any wallet can open a Balance for any
    GitHub owner, in a token of its own making, holding any number of it, and list anyone as a spender; the owner
    spends every Balance opened for their id. If the largest simply won, a stranger could make every bounty a
    funder's comment funds be in the stranger's token. So a comment spends a Balance only when its money is the one
    Knos names on this cluster (devnet: test USDC), or when the wallet that opened it is the one bound on chain to
    the GitHub account of one of `ids` (the commenter, the repository's owner): GitHub signed that claim for the
    account's owner, so that Balance is theirs. The Binds are read once, and only when a Balance needs them. Raises
    when the chain does not answer."""
    named = {str(pay.faucet_mint()), str(pay.USDC_DEVNET)} if _devnet(run) else set()
    bound: list | None = None

    def ours(b) -> bool:
        nonlocal bound
        if str(b.mint) in named:
            return True
        if bound is None:
            binds = (pay.read_bind(run.ledger.account(pay.bind_pda(int(i)))) for i in dict.fromkeys(ids) if i)
            bound = [str(x.wallet) for x in binds if x is not None]
        return str(b.authority) in bound
    return ours


def _balance(run: Run, rp: dict, commenter: dict, cmd, number: int, again: str, fee: int = 0, order: bool = False):
    """The Balance a fund or a tip spends: (its address, its mint, whether it is the faucet's, ""), or (None, None,
    False, the reply) when there is none. It is chosen here and named in the token, and the chain spends no other:
    a Balance of the repository owner's that lists this commenter (the owner, or a spender its wallet listed), that
    a comment may spend (`_ours`: test USDC, or one the commenter's or the owner's bound wallet opened) and that
    holds the amount, the largest first; else, on devnet, the owner's faucet Balance (test money, for whoever this
    workflow lets fund: `_fund` asked GitHub that they can write). One Balance funds an issue with one job; with work
    orders (`order`) it may fund it again, and it has to hold the `fee` its funder pays on top as well."""
    uid, units = commenter.get("id"), cmd.units
    live = _jobs(run, rp["id"], number)
    real = [(a, b) for a, b in _balances(run, rp["owner"]) if not b.faucet]
    ours = _ours(run, [uid, rp["owner"]])
    listed = sorted(((a, b) for a, b in real if uid and (uid == b.owner_id or uid in b.spenders)),      # any wallet can open one:
                    key=lambda x: (not ours(x[1]), -x[1].spent, str(x[0])))[:MAX_BALANCES]              # those in use first
    mine = sorted(((_holds(run, a), str(a), a, b) for a, b in listed), key=lambda x: (not ours(x[3]), -x[0], x[1]))
    fits = [(a, b.mint, False) for held, _s, a, b in mine
            if ours(b) and held >= units + fee and (not b.cap_per_job or units <= b.cap_per_job)]
    if not fits and _devnet(run) and units <= pay.FAUCET_CAP:
        fits = [(pay.faucet_balance_pda(rp["owner"]), pay.faucet_mint(), True)]
    taken = {str(j.source): (a, j) for a, j in live}
    free = [x for x in fits if order or str(x[0]) not in taken]
    if free:
        return (*free[0], "")
    if fits:
        address, j = taken[str(fits[0][0])]
        state = f"open {_until(run, j)}" if j.state == "open" else f"held until {who.when(j.hold_until)}"
        where = "This pull request" if isinstance(cmd, commands.Tip) else f"Issue #{number}"
        return None, None, False, (
            f"Knos: nothing was added. {where} already has {_sum(run, [(address, j)])} in escrow from this balance, {state} "
            f"({_link(run, 'job on Solana', 'address', address)}). A balance holds one "
            + ("tip on a pull request at a time: comment `/knos settle` to have this one paid." if isinstance(cmd, commands.Tip) else
               "bounty on an issue at a time; `/knos status` shows it."))
    rows = []
    for held, _s, a, b in mine[:3]:
        if not ours(b):
            rows.append(f"- Balance `{a}` holds {_amount(held)} {_money(run, b.mint)}, which a comment does not spend: Knos does not "
                        "name that token, and the wallet that opened the balance is not the one bound to your GitHub account or to "
                        "this repository's owner's.")
        elif b.cap_per_job and units > b.cap_per_job:
            rows.append(f"- Balance `{a}` holds {_amount(held)} {_money(run, b.mint)}, and its wallet lets one job take at most "
                        f"{_amount(b.cap_per_job)}.")
        else:
            rows.append(f"- Balance `{a}` holds {_amount(held)} {_money(run, b.mint)}: send {_amount(units + fee - held)} more to its "
                        f"token account `{pay.baltok_pda(a)}` (a plain token transfer; anyone can).")
    if _devnet(run):
        rows.append(f"- The devnet faucet gives at most {_amount(pay.FAUCET_CAP)} test USDC for one job: "
                    f"`/knos {cmd.name} {commands.amount(pay.FAUCET_CAP)}` works now.")
    if real and not mine:
        rows.append(f"- {len(real)} Balance{'s are' if len(real) > 1 else ' is'} set aside on Solana for this repository's owner, "
                    f"and {'none lists' if len(real) > 1 else 'it does not list'} your GitHub id ({uid}) as a spender. The wallet "
                    "that opened it adds you with `knos balance set`.")
    elif not real:
        rows.append(f"- No Balance on Solana is set aside for this repository's owner (GitHub id {rp['owner']}). {OPEN}")
    need = f"{_amount(units + fee)} ({_amount(units)} and Knos's fee of {_amount(fee)} on top)" if fee else _amount(units)
    return None, None, False, (f"Knos: nothing was funded: no balance you can spend holds {need}.\n" + "\n".join(rows)
                               + f"\nThen {again}.")


def _status(run: Run, on: dict, on_pull: bool) -> str:
    """`/knos status`: on an issue, what is in escrow for it, its terms and who holds it; on a pull request, what the
    automatic check would say now: which bounty it takes, each required check, who is paid and where."""
    number, rp = int(on["number"]), _repo(run)
    if rp is None:
        run.failed = True
        return "Knos: GitHub did not answer for this repository. Comment `/knos status` again."
    if not on_pull:
        return _escrow(run, rp, on)
    pull = _pull(run, number)
    if pull is None:
        run.failed = True
        return "Knos: GitHub did not answer for this pull request. Comment `/knos status` again."
    merged, found = bool(pull.get("merged_at")), _find(run, rp, pull)
    cases, closes, listed, blind, held = found
    run.failed = run.failed or bool(blind)      # the answer is incomplete, and not for anything the commenter did
    if merged:
        runs, statuses = _record(run, (pull.get("head") or {}).get("sha") or "", cases)
        _judge(run, pull, cases, listed, True, runs, statuses)
        parts = [_after(run, c, pull, "") for c in cases] + _left_out(run, number) + _unseen(blind, number, "comment `/knos status`")
    else:
        parts, _gate_said = _advice(run, rp, pull, found, 0, True, False)
    return _join(parts or [_nothing(run, pull, closes, listed, held, False, merged)])


def _escrow(run: Run, rp: dict, on: dict) -> str:
    """What is in escrow for one issue: each job, its terms in words, its deadline, and who holds the issue."""
    n = int(on["number"])
    try:
        live = sorted([*_jobs(run, rp["id"], n), *_orders(run, rp["id"], n)], key=lambda x: -x[1].amount)
    except Exception as why:  # noqa: BLE001
        run.failed = True
        return (f"Knos: Solana could not be read just now ({_short(why)}), so what is in escrow for issue #{n} is not known. "
                "Comment `/knos status` again.")
    if not live:
        return f"Knos: nothing is in escrow for issue #{n}. A maintainer puts a bounty on it with `/knos fund <amount>`."
    parts, bought = [], None
    more, live = len(live) - MAX_CASES, sorted(live, key=lambda x: (not x[1].from_balance, -x[1].amount))[:MAX_CASES]
    for address, j in live:
        order = isinstance(j, pay.Order)
        job = _link(run, "order on Solana" if order else "job on Solana", "address", address)
        if j.state == "warranty":
            parts.append(f"The work order on issue #{n} has paid, and holds back {_amount(j.amount * j.holdback_bps // 10_000)} "
                         f"{_money(run, j.mint)} as its warranty ({job}).")
            continue
        if j.state != "open":
            parts.append(f"{_sum(run, [(address, j)])} for issue #{n} is held for GitHub user id {j.payee_id} until "
                         f"{who.when(j.hold_until)}: it is paid when they bind a wallet ({job}).")
            continue
        c = Case(n, False, [(address, j)], order=order)
        _terms_of(run, c)
        bought = bought or c.terms
        told = " ".join(terms.describe(c.terms)) if c.terms else f"Its terms are not known here: {(c.unread or c.why)[0]}."
        as_ = (" as a standing offer" if j.flags & pay.F_STANDING else " as a work order") if order else ""
        parts.append(f"{_sum(run, [(address, j)])} is in escrow for issue #{n}{as_} {_until(run, j)} ({job}). {told}")
    holds = [h for h in who.reservation(on, terms.pages(f"repos/{run.repo}/issues/{n}/events", run.github), bought, run.clock())
             if not h.lapsed]
    if holds:
        parts[-1] += " It is assigned to " + ", ".join(f"@{h.login}" + (f" until {who.when(h.until)}" if h.until else "")
                                                       for h in holds[:4]) + ": only their pull request is paid for it."
    elif bought:
        parts[-1] += " Nobody holds it."
    if more > 0:
        parts.append(f"{more} more job{'s' if more > 1 else ''} on this issue {'are' if more > 1 else 'is'} not listed: the smallest, "
                     "each funded straight from a wallet.")
    return _join(parts)


def _unseen(blind: list[int], number: int, how: str = "comment `/knos settle`") -> list[str]:
    """What to say about the numbers the chain did not answer for, and how it is tried again."""
    if not blind:
        return []
    named = ", ".join(f"issue #{n}" for n in blind if n != number) or "this pull request's tips"
    return [f"Solana could not be read for {named}, so whether anything is in escrow there is not known. {how[0].upper()}{how[1:]} "
            "to try again."]


def _nothing(run: Run, pull: dict, closes: list[int], listed: list | None, held: list, tips_only: bool, merged: bool) -> str:
    """The answer when a pull request has no open job to take: what it closes, and what is already held."""
    if tips_only:
        return ("nothing to pay: no tip waits for this pull request on Solana. A tip sent a moment ago may not have arrived; "
                "comment `/knos settle` in a minute.")
    issues = ", ".join(f"#{n}" for n in closes)
    said = (f"no bounty is open on the issue{'s' if len(closes) > 1 else ''} this pull request closes ({issues})" if closes else
            "this pull request closes no issue (its description would say `Fixes #N`)" if listed is not None else
            "GitHub did not say which issues this pull request closes, and its description closes none")
    out = [f"{'nothing to pay' if merged else 'this pull request takes no bounty as it stands'}: {said}, and no tip waits for it."]
    for n, _address, j in held:
        who_ = f"@{pull['user']['login']}" if (pull.get("user") or {}).get("id") == j.payee_id else f"GitHub user id {j.payee_id}"
        out.append(f"The bounty on issue #{n} ({_sum(run, [(_address, j)])}) is already held for {who_} until "
                   f"{who.when(j.hold_until)}: it is paid when they bind a wallet ({BIND}).")
    return " ".join(out)


# ---- knos settle -----------------------------------------------------------------------------------------------------

# ---- the five states of a payment, and the one comment that carries them --------------------------------------------------
# received    the event (the merge, the comment, the judge's success) reached this command: the job's own clock at its start
# accepted    every case that is paid was checked against the pull request's last commit and passed, and GitHub signed the
#             token for this run. Written BEFORE the token goes anywhere: no chain wait stands between a merge and this word
# submitted   the relay handed the first transaction to the cluster (its `sent_at`: this job's clock when it relays its own
#             token, the public worker's from its log line otherwise)
# confirmed   the paying transaction confirmed (the relay's `confirmed_at`; a token another relayer carried first has no
#             such time, and then it is when this job learned of it)
# finalized   the cluster finalized that transaction, asked for at most FINAL_WAIT seconds
# ONE comment: posted at `received`, then edited in place as each state is reached, and ending as the comment a
# settlement always wrote (paid, held, refused, with the transaction). A new comment per state would be five of GitHub's
# content-creating requests for one payment; an edit is none of the pull request's readers' notifications.
STATES = ("received", "accepted", "submitted", "confirmed", "finalized")
STATUS = "<!-- knos-status -->"         # everything after this line of the comment is the states: people read one line, programs another
FINAL_WAIT = 40                         # seconds the job waits for the cluster to finalize a payment it has already reported


def _hms(t: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(t))


class _Status:
    """The one comment of a settlement on a pull request, and the time each of the five states was reached.

        reach(state, at=None)      note the time (once: the first time counts)
        write(text)                the comment says `text`, with the states under it: posted the first time, edited after

    A comment GitHub would not take, or would not let be edited, is not an error here: `write` answers False and the
    caller says its last words the way it always did (`Run.say`)."""

    def __init__(self, run: Run, number: int, since: float, after: str) -> None:
        self.run, self.number, self.since, self.after = run, int(number), since, after
        self.at: dict[str, float] = {}
        self.id: int | None = None
        self.lines: list[str] = []      # the relay's own log lines for this pull request's tokens, when this job relayed them
        self.sig = ""                   # the paying transaction, once there is one
        self.writes, self.text = 0, ""  # how often the comment was written, and its words now

    def reach(self, state: str, at: float | None = None) -> None:
        if state in STATES and state not in self.at:
            self.at[state] = float(self.run.clock() if at is None else at)

    def block(self) -> str:
        """The states under the comment's words: one line a person reads (each state reached, its time and the seconds
        since `after`), one a program reads (`knos-states`, Unix seconds), and the relay's log lines."""
        said = " · ".join(f"{s} {_hms(self.at[s])} UTC (+{max(0, round(self.at[s] - self.since))} s)" for s in STATES if s in self.at)
        data = " ".join([f"since={self.since:.1f}", *(f"{s}={self.at[s]:.1f}" for s in STATES if s in self.at), *([f"tx={self.sig}"] if self.sig else [])])
        lines = "".join(f"\n{ln.replace('--', '- -')}" for ln in self.lines[:4])
        return f"{STATUS}\n<sub>{said}; seconds are counted from {self.after}.</sub>\n<!-- knos-states {data}{lines}\n-->"

    def write(self, text: str) -> bool:
        body = f"{text}\n\n{self.block()}"
        try:
            if self.id is None:
                self.id = int(self.run.github(f"repos/{self.run.repo}/issues/{self.number}/comments", {"body": body})["id"])
            else:
                self.run.github(f"repos/{self.run.repo}/issues/comments/{self.id}", {"body": body}, "PATCH")
        except Exception:  # noqa: BLE001 - a read-only token, or GitHub did not answer: the caller falls back to `say`
            return False
        self.writes, self.text = self.writes + 1, text
        return True


def _status_of(run: Run) -> _Status | None:
    return getattr(run, "_status", None)


def _provisional(run: Run, c: "Case", jwt: str) -> tuple[str, Any]:
    """The provisional decision on a token this job is about to send (knos.decide), as one line for the status comment,
    and what asks the chain about it afterwards. It never says paid.

    Two halves since 0.3.19. OFFLINE first, with no network: the issuer's signature against the key lists kept on this
    machine, the token's claims and the terms that travel with it (`decide.offline`). When that decides, its line is
    the one posted at once, and the second value is a function that makes ONE chain request with a timeout
    (`decide.chain_check`) and gives the updated line, or "" when the chain did not answer or changed nothing. Where no
    key list is kept for the token's issuer (a runner that never ran `knos decide --refresh-keys`), the offline half
    cannot decide, and the line is the relay's whole precheck as before (`decide.token`: what `knos decide --full`
    runs); nothing is asked afterwards then.

    ("", None) when there is no token, when the relay this run uses has no `precheck` to ask, or when anything at all
    goes wrong: the decision is a convenience for the reader, and its failure is logged and never stands in a
    payment's way."""
    if not jwt or not callable(getattr(run.relay, "precheck", None)):
        return "", None
    try:
        from . import decide
        beside, at = c.raw or None, int(run.clock())
        first = decide.offline(jwt, beside, now=run.clock())
        if first["decision"] == "insufficient_evidence":        # no kept key list decides it: the relay's own reads, as before
            doc = decide.provisional(decide.token(jwt, beside, ledger=run.ledger, now=run.clock()), at=at, jwt=jwt, terms=beside)
            run.output("provisional", decide.digest(doc))
            return decide.comment_line(doc), None
        doc = decide.provisional(first, at=at, jwt=jwt, terms=beside)
        run.output("provisional", decide.digest(doc))

        def asked() -> str:
            try:
                seen = decide.chain_check(jwt, ledger=run.ledger)
                if not seen.get("read"):
                    return ""
                after = decide.provisional(decide.after_chain(first, seen, jwt), at=int(run.clock()), jwt=jwt, terms=beside, updates=decide.digest(doc))
                run.output("provisional", decide.digest(after))
                return decide.comment_line(after)
            except Exception as why:  # noqa: BLE001 - best effort
                _err(f"knos: the chain check of the provisional decision could not be made ({type(why).__name__}: {_short(why)}); settling goes on")
                return ""
        return decide.comment_line(doc), asked
    except Exception as why:  # noqa: BLE001 - best effort
        _err(f"knos: the provisional decision could not be made ({type(why).__name__}: {_short(why)}); settling goes on")
        return "", None


def _accepted(run: Run, c: "Case", jwt: str = "") -> None:
    """A case passed and GitHub signed for it: the comment says so now, before the token goes to the chain, with the
    provisional decision on that token (`_provisional`) when one could be made: the offline line at once, then the
    chain check's in its place when the chain answered."""
    st = _status_of(run)
    if st is None or "accepted" in st.at:
        return
    st.reach("accepted")
    decided, asked = _provisional(run, c, jwt)
    words = (f"Knos: accepted, settling. Everything {_what(run, c)} asks for holds at this pull request's last commit and GitHub signed "
             f"this run. The payment to @{c.paid.get('login')} is on its way to Solana; this comment is edited when it lands.")
    st.write(words + (f" {decided}" if decided else ""))
    later = asked() if asked is not None else ""
    if later and later != decided:
        st.write(f"{words} {later}")


def _settled(run: Run, cases: list) -> None:
    """After the relay: when the first transaction was sent and when the payment confirmed, from the relay's own times."""
    st = _status_of(run)
    done = [c.result for c in cases if c.result is not None]
    if st is None or not done:
        return
    sent = [float(r["times"]["sent_at"]) for r in done if (r.get("times") or {}).get("sent_at") is not None]
    if sent:        # (the public worker's clock is not this job's: a state is never shown before the one it follows)
        st.reach("submitted", max(min(sent), st.at.get("accepted", 0.0)))
    paid = [r for r in done if r.get("ok") and not r.get("quorum")]
    if paid:
        ends = [float(r["times"]["confirmed_at"]) for r in paid if (r.get("times") or {}).get("confirmed_at") is not None]
        st.reach("confirmed", max(max(ends) if len(ends) == len(paid) else run.clock(), st.at.get("submitted", 0.0)))
        st.sig = next((str(r["sigs"][-1]) for r in reversed(paid) if r.get("sigs")), "")
    st.lines = [str(r["line"]) for r in done if r.get("line")]


def _finalized(run: Run, sig: str) -> bool:
    """Whether the cluster finalized `sig` within FINAL_WAIT seconds. A ledger with no way to ask says nothing."""
    try:
        ask = getattr(run.ledger, "finalized", None)
        if ask is not None:
            return bool(ask(sig, FINAL_WAIT))
        url = getattr(run.ledger, "url", None)
        if not url:
            return False
        from . import chain
        chain.wait(str(url), sig, float(FINAL_WAIT), "finalized")
        return True
    except Exception:  # noqa: BLE001 - not finalized in time, or the cluster did not answer: the state stays unreached
        return False


def settle(run: Run, tests: bool = False, pull: int | None = None, head: str = "", issue: int | None = None) -> int:
    """`knos settle`: pay what merged pull requests earned. A push to the default branch settles every pull request it
    merged, and says nothing about one with nothing in escrow. A `/knos settle` comment and a workflow_dispatch with
    a pull request's number settle that one and always answer; a `/knos tip` comment pays the tip `knos command`
    has just funded. With `tests` (`--tests --pull N --head SHA`) it is the job that signs after the sandboxed
    judge passed: see `_attest`. Returns the job's exit status: 1 when something could not be read, signed or
    relayed (the comment says how it is tried again)."""
    if not tests and _attestor(run):
        return _attestor_settle(run)
    ev, rp = run.event, _repo(run)
    if rp is None:
        run.note("Knos settle: GitHub did not answer for this repository, so nothing was looked at. `/knos settle` on a merged "
                 "pull request tries its payment again.")
        return 1
    if tests:
        return _attest(run, rp, pull, head, issue)
    asked, tips_only, after, since = True, False, "this run began", run.began
    merged: dict | None
    if "comment" in ev:
        on, said = ev.get("issue") or {}, ev.get("comment") or {}
        cmd = commands.parse(said.get("body") or "", True) if "pull_request" in on and ev.get("action") == "created" else None
        if not isinstance(cmd, (commands.Settle, commands.Tip)):
            run.note("Knos settle: this comment asks for no payment.")
            return 0
        numbers, tips_only, after = [on.get("number")], isinstance(cmd, commands.Tip), "the comment"
        asked = not tips_only      # `knos command` has answered a tip already: with nothing to pay there is nothing to add
        since = who._ts(said.get("created_at")) or run.began
    elif "after" in ev and "ref" in ev:
        pulls, whole = _merged_by(run, rp)
        if not whole:
            run.failed = True
            run.note("Knos settle: GitHub did not answer for every commit of this push, so a pull request it merged may have been "
                     "missed. `/knos settle` on a merged pull request tries its payment again.")
        if not pulls:
            run.note("Knos settle: this push merged no pull request into the default branch.")
        for merged in pulls:
            _settle_safely(run, rp, merged, who._ts(merged.get("merged_at")) or run.began, "the merge", False, False)
        return 1 if run.failed else 0
    else:
        numbers = [_named(ev)]
    for n in numbers:
        merged = _pull(run, n) if n else None
        if merged is None:
            run.failed = True
            run.note(f"Knos settle: GitHub did not answer for pull request #{n}." if n else
                     "Knos settle: this run names no pull request (the workflow_dispatch input `pull`).")
        elif not merged.get("merged_at"):
            run.note(f"Knos settle: pull request #{n} is not merged. Its payment is tried once it is.")
        else:
            _settle_safely(run, rp, merged, since, after, asked, tips_only)
    return 1 if run.failed else 0


def _attest(run: Run, rp: dict, number: int | None, head: str, issue: int | None) -> int:
    """`knos settle --tests --pull N --head SHA [--issue I]`: the job that signs for a bounty paid by its acceptance
    checks. The workflow starts it only after the sandboxed judge passed for that pull request at that commit, in
    a job that holds no token; this job runs no pull request code. It trusts nothing the judge job said beyond its
    success: the pull request, the jobs, their terms, GitHub's record of the commit, the payee and the address are
    all read again here. The head must still be the pull request's, and the acceptance checks on the default
    branch must be the ones the bounty was funded with. Then it signs with mode 1, relays, and comments."""
    found = _pull(run, number) if number else None
    if found is None:
        run.note(f"Knos settle: GitHub did not answer for pull request #{number}, so nothing was signed." if number else
                 "Knos settle: --tests needs the pull request the judge passed (--pull) and its head commit (--head).")
        return 1
    now = str((found.get("head") or {}).get("sha") or "")
    if not head or now != head:
        run.note(f"Knos settle: pull request #{number} is at commit `{now[:7]}` now, and its acceptance checks passed at "
                 f"`{str(head)[:7] or 'no commit'}`, so nothing was signed. They run again for the new commit.")
        return 0
    if found.get("state") != "open" and not found.get("merged_at"):
        run.note(f"Knos settle: pull request #{number} was closed without being merged, so nothing was signed.")
        return 0
    handed = str(run.env.get("VERDICT") or "")
    if handed.strip():      # the judge job's verdict, when the workflow hands it to this step too: the bundle is read at the commit it names
        from . import verdict_gate
        try:
            v = verdict_gate.read(handed)
            verdict_gate.holds(v, verdict_gate.expected(run.env, str(number), head, str(issue or 0)))
        except verdict_gate.Refused as why:
            run.note(f"Knos settle: nothing was signed. {str(why)[0].upper()}{str(why)[1:]}.")
            return 1
        run.judged_at = v["base"]
    _settle_safely(run, rp, found, run.began, "its acceptance checks passed", False, False, int(issue or 0))
    return 1 if run.failed else 0


def _named(ev: dict) -> int | None:
    """The pull request a workflow_dispatch names: its input `pull` (also read: pull_request, number, pr)."""
    inputs: dict = ev["inputs"] if isinstance(ev.get("inputs"), dict) else {}
    for key in ("pull", "pull_request", "number", "pr"):
        if str(inputs.get(key) or "").strip().lstrip("#").isdigit():
            return int(str(inputs[key]).strip().lstrip("#"))
    return None


def _merged_by(run: Run, rp: dict) -> tuple[list[dict], bool]:
    """The pull requests a push to the default branch merged, lowest number first, and whether GitHub answered for
    every pushed commit. GitHub names the pull request that brought each commit in; one counts when it is merged,
    its base is the default branch and its merge commit is among the pushed ones. That holds for a merge commit, a
    squash (the one new commit is the merge) and a rebase (the last rebased commit is)."""
    ev = run.event
    shas = [s for s in dict.fromkeys([*(c.get("id") for c in ev.get("commits") or [] if isinstance(c, dict)), ev.get("after")])
            if isinstance(s, str) and re.fullmatch(r"[0-9a-f]{40}", s) and s.strip("0")]
    if ev.get("ref") != f"refs/heads/{rp['branch']}" or ev.get("deleted") or not shas:
        return [], True
    numbers: set[int]
    numbers, whole = set(), True
    if len(shas) > MAX_COMMITS:
        run.note(f"Knos settle: this push has {len(shas)} commits; the newest {MAX_COMMITS} were looked at. `/knos settle` on a "
                 "merged pull request settles it whatever the push.")
    for sha in reversed(shas[-MAX_COMMITS:]):       # the newest first: the head commit is the merge
        got = _brought_in(run, sha, patient=sha == ev.get("after"))
        if got is None:
            whole = False
            continue
        numbers.update(int(p["number"]) for p in got if isinstance(p, dict) and str(p.get("number") or "").isdigit())
    pulls = []
    for n in sorted(numbers):
        p = _pull(run, n)
        if p is None:
            whole = False
        elif p.get("merged_at") and (p.get("base") or {}).get("ref") == rp["branch"] and p.get("merge_commit_sha") in shas \
                and str(((p.get("base") or {}).get("repo") or {}).get("full_name") or run.repo).lower() == run.repo.lower():
            pulls.append(p)
    return pulls, whole


def _brought_in(run: Run, sha: str, patient: bool) -> list | None:
    """GET /repos/{repo}/commits/{sha}/pulls: the pull requests GitHub ties to a commit. Right after a merge the
    answer can be empty for a moment, so the head commit (`patient`) is asked again, briefly. None: no answer."""
    got = None
    for pause in (2, 4, None) if patient else (None,):
        try:
            got = run.github(f"repos/{run.repo}/commits/{sha}/pulls?per_page=100")
        except Exception:  # noqa: BLE001
            got = None
        if got or pause is None:
            break
        run.sleep(pause)
    return got if isinstance(got, list) else None


def _settle_safely(run: Run, rp: dict, pull: dict, since: float, after: str, asked: bool, tips_only: bool,
                   tests: int | None = None) -> None:
    """One pull request, and whatever goes wrong with it is said, never dropped: on the pull request when someone
    asked or a token had already left, else on the run's page."""
    sent = run.relayed
    try:
        _settle_one(run, rp, pull, since, after, asked, tips_only, tests)
    except Exception as why:  # noqa: BLE001
        run.failed = True
        text = (f"Knos: this pull request's payment stopped before it was finished ({type(why).__name__}: {_short(why)}). "
                + (f"To try again, {_again(run)}." if run.att is not None else
                   "`/knos status` shows what is in escrow" + ("." if tests is not None else "; comment `/knos settle` to try again.")))
        if asked or run.relayed != sent or _status_of(run) is not None:      # (a comment that said "received" says how it ended)
            run.say(pull["number"], text)
        else:
            run.note(f"#{pull['number']}: {text}")
    finally:
        setattr(run, "_status", None)       # the comment is this pull request's settlement's, and that is over


def _judged(cases: list[Case], issue: int = 0) -> list[Case]:
    """The cases the sandboxed judge decides: the bounties paid by acceptance checks on one issue (`issue`; else the
    first issue the pull request closes that has one, which is the one `knos review` names for the judge)."""
    found = [c for c in cases if not c.tip and c.jobs[0][1].mode == pay.TESTS and issue in (0, c.issue)]
    return [c for c in found if c.issue == found[0].issue]


def _settle_one(run: Run, rp: dict, pull: dict, since: float, after: str, asked: bool, tips_only: bool, tests: int | None) -> None:
    """One pull request where money moves: decide, sign and relay a token for each case where everything holds, and
    write the one comment. `asked`: a person asked, so there is an answer even when nothing is in escrow. `tests`
    (not None): the sandboxed judge passed for it, and only the bounty it judged (issue `tests`, 0: the first) is
    this job's to sign; None: the pull request is merged, and what the merge pays is."""
    number, by_tests = int(pull["number"]), tests is not None
    cases, closes, listed, blind, held = _find(run, rp, pull, tips_only)
    if tests is not None:
        cases = _judged(cases, tests)
        blind = [n for n in blind if n != number and tests in (0, n)]
    st = None
    if run.att is None and (cases or asked):     # (an attestor's token for a repository it reads posts comments there and edits none)
        st = _Status(run, number, since, after)
        st.reach("received", run.began)
        if not st.write(f"Knos: received. Pull request #{number} is being checked against what was funded for it. This comment is "
                        "edited as the payment moves."):
            st = None
    setattr(run, "_status", st)
    runs, statuses = _decide(run, rp, pull, cases, listed, by_tests)
    for c in cases:
        if c.verdict() == "yes":
            try:
                _prove(run, rp, pull, c, since)
            except Exception as why:  # noqa: BLE001 - one job's trouble is its own: the others are still paid
                c.unread.append(f"its signed token could not be made ({type(why).__name__}: {_short(why)})")
    if any(c.verdict() == "unread" or (c.result is not None and not c.result.get("ok")) for c in cases):
        run.failed = True
    parts = [_after(run, c, pull, after, by_tests) for c in cases] + ([] if by_tests else _left_out(run, number))
    if blind and (asked or closes or parts or tips_only):     # a push says nothing about a pull request that closes no issue
        run.failed = True
        parts += _unseen(blind, number, _again(run, by_tests))
    if not parts:
        if not asked:
            unlisted = listed is None and not closes     # GitHub did not say what it closes: not known, which is not "nothing"
            run.failed = run.failed or (unlisted and not tips_only)
            run.note(f"Knos settle: no bounty paid by acceptance checks is open for an issue pull request #{number} closes, so "
                     "there was nothing to sign." if by_tests else
                     f"Knos settle: no tip waits for pull request #{number} on Solana, so there is nothing to pay." if tips_only else
                     f"Knos settle: GitHub did not say which issues pull request #{number} closes. If one of them has a bounty, "
                     "`/knos settle` on the pull request pays it." if unlisted else
                     f"Knos settle: Solana could not be read for pull request #{number}, which closes no issue. `/knos settle` on it "
                     "pays a tip that waits for it." if blind else
                     f"Knos settle: nothing is in escrow for pull request #{number}, so there is nothing to pay.")
            return
        parts = [_nothing(run, pull, closes, listed, held, tips_only, True)]
    _settled(run, cases)
    before = st.writes if st is not None else 0
    run.say(number, badge.said(run.repo, number, _join(parts), run.now()))       # into the one comment, when it is there (Run.say)
    if st is not None and st.sig and st.writes > before and _finalized(run, st.sig):     # the payment is said already: this adds the last state to the same comment
        st.reach("finalized")
        st.write(st.text)
    setattr(run, "_status", None)
    if cases and run.att is None:       # paid or refused: what this settlement showed goes to the judge's memory, for the next funding
        _learn(run, pull, cases, runs, statuses)        # (an attestor writes nothing in a repository it reads but its replies)


def _decide(run: Run, rp: dict, pull: dict, cases: list[Case], listed: list | None, tests: bool = False) -> tuple:
    """The rules money moves on, in one place for `knos settle` and `knos attest`: GitHub's record of the pull
    request's last commit against each case's terms (a required check that has not finished is waited for), who is
    paid and where, then the repository's policy, a split, and the sanctions list. Afterwards `c.verdict()` is "yes"
    only for a case a token may be signed for. Returns GitHub's record of that commit: (check runs, statuses)."""
    runs, statuses = _record(run, (pull.get("head") or {}).get("sha") or "", cases, CHECKS_WAIT)
    _judge(run, pull, cases, listed, True, runs, statuses, tests=tests)
    _cleared(run, rp, pull, cases)
    return runs, statuses


def _order_audience(pull: dict, c: Case, address: str | None, salt: bytes | None = None) -> str:
    """What GitHub is asked to sign to pay a work order: the order, the commit, the terms, the pull request, the payees.
    An order funded `auto`, for a pull request that is still open: the same under `knos3:auto`, for its one author.
    A PRIVATE order (`salt`): the audience is public, so the pull request is named by `hidden_pull`, never by its
    number. THE HEAD COMMIT'S ID IS IN IT, as the chain's format has it: 40 hex characters that say nothing to anyone
    who cannot read the repository, and that let anyone who can check which commit was accepted."""
    order, o = c.jobs[0]
    c.payees = c.payees or [(int(c.paid["id"]), 10_000, address, c.paid.get("login"), c.where.get("address"))]
    number = int(pull["number"]) if salt is None else hidden_pull(salt, int(pull["number"]))
    head = (pull.get("head") or {}).get("sha") or ""
    if salt is None and _auto(c, pull) and len(c.payees) == 1:      # judge e: paid on the black-box suite alone, under its own word
        return order_auto.auto_audience(order, head, bytes(o.terms), number, c.payees[0][0], c.payees[0][2])
    return pay.order_pay_audience(order, head, bytes(o.terms), o.mode, number, [x[:3] for x in c.payees])


def _auto(c: Case, pull: dict) -> bool:
    """Whether this case is an order funded `auto` meeting an open pull request: the one its funder said is paid as soon
    as the pinned black-box suite passes, with no merge, to its author (an agent's account too). Merged, it is paid
    as any other order is."""
    o = c.jobs[0][1]
    return bool(c.order and o.flags & order_auto.F_AUTO and o.mode == pay.TESTS and not pull.get("merged_at"))


def _prove(run: Run, rp: dict, pull: dict, c: Case, since: float) -> None:
    """Everything a case asks for holds: have GitHub sign the token and carry it to the chain. The token names the
    payee's own address only when no wallet is bound (a bound wallet is where the chain pays whatever is named)."""
    address = c.where.get("address") if c.where.get("from") == "comment" else None
    job, head = c.jobs[0][1], (pull.get("head") or {}).get("sha") or ""
    kept = run._hidden.get(str(c.jobs[0][0]))
    if c.order:
        aud = _order_audience(pull, c, address, kept[0] if kept else None)
    else:
        aud = pay.pay_audience(rp["id"], c.issue, int(c.paid["id"]), head, bytes(job.terms), job.mode, address)
    try:
        jwt = run.mint(aud)
    except Exception as why:  # noqa: BLE001
        c.unread.append(f"GitHub did not sign the token ({_short(why)})")
        return
    pin = _pin(jwt)
    if pin and not any(bytes(j.wf_repo_hash) == pin[0] and j.wf_sha == pin[1] for _a, j in c.jobs):
        c.why.append(f"it was funded through Knos's workflows at commit `{job.wf_sha[:7]}`, and only a run at that commit is accepted for it; this "
                     f"run used `{pin[1][:7]}`")
        c.fix.append(f"Point this repository's workflow file at commit `{job.wf_sha}` of Knos's workflows again.")
        return
    if not _terms3_signer(run, c, jwt, pull):       # an order funded under Knos Terms 3: only an evaluator its terms name signs for it
        return
    _accepted(run, c, jwt)
    c.result = _carried(run, "proof", jwt, since) if run.att is not None else deliver("proof", jwt, int(pull["number"]), run=run, since=since)


def _cleared(run: Run, rp: dict, pull: dict, cases: list[Case]) -> None:
    """What stands between a decision and a payout, for each case where everything else holds: the repository's
    policy (who may be paid at all, and which vendors by a standing offer; a policy that cannot be used pays
    nobody), for a work order the shares a maintainer named with `/knos split`, and the sanctions list for every
    address money would be sent to. A listed address is not paid: nothing is signed, the money stays in escrow and
    the comment says so. An address that could not be screened is paid, and the comment says "not screened"."""
    ready = [c for c in cases if c.verdict() == "yes"]
    if not ready:
        return
    rules, unusable = _policy(run, rp)
    for c in ready:
        try:
            if unusable:
                c.unread.append(unusable)
                continue
            if c.order:
                _shares(run, pull, c)
            people = c.payees or [(int(c.paid["id"]), 10_000, None, c.paid.get("login"), c.where.get("address"))]
            vendor = (c.terms or {}).get("vendor")
            for pid, _bps, _named, login, to in people:
                ok, why = policy.payee_allowed(rules, pid, login or "") if rules is not None else (True, "")
                if not ok:
                    c.why.append(_short(why).rstrip("."))
                if vendor and (pid != vendor or len(people) > 1):
                    c.why.append(f"this standing offer pays one vendor (GitHub user id {vendor}), and this pull request pays @{login}")
                elif vendor and rules is not None and rules.vendors is not None and not {str(pid), str(login or "").lower()} & set(rules.vendors):
                    c.why.append(f"`{policy.PATH}` lists the vendors a standing offer may pay ({', '.join(rules.vendors)}), and @{login} is not one of them")
                if to:
                    clear, said = run.screen(to)
                    if clear is False:
                        c.listed = _short(said)
                    elif clear is None:
                        c.said.append(f"`{to}` was {_short(said).rstrip('.')}.")
        except Exception as why:  # noqa: BLE001 - one case's trouble is its own
            c.unread.append(f"Knos stopped while clearing this payout ({type(why).__name__}: {_short(why)})")


def _shares(run: Run, pull: dict, c: Case) -> None:
    """The people a work order pays when a maintainer named them with `/knos split` before the merge: the last such
    comment that was not edited. Each needs a wallet (bound to their account, else their own `/knos address`
    comment on the pull request): the chain pays a split only whole."""
    number = int(pull["number"])
    comments = terms.pages(f"repos/{run.repo}/issues/{number}/comments", run.github)
    if comments is None:
        c.unread.append("the pull request's comments could not be read from GitHub")
        return
    permission, merged, split = who.permission_of(run.repo, run.github), who._ts(pull.get("merged_at")), None
    for said in comments:
        cmd = commands.parse(str(said.get("body") or ""), True) if isinstance(said, dict) else None
        if isinstance(cmd, commands.Split) and who.unedited(said) and (merged is None or (who._ts(said.get("created_at")) or merged + 1) <= merged) \
                and who.is_maintainer((said.get("user") or {}).get("login"), permission):
            split = cmd
    for login, percent in split.shares if split else ():
        user = _read(run, f"users/{login}")
        if not (isinstance(user, dict) and user.get("id")):
            c.unread.append(f"GitHub did not answer for @{login}, whom `/knos split` names")
            return
        bind = pay.read_bind(run.ledger.account(pay.bind_pda(int(user["id"]))))
        where = who.payout_address({"id": int(user["id"]), "login": user.get("login") or login}, comments, str(bind.wallet) if bind else None)
        if not where.get("address"):
            c.why.append(f"`/knos split` names @{login}, and no wallet is known for them: a split is paid only when every person has one")
            c.fix.append(f"@{login} binds a wallet ({BIND}).")
        c.payees.append((int(user["id"]), percent * 100, where.get("address") if where.get("from") == "comment" else None,
                         user.get("login") or login, where.get("address")))


# ---- the attestor: private work orders, funded and paid from one repository of the organisation -----------------------
# A company's private repositories run no Knos workflow, and a token minted in one would name it: GitHub's claims carry
# `repository`. So ONE repository of the organisation, its ATTESTOR, does both jobs for the repositories its policy
# lists as `targets`. It reads them through KNOS_READ_TOKEN, never checks them out, and applies the rules above: the
# functions are the same ones, handed a Run that reads the target (`Run.reads`).
#
#   funding     a `/knos fund ...` comment on an issue of a target. The attestor's `knos command` (by hand: inputs
#               `repository` and `issue`; or on its schedule: every target's comments of the last SCAN_DAYS days) answers
#               each such comment once. The order is PRIVATE: scope = sha256(salt || repository id || issue), a salt per
#               order; terms = sha256(salt || "knos3:terms" || terms JSON), so that a guess at the terms cannot be tried
#               against the chain; judge = the attestor repository; money from a Balance of the attestor repository's
#               owner that lists that repository and whoever started the run.
#   off chain   the salt and the terms JSON, in a comment on the private issue (RECORD), which only people with access
#               to that repository read. `_kept` holds the chain to it at settlement: an order the record does not
#               hash to is not this issue's.
#   in public   the two tokens, on the attestor repository's "knos tokens" issue, and this job's log: an amount, a
#               Balance, an order's address, hashes, the payees' GitHub ids and wallets, the attestor repository, and
#               the accepted commit's id. No repository, issue, pull request, branch, check or path of a target.
#   settlement  the attestor's `knos settle` (by hand: `repository` and `pull`; or on its schedule: every target's
#               pull requests merged in the last SCAN_DAYS days) pays what a merge earned (judge c), and replies on the
#               private pull request.

@dataclass
class _Att:
    """An attestor's run: the Run in the attestor repository, that repository as the chain keys it, its policy (the
    policy of every target), and who started the run: GitHub signs that id, and the Balance must list it."""
    run: Run
    rp: dict
    rules: object
    actor: dict
    issue: int | None = None        # a run by hand: the one issue, or the one pull request, it is for
    pull: int | None = None
    funded: int = 0
    _tokens: int | None = None

    def tokens(self) -> int:
        """The attestor repository's "knos tokens" issue, where its tokens are posted for a relayer."""
        if self._tokens is None:
            self._tokens = _tokens_issue(self.run.github, self.run.repo)
        return self._tokens


def hidden_terms(salt: bytes, raw: bytes) -> bytes:
    """What a PRIVATE order stores as its terms hash: sha256(salt || "knos3:terms" || the terms JSON). The chain takes
    any 32 bytes there and only ever compares them, so the salt can go in: terms are short and guessable (a check
    named `test`), and a plain hash would let anyone try a guess."""
    return hashlib.sha256(salt + b"knos3:terms" + raw).digest()


def hidden_pull(salt: bytes, number: int) -> int:
    """How a PRIVATE order's pay token names its pull request: a number made of the order's salt and the pull request's,
    the same every time (a standing order pays each pull request once), that does not say which it is. Six bytes of the
    hash, so below 2^48 (at most 15 digits): knos_pay's audience parser takes at most 18 digits (claims.rs parse_u64), and a
    receipt's JSON number holds only integers below 2^53 (docs/RECEIPT.md). Eight bytes made 19 orders in 20 unpayable."""
    return int.from_bytes(hashlib.sha256(salt + b"knos3:pull" + _u64(number)).digest()[:6], "little")


def _keep(said: dict, order, salt: bytes, raw: bytes, att: _Att) -> str:
    """The comment that keeps, on the private issue, what Solana does not keep of its order. It is written before
    anything is signed, and it also marks the funding comment as answered."""
    kept = json.dumps({"answers": int(said.get("id") or 0), "order": str(order), "salt": salt.hex(), "terms": base64.b64encode(raw).decode()},
                      separators=(",", ":"))
    return (f"<!-- knos-private-order {kept} -->\nKnos: this comment keeps what Solana does not keep of the private work order asked for above: "
            f"its salt and its terms. {att.run.repo} reads it when a pull request is merged, so do not edit or delete it. Whether the order "
            "was funded is in the next comment.")


def _kept(run: Run, rp: dict, n: int) -> list:
    """[(address, Order)] of the PRIVATE orders of issue `n` of a repository an attestor reads: for each record in the
    issue's comments (`_keep`), the order at the address it names, when the chain holds one and it hashes to the
    record: private, judged by this attestor, its scope this repository's and this issue's under the record's salt,
    its terms the record's. Anyone who can comment there can write such a record, and a record proves nothing: a
    forged one names an order that does not hash to it, and is passed over. Raises when the comments or the chain
    cannot be read: not knowing is not "there is none"."""
    comments = terms.pages(f"repos/{run.repo}/issues/{n}/comments", run.github)
    if comments is None:
        raise OSError("the issue's comments could not be read from GitHub")
    out = {}
    for said in comments:
        for found in RECORD.findall(str(said.get("body") or "") if isinstance(said, dict) else ""):
            try:
                rec = json.loads(found)
                address, salt, raw = Pubkey.from_string(str(rec["order"])), bytes.fromhex(str(rec["salt"])), base64.b64decode(str(rec["terms"]))
            except Exception:  # noqa: BLE001, S112 - not a record
                continue
            o = pay.read_order(run.ledger.account(address))
            if (o is None or o.state not in ("open", "held", "warranty") or not o.flags & pay.F_PRIVATE or o.judge_repo_id != run.att.rp["id"]
                    or len(salt) != 32 or bytes(o.scope) != pay.scope_of(rp["id"], n, salt) or bytes(o.terms) != hidden_terms(salt, raw)):
                continue
            run._hidden[str(address)] = (salt, raw)
            out[str(address)] = (address, o)
    return [out[a] for a in sorted(out)]


def _carried(run: Run, kind: str, jwt: str, since: float, beside: bytes | None = None) -> dict:
    """`deliver`, for a token an attestor minted for a repository it reads: relayed by the attestor's own key, or
    posted on the attestor repository's "knos tokens" issue. Never on the private repository: a relayer could not
    read it there, and the comment would not be public anyway. `beside`: a fund token's 128 hex characters."""
    att = run.att
    run.relayed += 1
    try:
        number = 0 if att.run.env.get("KNOS_RELAY_KEY") else att.tokens()
    except Exception as why:  # noqa: BLE001 - a job with no `issues: write` in its own repository, or GitHub did not answer
        return {"ok": False, "kind": "pay" if kind == "proof" else kind, "sigs": [], "note": "", "seconds": 0,
                "why": f"the token could not be posted for a relayer on the \"{TOKENS}\" issue of {att.run.repo} ({_short(why)}): its job needs `issues: write` there"}
    return deliver(kind, jwt, number, beside, run=att.run, since=since)


def _listed_for(run: Run, att: _Att, balance, faucet: bool, no: str, again: str) -> tuple:
    """A private order's money: the Balance `_balance` chose, when it is the faucet's or its side account lists the
    attestor repository among the repositories that may spend it; else (None, why). Without that list any repository
    of the owner could spend the Balance as an attestor does."""
    who_ = f"@{att.actor.get('login')} (GitHub id {att.actor.get('id')})"
    if balance is None:
        return None, no + (f"\nA private order is paid from a balance of {att.run.repo}'s owner that lists whoever started that repository's run as a "
                           f"spender: here {who_}.")
    if faucet:
        return balance, ""
    x = pay.read_balx(run.ledger.account(pay.balx_pda(balance)))
    if x is None or att.rp["id"] not in x.repos:
        return None, (f"Knos: nothing was funded. The balance `{balance}` does not list {att.run.repo} (repository id {att.rp['id']}) among the "
                      "repositories that may spend it, and a private order is paid only from a balance that does. The wallet that opened the "
                      f"balance lists it (knos_pay's SetBalanceX: `knos.settle.v2.pay.set_balance_x_ix` builds the instruction). Then {again}.")
    return balance, ""


def _attestor(run: Run) -> bool:
    """Whether this run is an attestor's. Said outright (`--attestor`), or by what started it, because the pinned
    workflows take no inputs: a schedule, a run by hand that names a `repository`, or a run by hand that names no pull
    request in a repository whose policy names it as the attestor."""
    ev = run.event
    inputs = ev.get("inputs") if isinstance(ev.get("inputs"), dict) else None
    if run.attestor or "schedule" in ev or (inputs is not None and str(inputs.get("repository") or "").strip()):
        return True
    if "comment" in ev or "issue" in ev or "after" in ev or "workflow_run" in ev or _named(ev):
        return False
    rp = _repo(run) if inputs is not None else None
    rules = _policy(run, rp)[0] if rp is not None else None
    return rules is not None and rules.attestor == run.repo.lower()


def _number(value) -> int | None:
    text = str(value or "").strip().lstrip("#")
    return int(text) if text.isdigit() and int(text) > 0 else None


def _att_open(run: Run) -> tuple:
    """(the attestor, the targets this run is for, "") when this repository may attest, by its own policy, for what
    the run names; (None, [], why not) otherwise. The reason never names a target: it goes to this job's log."""
    inputs: dict = run.event["inputs"] if isinstance(run.event.get("inputs"), dict) else {}
    only = (run.only or str(inputs.get("repository") or "")).strip()
    rp = _repo(run)
    if rp is None:
        return None, [], "GitHub did not answer for this repository. Run the workflow again."
    rules, unusable = _policy(run, rp)
    if unusable:
        return None, [], f"{unusable[0].upper()}{unusable[1:]}. Fix `{policy.PATH}` on the default branch, then run the workflow again."
    ok, why = policy.attests(rules, run.repo, only or None)
    if not ok:
        return None, [], why
    if not run.version():
        return None, [], "The escrow on this cluster does not hold work orders yet (knos_pay 2.1 is not live here), and a private order is one."
    if str(run.env.get("GITHUB_RUN_ATTEMPT") or "1") != "1":
        return None, [], "This is a re-run, and GitHub's signature counts only on a run's first attempt. Start the workflow again."
    if run._reader is None and not run.env.get("KNOS_READ_TOKEN"):
        return None, [], ("This job has no KNOS_READ_TOKEN: the secret that lets the attestor read the repositories its policy lists. Add it to this "
                          "repository's secrets and hand it to the called workflows by name, as examples/knos-attestor.yml does.")
    actor = {"id": int(run.env.get("GITHUB_ACTOR_ID") or 0), "login": str(run.env.get("GITHUB_ACTOR") or "")}
    targets = [only.lower()] if only else list(rules.targets)
    issue, pull = _number(inputs.get("issue")), _named(run.event)
    if (issue or pull) and len(targets) != 1:
        return None, [], "An `issue` or a `pull` is one repository's: name it as `repository` too."
    return _Att(run, rp, rules, actor, issue, pull), targets, ""


def _asked(run: Run, att: _Att) -> list:
    """[(issue, comment, command)]: the `/knos fund` comments on issues of one target that the attestor has not
    answered. By hand, those of the issue the run names; on a schedule, those written in the last SCAN_DAYS days. A
    comment that was edited commands nothing, as everywhere. An answer is a comment that carries the comment's id
    (ANSWER, or the order's record). Raises when GitHub does not answer."""
    since = run.clock() - SCAN_DAYS * 86_400
    if att.issue:
        numbers = [att.issue]
    else:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
        recent = terms.pages(f"repos/{run.repo}/issues/comments?since={stamp}&sort=created&direction=desc", run.github, cap=3)
        if recent is None:
            raise OSError("the repository's comments could not be read from GitHub")
        numbers = sorted({int(str(c.get("issue_url")).rsplit("/", 1)[-1]) for c in recent if isinstance(c, dict)
                          and "/knos" in str(c.get("body") or "").lower() and str(c.get("issue_url") or "").rsplit("/", 1)[-1].isdigit()})[:MAX_ASKED]
    out = []
    for n in numbers:
        on, comments = run.github(f"repos/{run.repo}/issues/{n}"), terms.pages(f"repos/{run.repo}/issues/{n}/comments", run.github)
        if not isinstance(on, dict) or comments is None:
            raise OSError("an issue could not be read from GitHub")
        if "pull_request" in on:
            continue
        bodies = [str(c.get("body") or "") for c in comments if isinstance(c, dict)]
        answered = {int(i) for b in bodies for found in ANSWERED.findall(b) for i in found if i}
        for said in comments:
            cmd = commands.parse(str(said.get("body") or ""), False) if isinstance(said, dict) and who.unedited(said) else None
            wanted = isinstance(cmd, commands.Fund) or (isinstance(cmd, commands.Error) and cmd.command == "fund")
            if wanted and said.get("id") not in answered and (att.issue or (who._ts(said.get("created_at")) or 0) >= since):
                out.append((on, said, cmd))
    return out[:MAX_ASKED]


def _attestor_command(run: Run) -> int:
    """`knos command` in an attestor: fund what the targets' `/knos fund` comments ask for, each answered once, on its
    own issue. What this job's log says is counts: it may be public, and the issues are not."""
    att, targets, why = _att_open(run)
    if att is None:
        run.note(f"Knos attestor: nothing was funded. {why}")
        return 1
    answered = lost = 0
    for repo in targets:
        try:
            view = run.reads(repo, att)
            asked = _asked(view, att)
        except Exception:  # noqa: BLE001 - which repository, and what GitHub said about it, stay out of this log
            lost += 1
            continue
        for on, said, cmd in asked:
            try:
                reply = cmd.reply if isinstance(cmd, commands.Error) else _fund(view, cmd, said, on, None, att)
            except Exception as stopped:  # noqa: BLE001 - whatever it was, the commenter is told
                view.failed = True
                reply = f"Knos: this stopped before it was finished ({type(stopped).__name__}: {_short(stopped)}). Post the comment again to retry."
            if reply and view.say(int(on["number"]), ANSWER.format(int(said.get("id") or 0)) + "\n" + reply):
                answered += 1
        lost += int(view.failed)
    run.note(f"Knos attestor: read {len(targets)} repositor{'y' if len(targets) == 1 else 'ies'}; answered {answered} funding comment"
             f"{'' if answered == 1 else 's'}, funded {att.funded} private order{'' if att.funded == 1 else 's'}."
             + (f" {lost} could not be read or written, or something in {'it' if lost == 1 else 'them'} could not be finished: the token in "
                "KNOS_READ_TOKEN reads each target's contents, checks and metadata, and reads and writes its issues and pull requests." if lost else ""))
    return 1 if lost or run.failed else 0


def _attestor_settle(run: Run) -> int:
    """`knos settle` in an attestor: for each target, the pull request the run names, or every pull request merged into
    its default branch in the last SCAN_DAYS days, is settled as a merge is anywhere (`_settle_one`), against the
    private orders the attestor funded (`_kept`). A pull request with nothing in escrow gets no comment from a
    schedule. This job's log gets counts."""
    att, targets, why = _att_open(run)
    if att is None:
        run.note(f"Knos attestor: nothing was looked at. {why}")
        return 1
    looked = signed = lost = 0
    for repo in targets:
        try:
            view = run.reads(repo, att)
            rp = _repo_known(view)
            if att.pull:
                pulls = [view.github(f"repos/{repo}/pulls/{att.pull}")]
            else:
                closed = view.github(f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100")
                pulls = [p for p in closed if isinstance(p, dict) and (who._ts(p.get("merged_at")) or 0) >= run.clock() - SCAN_DAYS * 86_400
                         and (p.get("base") or {}).get("ref") == rp["branch"]][:MAX_ASKED]
        except Exception:  # noqa: BLE001
            lost += 1
            continue
        for pull in sorted(pulls, key=lambda p: int(p["number"])):
            if not pull.get("merged_at"):
                continue
            looked += 1
            _settle_safely(view, rp, pull, who._ts(pull.get("merged_at")) or run.began, "the merge", bool(att.pull), False)
        signed += view.relayed
        lost += int(view.failed)
    run.note(f"Knos attestor: read {len(targets)} repositor{'y' if len(targets) == 1 else 'ies'}; looked at {looked} merged pull request"
             f"{'' if looked == 1 else 's'}, signed {signed} payment{'' if signed == 1 else 's'}."
             + (f" {lost} could not be read, or something in {'it' if lost == 1 else 'them'} was not paid that may be later: the replies are on "
                "the pull requests." if lost else ""))
    return 1 if lost or run.failed else 0


# ---- what settlements teach: Sibyl's memory, written after each one and read at funding -------------------------------

class _Kept:
    """Lessons in this process only, in a store's shape. A job that signs installs no memory engine, so there Sibyl's
    store cannot be opened; what such a job learned still reaches the knos-memory issue through this, and every run
    that has the engine loads it into Sibyl from there."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, dict]] = {}

    def put(self, category: str, name: str, body: dict) -> None:
        self._rows.setdefault(category, {})[name] = body

    def rows(self, category: str) -> list[tuple[str, dict]]:
        return list(self._rows.get(category, {}).items())

    def all(self, category: str) -> list[dict]:
        return [body for _name, body in self.rows(category)]


def _memory(run: Run):
    """The judge's memory of this repository (the knos-memory issue), loaded into Sibyl's local store, the same one
    `knos check` and `knos review` judge from. None when GitHub could not be read."""
    from .proof import history, memory
    try:
        store: Any = history.SibylStore.local(run.scratch() / "memory")
    except Exception:  # noqa: BLE001 - the engine is not installed in this job
        store = _Kept()
    return None if memory.pull(run.repo, store, run.github) is None else store


def _dirs(changed: list[str]) -> list[str]:
    """Where a change was made: each file's folder, two levels deep at most (`src/parser`); `.` for the root."""
    return sorted({"/".join(str(f).split("/")[:-1][:2]) or "." for f in changed})[:12]


def _learn(run: Run, pull: dict, cases: list[Case], runs, statuses) -> None:
    """After a settlement, paid or refused, one lesson in the memory the check keeps (category `settlement`): which
    checks failed at the merged commit and on which paths, whether the description claimed what a failed check
    contradicts, which of the terms' checks the change met, and whether it was paid; and for each work order it paid,
    how that order ended (category `order`: accepted first time, or fixed after an earlier pull request was refused,
    with the published template and the policy version it was funded with). Its failure never touches the
    settlement: it is a note on the run's page."""
    try:
        from . import judge
        from .proof import history, memory
        number, head = int(pull["number"]), str((pull.get("head") or {}).get("sha") or "")
        files = _changes(run, number)
        dirs = _dirs([str(f.get("filename")) for f in files or [] if isinstance(f, dict) and f.get("filename")])
        report = judge.claim_report(pull.get("body") or "", runs, True, statuses)
        failed = sorted(name for name, state in (report.get("checks") or {}).items() if state == "failed")
        body = {"repo": history.repo_key(run.repo), "pull": number, "paid": any(c.result is not None and c.result.get("ok") for c in cases),
                "failed": {name: dirs for name in failed[:12]}, "false": [_short(report.get("said"))] if report.get("state") == "false" else [],
                "met": sorted({str(name) for c in cases for name, state in c.checks.items() if state == "passed"})[:12], "paths": dirs,
                "at": int(run.clock())}
        orders = [c for c in cases if c.order and not c.tip]
        refused = {str(c.issue): sorted(str(name) for name, state in c.checks.items() if state in ("failed", "skipped", "absent"))[:12]
                   for c in orders if c.verdict() == "no"}
        if refused:         # which work orders this pull request did not take, and on which checks: a later one that is paid was "fixed"
            body["refused"] = refused
        store = _memory(run)
        if store is None:
            run.note("Knos: the judge's memory (the knos-memory issue) could not be read, so what this settlement showed was not kept.")
            return
        for c in orders:    # how each work order ended, by the published template and the policy version it was funded with (Sibyl)
            if c.result is not None and c.result.get("ok"):
                before = [b["refused"][str(c.issue)] for _name, b in store.rows("settlement")
                          if isinstance(b, dict) and b.get("repo") == body["repo"] and b.get("pull") != number
                          and isinstance(b.get("refused"), dict) and isinstance(b["refused"].get(str(c.issue)), list)]
                template, version = _published(c.raw)
                history.order_outcome(store, run.repo, c.issue, "fixed" if before else "accepted", template, version,
                                      policy=str((c.terms or {}).get("policy") or ""),
                                      failed=[str(name) for names in before for name in names if isinstance(name, str) and name][:12], seq=c.issue)
        # as a lesson read from the issue is loaded: a "not paid" never takes back a "paid" for the same pull request at
        # the same commit (a merge's settlement and the attestor's run can settle it at the same moment)
        history.import_lessons(store, [{"category": "settlement", "name": history._id("settlement", body["repo"], number, head), "body": body}])
        _learn_supplier(run, store, pull, orders)
        memory.push(run.repo, store, run.github, run.github, str(run.env.get("GITHUB_RUN_ID") or ""))
    except Exception as why:  # noqa: BLE001
        run.note(f"Knos: what this settlement showed could not be written to the knos-memory issue ({_short(why)}).")


def _learn_supplier(run: Run, store, pull: dict, orders: list[Case]) -> None:
    """What the supplier's own tools recall later (`knos preflight`, an appeal): each reason a work order refused this
    pull request, under the terms' hash and by its code in the refusal table, and an acceptance on the supplier's
    record when it was paid. Its failure is a note, and loses nothing else."""
    try:
        from .proof import history
        number, supplier = int(pull["number"]), str((pull.get("user") or {}).get("login") or "")
        for c in orders:
            thash = hashlib.sha256(c.raw).hexdigest() if c.raw else ""
            if c.result is not None and c.result.get("ok"):
                if supplier:
                    history.supplier_event(store, run.repo, supplier, number, "accepted", thash, run.clock())
            elif thash and c.verdict() == "no":
                for said in [str(p) for p in c.scope][:12]:
                    history.refused(store, run.repo, thash, number, ghwords.code_of_reason(said) or "terms.out-of-scope", "", supplier, run.clock())
                for state in sorted({s for s in c.checks.values() if s in ("failed", "skipped", "absent")}):
                    history.refused(store, run.repo, thash, number, f"terms.check-{state}", "", supplier, run.clock())
                for r in c.why[:12]:
                    history.refused(store, run.repo, thash, number, ghwords.code_of_reason(str(r)) or "unknown", "", supplier, run.clock())
    except Exception as why:  # noqa: BLE001
        run.note(f"Knos: what this settlement showed of the supplier could not be kept ({_short(why)}).")


def _published(raw: bytes | None = None):
    """With terms' bytes: (the published template they are, its version), or ("", 0) when they are no published
    template or this installation has no registry (knos.terms_registry). With none: {template: its newest version}."""
    try:
        from . import terms_registry
        if raw is None:
            return {name: row["version"] for name, row in terms_registry.latest(terms_registry.check()).items()}
        found = terms_registry.verify(bytes(raw).decode("ascii")) if raw else []
        return (found[-1]["name"], found[-1]["version"]) if found else ("", 0)
    except ValueError:      # no registry here, or one that is not what its index says: nothing is named from it
        return {} if raw is None else ("", 0)


def suggest_terms(repo: str, memory) -> dict:
    """What this repository's settlements so far suggest a funder ask for: {"checks": [names], "paths": [globs],
    "said": [the sentences that propose them]}. `memory` is the judge's store (Sibyl's, or anything with
    `rows(category)`), or the lesson rows themselves ({"category", "name", "body"}). A check is proposed when it
    failed at merged commits here, with where and how often; paths when every paid change stayed under the same one
    or two top folders. From an empty memory nothing is proposed."""
    from .proof import history
    rows = memory.rows("settlement") if hasattr(memory, "rows") else [(x.get("name"), x.get("body")) for x in memory or []
                                                                      if isinstance(x, dict) and x.get("category") == "settlement"]
    mine = [b for _name, b in rows if isinstance(b, dict) and b.get("repo") == history.repo_key(repo)]
    counts: dict[tuple[str, str], int] = {}
    for b in mine:
        for name, dirs in (b.get("failed") or {}).items():
            for d in dirs or ["."]:
                counts[(str(name), str(d))] = counts.get((str(name), str(d)), 0) + 1
    best: dict[str, tuple[str, int]] = {}
    for (name, d), n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        best.setdefault(name, (d, n))
    checks = sorted(best, key=lambda name: (-best[name][1], name))[:2]
    said = [f"In this repository, changes {'at the root' if best[name][0] == '.' else f'under `{_plain(best[name][0])}`'} failed `{_plain(name)}` "
            f"{best[name][1]} time{'s' if best[name][1] != 1 else ''}: add it? (`checks: {_plain(name)}` on the fund line.)" for name in checks]
    paid = [b for b in mine if b.get("paid")]
    tops = sorted({str(d).split("/")[0] for b in paid for d in b.get("paths") or []})
    paths = [f"{t}/**" for t in tops] if len(paid) >= 2 and 1 <= len(tops) <= 2 and "." not in tops else []
    if paths:
        said.append(f"The {len(paid)} changes paid here so far stayed under {' and '.join(f'`{p}`' for p in paths)}: keep this one there too? "
                    f"(`paths: {', '.join(paths)}` on the fund line.)")
    return {"checks": checks, "paths": paths, "said": said}


def _proposed(run: Run, asked, built) -> str:
    """The last paragraph of a funding reply: what the judge's memory proposes, for what the funder left unsaid
    (checks when they named none, paths when they named none), after one line on how the last work orders here ended
    and the published template that supports (knos.proof.history.terms_supported; nothing with no memory of one).
    Empty when memory proposes nothing or cannot be read."""
    if asked.checks is not None and asked.paths:
        return ""
    try:
        from .proof import history
        store = _memory(run)
        got = suggest_terms(run.repo, store) if store is not None else {"checks": [], "paths": [], "said": []}
        line = history.terms_supported(store, run.repo, versions=_published()) if store is not None else ""
    except Exception:  # noqa: BLE001 - a proposal, never a reason to fail a funding that is done
        return ""
    have = {str(c.get("name")) for c in built.terms.get("checks") or []}
    keep = [line + "."] if line else []     # how the last work orders here ended, and the published template that supports
    keep += [text for name, text in zip(got["checks"], got["said"]) if asked.checks is None and name not in have]
    keep += got["said"][len(got["checks"]):] if not asked.paths else []
    return ("\n\nFrom what Knos remembers of this repository: " + " ".join(keep)
            + " To change the terms, fund another issue with them: these are fixed.") if keep else ""


# ---- knos attest: the same decision, from anyone's repository --------------------------------------------------------

KINDS = ("pay", "take", "revert", "rule", "eval", "batch", "claim")
# kind eval (knos_meter): the one rule this command reaches a verdict by, named in every evaluation it signs by its hash (the policy)
EVAL_RULE = (b"knos attest eval 1: accepted when the buyer merged the pull request into a repository of its own, "
             b"rejected when the buyer closed it unmerged")
EVAL_POLICY = hashlib.sha256(EVAL_RULE).digest()


def _evaluation(text: str) -> tuple[bytes, int, int] | None:
    """`--order` of kind eval, `<work order>.<milestone>.<rate>`: (the work order's 32-byte id, the milestone, the
    rate), or None when it is not that."""
    m = re.fullmatch(r"([0-9a-f]{64})\.([0-9]{1,10})\.([0-9]{1,20})", str(text).strip())
    if not m or int(m.group(2)) >= 2 ** 32 or int(m.group(3)) >= 2 ** 64:
        return None
    return bytes.fromhex(m.group(1)), int(m.group(2)), int(m.group(3))


def _attest_eval(run: Run, order: str, pull: int | None, no) -> int:
    """`knos attest --kind eval`: one evaluation for knos_meter to count, run in a repository of the BUYER (the owner the
    run is in), of a pull request in a repository of that same owner. The verdict is GitHub's record of what the buyer
    did with it (EVAL_RULE, whose hash is the audience's policy): accepted when it was merged, rejected when it was
    closed unmerged; an open one is not evaluated yet. The seller is its author, the artifact its head commit:

        knosm:eval:<buyer>:<seller>:<work order>:<head>:<policy>:<milestone>:<verdict>:<rate>

    knos_meter counts it once per (buyer, work order, artifact, policy, milestone), from the run's first attempt, and
    only against credits the buyer opened for this workflow at this commit (OpenCredits pins drexthealpha/knos-workflows
    and its commit). Posted as `knos-eval:` for a relayer, like every token of this command."""
    got = _evaluation(order)
    if got is None:
        return no("An evaluation names its work order, milestone and rate: `--order` is `<work order>.<milestone>.<rate>`, the work order as "
                  "its 32-byte id in hex (64 characters), the milestone a number below 2^32, and the rate what the seller bills when it is "
                  "accepted, in the smallest units of what the two settle in.")
    work, milestone, rate = got
    if str(run.env.get("GITHUB_RUN_ATTEMPT") or "1") != "1":
        return no("This is a re-run, and knos_meter counts only a run's first attempt: start the workflow again.")
    buyer = str(run.env.get("GITHUB_REPOSITORY_OWNER_ID") or "")
    rp, pull_ = _repo(run), (_pull(run, pull) if pull else None)
    if rp is None or pull_ is None:
        return no(f"GitHub did not answer for pull request #{pull} of {run.repo}. Run the workflow again." if pull else "`--pull` is the pull request's number.")
    if not buyer.isdigit() or int(buyer) != rp["owner"]:
        return no(f"An evaluation is the buyer's own: the pull request must be in a repository of the owner this run is in (GitHub id "
                  f"{buyer or 'unknown'}), and {run.repo} belongs to GitHub id {rp['owner']}.")
    number, head = int(pull_["number"]), str((pull_.get("head") or {}).get("sha") or "")
    author = pull_.get("user") or {}
    if pull_.get("merged_at"):
        verdict = 1
    elif pull_.get("state") == "closed":
        verdict = 0
    else:
        return no(f"Pull request #{number} of {run.repo} is open: it is evaluated once it is merged (accepted) or closed unmerged (rejected).")
    if not re.fullmatch(r"[0-9a-f]{40}", head) or not int(author.get("id") or 0):
        return no(f"GitHub's record of pull request #{number} of {run.repo} names no head commit or no author. Run the workflow again.")
    from .settle.v2 import meter
    aud = meter.eval_audience(int(buyer), int(author["id"]), work, head, EVAL_POLICY, milestone, verdict, rate)
    said = (f"pull request #{number} of {run.repo} by @{author.get('login')} (commit `{head[:7]}`) was "
            + ("merged: accepted" if verdict else "closed unmerged: rejected") + f", for work order `{work.hex()[:12]}` milestone {milestone} at rate {rate}")
    try:        # the same evaluation as a ledger line with its verdict in words and its ids (knos.ledger, knos.ids): the output `evaluation`
        from . import ledger
        run.output("evaluation", ledger.Evaluation(int(buyer), int(author["id"]), work.hex(), head, EVAL_POLICY.hex(), milestone, bool(verdict), rate,
                                                   verdict="accepted" if verdict else "rejected", evaluator=_evaluator(run.env, "eval"),
                                                   run=str(run.env.get("GITHUB_RUN_ID") or "")).line())
    except ValueError as why:
        run.note(f"Knos attest: the evaluation's ledger line could not be written ({_short(why)}). The token says the same.")
    return _attest_sign(run, "eval", aud, said, "", number, None, no)


def _evaluator(env, kind: str) -> str:
    """Who judged, as a ledger line and an evaluation's id name it: `<judge>@<version>`, the version the workflow's commit."""
    from . import version
    return f"{kind}@{_plain(env.get('GITHUB_WORKFLOW_SHA') or version())}"


# ---- knos attest, re-executed: the acceptance suite run again in the attester's own repository ---------------------------
# GitHub signs WHICH workflow ran, not what it read. For an order paid by its acceptance checks (tests mode: a black-box
# bundle whose hash is in the terms) attest.yml therefore does not take anyone's word that the suite passed: its first
# job, which can ask for no token, fetches the two commits from the order's repository and runs the suite itself, and
# hands the job that signs one small JSON verdict. That job checks out nothing and runs none of that code; it reads the
# verdict as untrusted text (`_rerun_read`), holds it to the order, the pull request, the commit and the terms it reads
# again itself, and signs only then. An order paid on the merge has no suite to run: the verdict then says so.

RERUN_ENV = "KNOS_RERUN"                # the token job's: the verdict the re-execution job handed it (needs.rerun.outputs.verdict)
VERDICT = "knos-verdict: "              # the line the verdict travels in, in a comment on the "knos tokens" issue
NOT_RERUN = "this judge read the buyer repository's check results; it did not run them"
RERUN_MEANS = ("this judge fetched the two commits and ran the acceptance suite itself, in the repository the run was in; every other "
               "check the terms name was read from GitHub's record")
_HEX40, _HEX64 = r"[0-9a-f]{40}", r"[0-9a-f]{64}"
RERUN_VERDICTS = ("accepted", "rejected", "insufficient_evidence")       # what one run can say (knos.ids.VERDICTS; disputed is somebody's appeal, not a run's)
# the outcome in the words of the refusal table (its row `rerun.insufficient-evidence`), as the middle of a sentence
UNDECIDED = (lambda said: said[0].lower() + said[1:].rstrip("."))(ghwords.refusal("rerun.insufficient-evidence")[0])
UNDECIDED_MEANS = ("It will be run again: nothing is paid, nothing is recorded against the supplier and no evaluation is charged")
RECEIPT = "knos-receipt: "              # the line a receipt of a run that paid nothing travels in, under the verdict's
_RERUN_KEYS = {"v": int, "reexecuted": bool, "passed": bool, "sentence": str, "order": str, "repository": str, "pull": int, "issue": int,
               "head": str, "base": str, "accept": str, "assurance": str, "image": dict, "artifact": dict, "environment": dict,
               "reasons": list}
_ENVIRONMENT = ("GITHUB_REPOSITORY", "GITHUB_REPOSITORY_ID", "GITHUB_REPOSITORY_OWNER_ID", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA", "RUNNER_OS", "RUNNER_ARCH", "RUNNER_ENVIRONMENT", "ImageOS", "ImageVersion")


def _environment(env) -> dict:
    """Where a verdict was reached, as the runner itself says it: the repository and run, the machine's kind and image.
    It is the run's own word (the signed token says the repository and the hosted runner; nothing signs the rest)."""
    from . import version
    return {"knos": version(), **{k.lower(): _plain(env.get(k))[:120] for k in _ENVIRONMENT if env.get(k)}}


def _rerun_plan(run: Run, address, o, pull: dict, c: Case) -> dict | None:
    """What the re-execution job fetches and runs for a merged pull request of an order paid by its acceptance checks:
    {"order", "repository", "pull", "issue", "head" (the commit that was merged), "base" (the commit it was merged
    onto: the merge commit's first parent), "accept" (the bundle's hash, from the terms), "image" (the terms', or ""),
    "changed" (the paths the pull request changed, as GitHub lists its files: a rename under both its names)}.
    The judge is told those paths and not the difference of the two trees: when the default branch moved after the pull
    request left it, the first parent holds files the pull request never touched, and a tree difference would charge
    them to it (a workflow the buyer changed after it, say, read as a pull request that changes a protected path).
    None for an order paid on the merge: there is no suite to run. Raises OSError when GitHub does not name the base,
    or does not list the pull request's files whole."""
    if not c.terms or c.terms["mode"] != "tests" or o.mode != pay.TESTS:
        return None
    merge = str(pull.get("merge_commit_sha") or "")
    parents = (_read(run, f"repos/{run.repo}/commits/{merge}") or {}).get("parents") if merge else None
    base = str((parents[0] or {}).get("sha") if isinstance(parents, list) and parents and isinstance(parents[0], dict)
               else (pull.get("base") or {}).get("sha") or "")
    head = str((pull.get("head") or {}).get("sha") or "")
    if not re.fullmatch(_HEX40, base) or not re.fullmatch(_HEX40, head):
        raise OSError("GitHub did not name the commit the pull request was merged onto")
    files = _changes(run, int(pull["number"]))
    if files is None:
        raise OSError("GitHub did not list the files the pull request changed")
    changed = sorted({str(f.get(k)) for f in files if isinstance(f, dict) for k in ("filename", "previous_filename") if f.get(k)})
    return {"order": str(address), "repository": run.repo, "pull": int(pull["number"]), "issue": int(o.issue), "head": head, "base": base,
            "accept": str(c.terms["accept"]), "image": str(c.terms.get("image") or ""), "changed": changed}


def _rerun_verdict(plan: dict | None, env, judged: dict | None = None, why: str = "") -> dict:
    """The verdict of one neutral run, as it is written to verdict.json, handed to the job that signs and posted. With no
    `plan` (an order paid on the merge) nothing was run, and it says so. `judged`: knos.judge.judge's verdict."""
    if plan is None:
        return {"v": 1, "reexecuted": False, "sentence": NOT_RERUN, "environment": _environment(env)}
    ev = (judged or {}).get("evidence") or {}
    image = ev.get("image") if isinstance(ev.get("image"), dict) else {}
    reasons = [why] if why else [_short(r)[:200] for r in (judged or {}).get("reasons") or []][:6]
    passed = bool(judged and judged.get("passed") and not reasons)
    # the judge's verdict in one of the words, and its reason: a run that could not tell (it could not run, or the judge says so) is
    # insufficient evidence, never the supplier's failure. A judge that says no word (0.3.16's) adds neither field.
    word = "insufficient_evidence" if why else str((judged or {}).get("verdict") or "")
    said = {} if word not in RERUN_VERDICTS else {
        "verdict": word if passed == (word == "accepted") else "accepted" if passed else "rejected",
        "reason": re.sub(r"\s+", " ", str(why or (judged or {}).get("reason") or "; ".join(reasons))).strip()[:300]}
    return {"v": 1, "reexecuted": True, "passed": passed, "sentence": RERUN_MEANS, **said,
            **{k: plan[k] for k in ("order", "repository", "pull", "issue", "head", "base", "accept")},
            "assurance": str((judged or {}).get("assurance") or ""),
            "image": {"ref": str(image.get("ref") or ""), "digest": str(image.get("digest") or "")} if image else {},
            "artifact": {k: str(v) for k, v in (ev.get("artifact") or {}).items() if k in ("base", "pr")},
            "environment": _environment(env), "reasons": reasons}


def _rerun_read(text: str) -> dict | str:
    """The verdict the re-execution job handed over, read as what it is: text from a job that ran a stranger's code.
    First knos.verdict_gate.shape: what two readers could read differently (a key twice, a fraction, a character
    outside printable ASCII, something nested) is refused before anything is made of it. Then it is returned only when
    it is one small JSON object of exactly the fields `_rerun_verdict` writes, each of its type and shape; else one
    sentence saying what is wrong. Whether it is about THIS order is the caller's to check."""
    from . import verdict_gate
    gate = ""
    try:
        verdict_gate.shape(text)
    except verdict_gate.Refused as why:
        gate = f"the re-execution's verdict is not text every reader reads the same way: {why}"
    got = _rerun_fields(text)
    return got if isinstance(got, str) or not gate else gate


def _rerun_fields(text: str) -> dict | str:
    """`_rerun_read` after the gate: exactly the fields `_rerun_verdict` writes, each of its type and shape."""
    if len(text) > 8192:
        return "the re-execution's verdict is larger than a verdict is"
    try:
        v = json.loads(text)
    except ValueError:
        return "the re-execution's verdict is not JSON"
    if not isinstance(v, dict) or v.get("v") != 1 or not isinstance(v.get("reexecuted"), bool):
        return "the re-execution's verdict is not in a form this version reads"
    want = _RERUN_KEYS if v["reexecuted"] else {k: _RERUN_KEYS.get(k, dict) for k in ("v", "reexecuted", "sentence", "environment")}
    shapes = {"head": _HEX40, "base": _HEX40, "accept": _HEX64, "assurance": r"black-box|hermetic|in-process|", "repository": r"[\w.-]+/[\w.-]+",
              "order": r"[1-9A-HJ-NP-Za-km-z]{32,44}"}
    flat = lambda d, most: len(d) <= most and all(isinstance(k, str) and isinstance(x, str) and len(x) <= 200 for k, x in d.items())  # noqa: E731
    more = {k: v[k] for k in ("verdict", "reason") if k in v} if v["reexecuted"] else {}      # the judge's word and reason, when it gave them
    if more and (set(more) != {"verdict", "reason"} or more["verdict"] not in RERUN_VERDICTS or not isinstance(more["reason"], str) or len(more["reason"]) > 300
                 or v.get("passed") is not (more["verdict"] == "accepted")):
        return "the re-execution's verdict does not have the fields a verdict has"
    if set(v) - set(more) != set(want) or any(type(v[k]) is not t for k, t in want.items()) \
            or any(k in v and not re.fullmatch(shape, v[k]) for k, shape in shapes.items()) \
            or not flat(v["environment"], 16) or (v["reexecuted"] and not (
                flat(v["image"], 2) and flat(v["artifact"], 2) and len(v["reasons"]) <= 6 and all(isinstance(r, str) and len(r) <= 200 for r in v["reasons"]))):
        return "the re-execution's verdict does not have the fields a verdict has"
    return v


def _rerun_holds(v: dict, plan: dict) -> str:
    """Why a verdict that was re-executed does not carry this payment; "" when it does: it is about this order, this
    pull request and these two commits, on the bundle the terms were funded with, in the image they name, and it passed."""
    for k in ("order", "repository", "pull", "issue", "head", "base", "accept"):
        if v[k] != plan[k]:
            return f"the re-execution was of another {k} (`{_plain(v[k])}`) than this payment's (`{plan[k]}`)"
    if not v["passed"] and v.get("verdict") == "insufficient_evidence":
        return f"{UNDECIDED}: {_plain(v.get('reason') or '; '.join(v['reasons']))}. {UNDECIDED_MEANS}"
    if not v["passed"]:
        return ("the acceptance suite did not pass when it was run again here" + (": " + "; ".join(_plain(r) for r in v["reasons"]) if v["reasons"] else "")
                + ". Whatever the check results in the order's repository say, this judge signs only what it ran itself")
    if set(v["artifact"]) != {"base", "pr"}:
        return "the re-execution does not say which two trees it judged"
    if plan["image"]:
        if v["assurance"] != "hermetic" or v["image"].get("ref") != plan["image"] or v["image"].get("digest") != plan["image"].rsplit("@", 1)[-1]:
            return f"the terms name the image `{plan['image']}`, and the re-execution did not run the suite in it"
    elif v["assurance"] != "black-box":
        return "the re-execution did not run the pull request's code black-box"
    return ""


def _rerun_judge(plan: dict, folder: Path, env, judge_fn=None, sandbox: str = "require") -> dict:
    """Run the pinned acceptance suite on `folder`/base and `folder`/pr (plain files of the plan's two commits) and
    return the verdict. The bundle is the base's and must hash to what the terms were funded with; the image is the
    terms'. The pull request's code runs where the judge always runs it: the sandbox (required), or a container of the
    image. Nothing here holds a secret or can ask for a token."""
    from . import judge
    base, pr = Path(folder) / "base", Path(folder) / "pr"
    try:
        have = judge.checks_hash(base / ".knos" / "acceptance" / str(plan["issue"]))
    except (OSError, ValueError):
        have = ""
    if have != plan["accept"]:
        return _rerun_verdict(plan, env, why=f"the acceptance checks in .knos/acceptance/{plan['issue']}/ at the base commit are not the ones this order was funded with")
    try:
        text = (base / ".knos" / "proof.toml").read_text(encoding="utf-8")
    except OSError:
        text = None
    cfg = {**judge.proof_config(text), "issue": str(plan["issue"])}
    if plan["image"]:
        cfg["image"] = plan["image"]            # the image that was funded, whatever proof.toml says at this commit
    try:
        # the paths GitHub lists for the pull request (the plan's), never the difference of the two trees: see _rerun_plan
        changed = plan.get("changed")
        judged = (judge_fn or judge.judge)(base, pr, cfg, [str(n) for n in changed] if isinstance(changed, list) else None, sandbox=sandbox)
    except Exception as why:  # noqa: BLE001 - a judge that could not run is a suite that did not pass here
        return _rerun_verdict(plan, env, why=f"the judge could not run here ({type(why).__name__}: {_short(why)})"[:200])
    return _rerun_verdict(plan, env, judged)


def _rerun_job(run: Run, plan: dict | None, folder: str, judging: bool, judge_fn=None) -> int:
    """The re-execution job's two steps. `--plan DIR`: write DIR/plan.json and say what to fetch (outputs `rerun`, `base`,
    `head`); for an order with no suite to run, write the verdict that says so. `--judge DIR`: run the suite on
    DIR/base and DIR/pr as DIR/plan.json has it, write DIR/verdict.json, and end 1 unless it passed. Either way the
    verdict is the job's output `verdict`, one line of JSON."""
    where = Path(folder)
    where.mkdir(parents=True, exist_ok=True)
    if judging:
        try:
            plan = json.loads((where / "plan.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            plan = None
        if not isinstance(plan, dict):
            run.note("Knos attest: there is no plan to re-execute here: the step before this one writes it.")
            return 1
    v = _rerun_judge(plan, where, run.env, judge_fn) if judging and plan is not None else _rerun_verdict(plan, run.env) if plan is None else None
    if v is None:
        if plan is None:        # (with no plan there is a verdict, the one that says nothing was run)
            raise ValueError("there is no plan and no verdict")
        (where / "plan.json").write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
        for k in ("base", "head"):
            run.output(k, plan[k])
        run.output("rerun", "1")
        run.note(f"Knos attest: this order is paid by its acceptance checks, so they are run again here: `.knos/acceptance/{plan['issue']}/` as funded, on "
                 f"commit `{plan['head'][:7]}` of {plan['repository']} against `{plan['base'][:7]}`" + (f", in `{plan['image']}`." if plan["image"] else "."))
        return 0
    line = json.dumps(v, sort_keys=True, separators=(",", ":"))
    (where / "verdict.json").write_text(json.dumps(v, sort_keys=True, indent=1), encoding="utf-8")
    run.output("verdict", line)
    if not judging:
        run.output("rerun", "")
        run.note(f"Knos attest: nothing is re-executed for this order: {NOT_RERUN}.")
        return 0
    undecided = v.get("verdict") == "insufficient_evidence"
    run.note(f"Knos attest: the acceptance suite was run again here and {'passed' if v['passed'] else 'the run could not decide' if undecided else 'did not pass'} "
             f"({v['assurance'] or 'not run'}" + (f", image digest `{v['image'].get('digest')}`" if v["image"] else "") + ")."
             + "".join(f"\n- {_plain(r)}" for r in v["reasons"]) + _reason_said(v)
             + ("" if v["passed"] else "\n\nNothing is signed: the job that asks GitHub for the token does not start." + (f" {UNDECIDED_MEANS}." if undecided else "")))
    return 0 if v["passed"] else 1


def _reason_said(v: dict) -> str:
    """The judge's reason for a verdict, as a comment says it: the reason itself, then the refusal table's two sentences
    for it when the table has a row (knos.ghwords). Empty for a verdict whose judge gave no reason."""
    reason = str(v.get("reason") or "") if isinstance(v, dict) else ""
    if not reason:
        return ""
    code = ghwords.code_of_reason(reason) if v.get("verdict") != "accepted" else None
    return f"\n\nThe judge's reason: {_plain(reason)[:300]}." + (f" {ghwords.said(reason)}" if code else "")


def _unpaid(run: Run, word: str, about: dict, record: str) -> tuple[dict | None, str]:
    """What a run that paid nothing leaves: (a version 5 receipt with the verdict `word`, rejected or insufficient_evidence,
    which never authorises payment (knos.receipt.unpaid4, then build5 for its assurance level; the version 4 receipt
    itself should that step fail), the same evaluation as a ledger line that says that verdict).
    `about`: {"address", "order", "case", "pull"}. `record`: the run's own verdict line, whose sha256 the receipt names.
    Either is None or "" when the run does not know enough to write it: it is a record, never a condition."""
    from . import ids, ledger
    from . import receipt as rc
    address, o, c, pull = about["address"], about["order"], about["case"], about["pull"]
    head, number = str((pull.get("head") or {}).get("sha") or ""), int(pull["number"])
    kind = "repository" if str(run.env.get("GITHUB_REPOSITORY_ID") or "") == str(o.repo_id) else "neutral"
    milestone = number if o.flags & pay.F_STANDING else 0
    made, line = None, ""
    try:
        t = c.terms or {}
        states = {"passed": "passed", "failed": "failed"}
        payees = [{"github_id": int(pid), "bps": int(bps), "to": str(named or dest)} for pid, bps, named, _login, dest in c.payees]
        made = rc.unpaid4(cluster={"mainnet": "mainnet-beta"}.get(str(run.env.get("KNOS_CLUSTER") or "devnet"), str(run.env.get("KNOS_CLUSTER") or "devnet")),
                          program=str(pay.PAY_ID), order=str(address), scope=pay.scope_of(o.repo_id, o.issue).hex(), repository={"id": int(o.repo_id), "issue": int(o.issue)},
                          commit=head, pull_request=number, terms_hash=bytes(o.terms).hex(), mode="tests" if o.mode == pay.TESTS else "merge", judge_kind=kind,
                          judge_version=str(run.env.get("GITHUB_WORKFLOW_SHA") or ""), verdict=word,
                          checks=[{"name": str(name), "conclusion": states.get(state, "missing")} for name, state in c.checks.items()],
                          allowed_paths=sorted(set(t["paths"])) if c.terms else None, denied_paths=sorted(set(t["deny"])) if c.terms else None,
                          policy_version=t.get("v") if c.terms else None, mint=str(o.mint), decimals=int(o.decimals), of=int(o.rate if milestone else o.amount),
                          milestone=milestone, payees=payees if all(p["to"] not in ("", "None") for p in payees) else (),
                          record_sha256=hashlib.sha256(record.encode()).hexdigest())
        made = rc.build5(made, _declared(run, t))       # version 5 (0.3.19): the same receipt with its assurance level, computed from its evidence
    except Exception as why:  # noqa: BLE001
        run.note(f"Knos attest: no receipt was written for this run ({_short(why)}). Its verdict above stands as it is.")
    try:
        seller = int((pull.get("user") or {}).get("id") or 0)
        line = ledger.Evaluation(int(about["buyer"]), seller, ids.order_scope(str(address)), head, bytes(o.terms).hex(), milestone, False,
                                 int(o.rate if milestone else o.amount), verdict=word, evaluator=_evaluator(run.env, kind), run=str(run.env.get("GITHUB_RUN_ID") or "")).line()
    except Exception:  # noqa: BLE001, S110 - the ledger line is one more record of what the verdict already says
        pass
    return made, line


def _rerun_said(run: Run, v: dict | None, refused: str = "", about: dict | None = None, appealed: str = "") -> None:
    """Post a verdict where the token is posted: one comment on the "knos tokens" issue of the repository the run is in.
    `refused`: why nothing was signed on it, said after the verdict (attest.yml's job `refused` posts a suite that did
    not pass here this way). It is a record, not a condition: when it cannot be posted the run's page still has it,
    and says so.

    `about` (the order, the case and the pull request, with `word`: rejected or insufficient_evidence) on a run that
    signed nothing: a receipt of that verdict is written beside it (`_unpaid`: the outputs `receipt` and `evaluation`,
    and the `knos-receipt:` line of the comment), so a rejected or undecided run leaves a receipt, one that never
    authorises payment. `appealed`: how an appeal of this verdict ended (knos.appeal.reply), said last."""
    line = json.dumps(v, sort_keys=True, separators=(",", ":")) if v is not None else ""
    made, counted = _unpaid(run, about["word"], about, line) if about is not None and (refused or v is None) else (None, "")
    if made is not None:
        from . import receipt as rc
        run.output("receipt", rc.canonical(made).decode("utf-8").strip())
    if counted:
        run.output("evaluation", counted)
    if v is None:
        return
    run.output("verdict", line)
    here = str(run.env.get("GITHUB_REPOSITORY") or "")
    if here.count("/") != 1:
        return
    why = f"\n\nNothing was signed: {' '.join(refused.split()).rstrip('.')}." if refused else ""     # its untrusted parts are _plain already
    beside = f"\n{RECEIPT}{run.outputs['receipt']}" if made is not None else ""
    try:
        run.github(f"repos/{here}/issues/{_tokens_issue(run.github, here)}/comments",
                   {"body": f"{VERDICT}{line}{beside}\n\nHow this run reached its verdict: {v['sentence']}.{_reason_said(v)}{why}"
                            + (f"\n\n{appealed}" if appealed else "")})
    except Exception as why:  # noqa: BLE001
        run.note(f"Knos attest: the verdict could not be posted on the \"{TOKENS}\" issue of {here} ({_short(why)}). It is this job's output `verdict`.")


def _appeal_ended(run: Run, v: dict, c: Case, pull: dict) -> str:
    """An appeal of this pull request's verdict, ended on the neutral judge's verdict `v` (knos.appeal): what memory
    holds of it is resumed, resolved and remembered, and the reply that says how it ended is posted on the pull
    request and returned. "" when memory holds no open appeal of it, or cannot be read: an appeal is never in a
    payment's way."""
    try:
        from . import appeal, ids
        from .proof import history, memory
        store = _memory(run)
        if store is None or not history.appeals(store, run.repo):
            return ""
        number, head = int(pull["number"]), str((pull.get("head") or {}).get("sha") or "")
        thash = hashlib.sha256(terms.canonical(c.terms)).hexdigest() if c.terms else ""
        deliverable = ids.deliverable(thash or run.repo, c.issue or number)         # as `/knos appeal` named them (`_appeal`)
        row = appeal.recalled(store, run.repo, ids.evaluation(deliverable, head, thash, "knos", head or number))
        if row is None or row.get("state") not in ("open", "rerun"):
            return ""
        ended = appeal.resolve(appeal.resume(row, run.repo, deliverable, mode=str((c.terms or {}).get("mode") or "tests"),
                                             arbiter=str((c.terms or {}).get("arbiter") or "")), run.clock(), rerun=v)
        appeal.remember(store, ended)
        said = appeal.reply(ended)
        try:
            kept = memory.push(run.repo, store, run.github, run.github, str(run.env.get("GITHUB_RUN_ID") or ""))
            run.github(f"repos/{run.repo}/issues/{number}/comments", {"body": said})
        except Exception:  # noqa: BLE001 - a neutral run's token writes nothing in the order's repository
            kept = None
        if kept is None:
            run.note(f"Knos attest: the appeal of pull request #{number} ended {ended['state']}, and that could not be written in {run.repo} from this run: "
                     "it is said with the verdict, and `/knos status` there reads it again.")
        return said
    except Exception as why:  # noqa: BLE001
        run.note(f"Knos attest: an appeal of this verdict could not be read or ended ({_short(why)}). The verdict stands as it is.")
        return ""


def attest(run: Run, order: str, kind: str, pull: int | None = None, payees: str = "", plan: str = "", judge: str = "",
           judge_fn=None) -> int:
    """`knos attest --repository R --pull P --order O --kind pay|take|revert|rule|eval [--payees ...]`: what attest.yml runs,
    in ANY repository. `run.repo` is R, the repository the work order is for, and nothing is read of it but GitHub's
    public record: the pull request and its merge, each required check of the order's terms at its last commit, the
    issues it closes, the default branch's history (a revert). The rules are settle's own (`_decide`); when they
    hold, GitHub is asked to sign the audience the chain expects:

        pay      knos3:pay:<order>:<head>:<terms>:<mode>:<pull>:<payees>     the merge met the order's terms
        take     knos3:take:<order>:<the starter's id>:<days>                the issue is free to reserve
        revert   knos3:revert:<order>:<head>                                 the merge was reverted on the default branch
        rule     knos3:rule:<order>:<payees>                                 the starter is the order's arbiter
        eval     knosm:eval:<buyer>:<seller>:<work order>:<head>:...         knos_meter: the buyer merged it, or closed it unmerged
                                                                             (`--order` is then `<work order>.<milestone>.<rate>`: _attest_eval)

    The chain, not this command, decides whose signature counts (the order's repository; a run started by hand in a
    repository its starter owns, for a NEUTRAL order; the arbiter). When it refuses, it says what it found, in plain
    words, and signs nothing: exit 1. With KNOS_RELAY_KEY the token is relayed here. Without, it is posted where a
    relayer finds it: a comment on the issue titled "knos tokens" of the repository the run is in (GITHUB_REPOSITORY;
    the issue is made the first time, so the job's token needs `issues: write` there), with the word Knos's public
    relay searches for; the relay's verdict is waited for, and the comment's link is the job's output `comment`. The
    token itself is always the output `token`.

    HOW A PAYMENT'S VERDICT IS REACHED (kind pay). For an order paid on the merge, from GitHub's record: the conclusions
    of the checks its terms name, at the merged commit. For an order paid by its acceptance checks (tests mode), never
    from anyone's record of the suite: attest.yml's first job, which has no token permission, runs the suite itself
    (`plan`, then `judge`: `_rerun_job`) and hands this command its verdict in KNOS_RERUN; this command reads the
    order, the pull request and the bundle again and signs only for a verdict that passed on exactly those. The
    verdict (`reexecuted` true or false, and where it ran) is posted beside the token and is the output `verdict`."""
    def no(why: str, found: str = "") -> int:
        run.note(f"Knos attest: nothing was signed. {why}" + (f"\n\nWhat was found:{found}" if found else ""))
        return 1
    actor = {"id": int(run.env.get("GITHUB_ACTOR_ID") or 0), "login": str(run.env.get("GITHUB_ACTOR") or ""), "type": "User"}
    if kind not in KINDS:
        return no(f"`--kind` is one of {', '.join(KINDS)}.")
    if (plan or judge) and kind != "pay":       # only a payment has a suite to run again: the job that signs decides the rest
        return _rerun_job(run, None, plan, False)
    if judge:
        return _rerun_job(run, None, judge, True, judge_fn)
    if kind == "eval":
        return _attest_eval(run, order, pull, no)
    if kind in ("batch", "claim"):      # knos_meter's batch mode: one batch of a ledger file in the repository (knos.ledger.attest_batch)
        return __import__("knos.ledger", fromlist=["attest_batch"]).attest_batch(run, order, kind, no, _attest_sign)
    try:
        address = Pubkey.from_string(str(order).strip())
        o = pay.read_order(run.ledger.account(address))
    except ValueError:
        return no(f"`{_plain(order)}` is not a Solana address: --order is the work order's address, as its page shows it.")
    except Exception as why:  # noqa: BLE001
        return no(f"Solana could not be read just now ({_short(why)}). Run the workflow again.")
    rp = _repo(run)
    if o is None or rp is None:
        return no(f"No work order is at `{address}` on Solana ({run.env.get('KNOS_CLUSTER', 'devnet')}): it was paid, refunded, or never "
                  "there." if rp is not None else f"GitHub did not answer for the repository {run.repo}. Run the workflow again.")
    if o.repo_id != rp["id"]:
        return no(f"The work order `{address}` is not for {run.repo}: it is for the repository with GitHub id {o.repo_id}, issue #{o.issue}.")
    own = str(run.env.get("GITHUB_REPOSITORY_ID") or "") == str(o.repo_id)
    if not own and kind != "rule" and not o.flags & pay.F_NEUTRAL:
        return no(f"This work order was funded with `neutral off`: only {run.repo}'s own workflow can sign for it.")
    what = f"the work order on {run.repo} issue #{o.issue} ({_sum(run, [(address, o)])})"
    c = Case(o.issue, False, [(address, o)], order=True)
    found = pull_ = None
    if kind == "take":
        _terms_of(run, c)
        issue = _read(run, f"repos/{run.repo}/issues/{o.issue}")
        if not c.terms or not isinstance(issue, dict):
            return no(f"{(c.unread or c.why or ['GitHub did not answer for the issue'])[0][0].upper()}{(c.unread or c.why or ['GitHub did not answer for the issue'])[0][1:]}. Run the workflow again.")
        if o.state != "open" or not o.reserve_days or (o.reserved_by and o.reserved_until > run.now() and o.reserved_by != actor["id"]):
            return no(f"{what[0].upper()}{what[1:]} " + ("is not open." if o.state != "open" else "takes no reservations." if not o.reserve_days else
                                                        f"is reserved for GitHub user id {o.reserved_by} until {who.when(o.reserved_until)}."))
        got = who.take(issue, terms.pages(f"repos/{run.repo}/issues/{o.issue}/events", run.github), {**c.terms, "reserve": o.reserve_days}, actor, run.clock(),
                       auto=bool(o.flags & order_auto.F_AUTO))
        held = [a.get("login") for a in issue.get("assignees") or [] if isinstance(a, dict) and a.get("id") != actor["id"]]
        if not got.assign and not (not held and any(isinstance(a, dict) and a.get("id") == actor["id"] for a in issue.get("assignees") or [])):
            return no(got.reply.split("Knos: ", 1)[-1])
        aud, said = f"knos3:take:{address}:{actor['id']}:{o.reserve_days}", f"{what} is reserved for @{actor['login']} for {_days(o.reserve_days)}"
    elif kind == "rule":
        if not o.arbiter_id or actor["id"] != o.arbiter_id:
            return no(f"{what[0].upper()}{what[1:]} " + (f"names GitHub user id {o.arbiter_id} as its arbiter, and this run was started by "
                                                        f"@{actor['login']} (id {actor['id']})." if o.arbiter_id else "names no arbiter, so nobody can rule on it."))
        try:
            ruled = pay.payees_of("x:" + payees.strip())
            assert 1 <= len(ruled) <= pay.MAX_PAYEES and sum(bps for _i, bps, _a in ruled) == 10_000 and all(i > 0 and bps > 0 for i, bps, _a in ruled)
        except Exception:  # noqa: BLE001
            return no("A ruling names who is paid: `--payees` is one to four entries `id.bps.address` separated by commas, where id is a "
                      "GitHub user id, the bps add up to 10000, and address is a Solana address or `-` for the id's bound wallet.")
        aud, said = f"knos3:rule:{address}:{pay.payees_text(ruled)}", f"the arbiter's ruling on {what}: it pays {pay.payees_text(ruled)}"
    else:
        pull_ = _pull(run, pull) if pull else None
        if pull_ is None:
            return no(f"GitHub did not answer for pull request #{pull} of {run.repo}." if pull else "`--pull` is the pull request's number.")
        number, head = int(pull_["number"]), str((pull_.get("head") or {}).get("sha") or "")
        if not pull_.get("merged_at"):
            return no(f"Pull request #{number} of {run.repo} is not merged. A work order is paid, and a warranty judged, after the merge.")
        if kind == "revert":
            aud, said = _reverted(run, rp, pull_, address, o)
            if not aud:
                return no(said)
        else:
            _terms_of(run, c)
            listed, run._edited[number] = closing.facts(run.repo, number, run.github)
            if o.issue not in closing.closed_by(pull_, listed):
                c.why.append(f"pull request #{number} does not close issue #{o.issue} (its description would say `Fixes #{o.issue}`)")
            if o.state != "open":
                c.why.append("the order is not open: it has paid already, or is held for its payee")
            try:
                todo = _rerun_plan(run, address, o, pull_, c)
            except OSError as why:
                return no(f"{_short(why)}. Run the workflow again.")
            if plan:
                return _rerun_job(run, todo, plan, False)
            verdict: dict | str | None
            verdict, refused, undecided, appealed = _rerun_verdict(None, run.env), "", False, ""
            if todo is not None:       # paid by its acceptance checks: only on a verdict this run's own first job reached by running them
                verdict = _rerun_read(str(run.env.get(RERUN_ENV) or "")) if run.env.get(RERUN_ENV) else (
                    "this order is paid by its acceptance checks, and they were not run again here: attest.yml's first job does that")
                if isinstance(verdict, dict) and not verdict["reexecuted"]:
                    verdict = "this order is paid by its acceptance checks, and the verdict handed to this job says they were not run"
                refused = verdict if isinstance(verdict, str) else _rerun_holds(verdict, todo)
                undecided = isinstance(verdict, dict) and verdict.get("verdict") == "insufficient_evidence"
                if refused:     # a run that could not decide is nobody's refusal: it is something that could not be read
                    (c.unread if undecided else c.why).append(refused)
                if not isinstance(verdict, dict):       # a refusal in words (said above): there is no verdict to post
                    verdict = None
                run.judged_at = todo["base"]
                appealed = _appeal_ended(run, verdict, c, pull_) if verdict is not None and verdict["reexecuted"] else ""
            _decide(run, rp, pull_, [c], listed, tests=todo is not None)
            found = (f"\n- pull request #{number} by @{(pull_.get('user') or {}).get('login')}, merged on {who.when(who._ts(pull_.get('merged_at')) or 0)} "
                     f"at commit `{head[:7]}`" + _rows(c) + _pays(c, "pays").replace("\nIt pays", "\n- it pays"))
            found += f"\n- how this verdict was reached: {(verdict or {}).get('sentence') or 'the acceptance suite was not run again here'}"
            if c.verdict() != "yes":
                # rejected only on something certain: the suite failed when it was run here, or the record refuses it. A run that
                # could not tell (no verdict, another run's verdict, something unread) is insufficient evidence
                certain = (c.scope or c.listed or set(c.checks.values()) & {"failed", "skipped", "absent"} or [w for w in c.why if w != refused]
                           or refused.startswith("the acceptance suite did not pass"))
                word = "rejected" if certain and not undecided else "insufficient_evidence"
                _rerun_said(run, verdict, refused, {"word": word, "address": address, "order": o, "case": c, "pull": pull_, "buyer": rp["owner"]}, appealed)
                if undecided:
                    return no(f"{UNDECIDED[0].upper()}{UNDECIDED[1:]} whether pull request #{number} takes {what}. {UNDECIDED_MEANS}: run the workflow again.", found)
                return no(f"Pull request #{number} does not take {what} as GitHub's record stands"
                          + (", or something could not be read: run the workflow again." if c.verdict() in ("unread", "wait") else "."), found)
            aud = _order_audience(pull_, c, c.where.get("address") if c.where.get("from") == "comment" else None)
            if payees.strip() and payees.strip() != aud.split(":")[-1]:
                return no(f"`--payees {_plain(payees.strip())}` is not who GitHub's record says is paid ({aud.split(':')[-1]}). Leave it empty.", found)
            said = f"pull request #{number} takes {what}: it pays {', '.join('@' + str(x[3]) for x in c.payees)}"
            code = _attest_sign(run, kind, aud, said, found, pull or o.issue, o, no, c, pull_)
            _rerun_said(run, verdict, appealed=appealed)       # after the token, so that a relayer's first comment on the issue is the token's
            return code
    return _attest_sign(run, kind, aud, said, found, pull or o.issue, o, no)


def _attest_sign(run: Run, kind: str, aud: str, said: str, found: str | None, number: int, o, no, case: "Case | None" = None,
                 pull: dict | None = None) -> int:
    """The end of `knos attest`, whatever it asks for: GitHub signs `aud`, and the token is relayed here or posted for
    a relayer. `o`: the work order the token is for (None for an evaluation, which names none on chain)."""
    try:
        jwt = run.mint(aud)
    except Exception as why:  # noqa: BLE001
        return no(f"GitHub did not sign ({_short(why)}). Run the workflow again.", found or "")
    pin = _pin(jwt)
    if pin and o is not None and (bytes(o.wf_repo_hash), o.wf_sha) != pin:
        return no(f"The order was funded through Knos's workflows at commit `{o.wf_sha[:7]}`, and only a run at that commit is accepted for "
                  f"it; this run used `{pin[1][:7]}`. Point your knos-attest.yml at commit `{o.wf_sha}`.", found or "")
    if case is not None and not _terms3_signer(run, case, jwt, pull or {}):     # an order under Knos Terms 3: only an evaluator its terms name
        stopped = (case.why or case.unread or ["its terms do not name this run as a judge"])[-1]
        return no(f"Nothing is sent: {stopped}.", found or "")
    run.output("audience", aud)
    where = None
    carried = ("It is no secret: it can do only what it names, once. Any relayer carries it to Solana: `knos relay` with a funded key, or "
               "Knos's public relay.")
    if not run.env.get("KNOS_RELAY_KEY"):
        run.output("token", jwt)
        here = str(run.env.get("GITHUB_REPOSITORY") or "")
        if here.count("/") != 1:        # not a workflow's job: there is no repository to post in
            run.note(f"Knos attest: GitHub signed that {said}.{found or ''}\n\nThe signed token is above (`token=`). {carried}")
            return 0
        try:
            number, where = _tokens_issue(run.github, here), here
        except Exception as why:  # noqa: BLE001 - a job with no `issues: write`, or GitHub did not answer
            run.note(f"Knos attest: GitHub signed that {said}, but the token could not be posted for a relayer on the \"{TOKENS}\" issue of {here} "
                     f"({_short(why)}): the job needs `issues: write` there.{found or ''}\n\nThe signed token is above (`token=`). {carried}")
            return 1
    r = deliver("proof" if kind == "pay" else kind, jwt, number, run=run, where=where)
    if r.get("comment"):
        run.output("comment", r["comment"])
    posted = f" The token is posted for any relayer at {r['comment']}." if r.get("comment") else ""
    late = (" Solana takes it until an hour after it expires: when a relayer carries it, "
            + ("the evaluation is counted." if kind == "eval" else "the payment is made.")) if r.get("timeout") else ""
    run.note(f"Knos attest: GitHub signed that {said}" + (f", and Solana took it ({_link(run, 'transaction', 'tx', r['sigs'][-1]) if r['sigs'] else r['note']})."
                                                         if r["ok"] else f", but Solana did not take it: {r['why'].rstrip('. ')}.") + posted + late + (found or ""))
    return 0 if r["ok"] else 1


def _reverted(run: Run, rp: dict, pull: dict, address, o) -> tuple[str, str]:
    """(the revert audience, what was found) when the default branch's history holds a revert of the pull request's
    merge inside the order's warranty; ("", why not) otherwise. A revert is a commit after the merge whose message
    names the merge commit the way `git revert` and GitHub's Revert button write it."""
    number, merge = int(pull["number"]), str(pull.get("merge_commit_sha") or "")
    if o.state != "warranty":
        return "", f"The work order on {run.repo} issue #{o.issue} holds nothing back now: a revert counts only inside its warranty."
    since = urllib.parse.quote(str(pull.get("merged_at") or ""), safe="")
    commits = terms.pages(f"repos/{run.repo}/commits?sha={urllib.parse.quote(rp['branch'], safe='')}&since={since}", run.github, cap=5)
    if commits is None or not merge:
        return "", f"GitHub did not answer for {run.repo}'s history since the merge. Run the workflow again."
    hit = next((x for x in commits if isinstance(x, dict) and x.get("sha") != merge
                and re.search(rf"\bThis reverts commit {merge[:12]}[0-9a-f]*\b", str((x.get("commit") or {}).get("message") or ""))), None)
    if hit is None:
        return "", (f"No commit on `{rp['branch']}` of {run.repo} since the merge reverts pull request #{number}'s merge commit `{merge[:7]}` "
                    f"({len(commits)} looked at): its message would say `This reverts commit {merge}`.")
    return (f"knos3:revert:{address}:{(pull.get('head') or {}).get('sha') or ''}",
            f"commit `{str(hit.get('sha'))[:7]}` on `{rp['branch']}` reverts pull request #{number}'s merge `{merge[:7]}`, so the warranty of the work order "
            f"on {run.repo} issue #{o.issue} goes back to its funder")


def neutral(run: Run, url: str) -> int:
    """`knos settle --neutral <pull request URL>`, on the seller's own machine: for each NEUTRAL work order the merged
    pull request could take, start `knos attest` (kind pay) in the seller's own repository `knos-attest` through the
    GitHub CLI. That run, not this command, decides and signs: from GitHub's record for an order paid on the merge, and
    from its own run of the acceptance checks for an order paid by them (`_rerun_job`)."""
    number = int(url.rstrip("/").rsplit("/", 1)[-1])
    rp, pull = _repo(run), _pull(run, number)
    if rp is None or pull is None:
        print(f"GitHub did not answer for {url}. Try again.")
        return 1
    if not pull.get("merged_at"):
        print(f"Pull request #{number} of {run.repo} is not merged. A work order is paid after the merge.")
        return 1
    cases, closes, _listed, blind, _held = _find(run, rp, pull)
    orders = [c for c in cases if c.order]
    mine = [c for c in orders if c.jobs[0][1].flags & pay.F_NEUTRAL]
    if not mine:
        print(f"Solana could not be read for {run.repo}. Try again." if blind else
              f"Pull request #{number} of {run.repo} closes {', '.join(f'#{n}' for n in closes) or 'no issue'}, and "
              + ("its work order was funded with `neutral off`: only that repository's own workflow can have it paid (`/knos settle` on the pull request)."
                 if orders else "no open work order waits there. `/knos status` on the pull request says what does."))
        return 1
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(run.clock() - 60))
    try:
        login = run.gh("api", "user", "--jq", ".login").strip()
        here = f"{login}/knos-attest"
        for c in mine:
            run.gh("workflow", "run", "knos-attest.yml", "--repo", here, "-f", f"repository={run.repo}", "-f", f"pull={number}",
                   "-f", f"order={c.jobs[0][0]}", "-f", "kind=pay")
            how = (f"This order is paid by its acceptance checks, so the run does not take {run.repo}'s word for them: it fetches the two "
                   f"commits of pull request #{number}, runs the checks again in {here}, and asks GitHub to sign only if they pass"
                   if _by_tests(c) else f"It reads GitHub's public record of pull request #{number} and asks GitHub to sign")
            print(f"Started `knos attest` in {here} for {_what(run, c)} of {run.repo}, order {c.jobs[0][0]}. {how}; its page says what it "
                  f"found: https://github.com/{here}/actions")
    except OSError as why:
        print(f"The attest workflow was not started: {_short(why)}. It needs the GitHub CLI signed in (`gh auth login`) and a repository of your "
              "own named knos-attest that holds examples/knos-attest.yml from drexthealpha/Knos as .github/workflows/knos-attest.yml.")
        return 1
    # where the run posts what GitHub signed: one comment on the "knos tokens" issue of that repository, which Knos's
    # public relay finds and carries. The issue is made here if it is not there, and each comment's link is printed
    try:
        issue = _tokens_issue(lambda path, data=None: _gh_api(run, path, data), here)
    except Exception:  # noqa: BLE001 - the run makes the issue itself; only the link cannot be printed
        print(f"The run posts its signed token as a comment on the issue titled \"{TOKENS}\" of {here}: https://github.com/{here}/issues")
        return 0
    for c in mine:
        link = _token_comment(run, here, issue, str(c.jobs[0][0]), since)
        print(f"The signed token for order {c.jobs[0][0]} is posted at {link}. Knos's public relay carries it to Solana from there; anyone may."
              if link else
              f"The run has not posted its signed token for order {c.jobs[0][0]} yet. It will be a comment on https://github.com/{here}/issues/{issue} "
              "(when the run signs: its page says if it does not, and why).")
    return 0


def _gh_api(run: Run, path: str, data: dict | None = None):
    """GitHub's API through the GitHub CLI, as the person signed in to it: a GET, or a POST of `data`'s text fields."""
    fields = [x for k, v in (data or {}).items() for x in ("-f", f"{k}={v}")]
    out = run.gh("api", *(["-X", "POST"] if data is not None else []), path, *fields)
    return json.loads(out) if out.strip() else None


def _token_comment(run: Run, here: str, issue: int, order: str, since: str) -> str | None:
    """The link of the comment on `here`'s tokens issue that carries a token for this order, posted since `since`:
    looked for every NEUTRAL_EVERY seconds for NEUTRAL_WAIT. None when the run has not posted one by then."""
    end = run.clock() + NEUTRAL_WAIT
    while True:
        try:
            got = _gh_api(run, f"repos/{here}/issues/{issue}/comments?since={since}&per_page=100")
        except (OSError, ValueError):
            got = None
        for c in got if isinstance(got, list) else []:
            for jwt in re.findall(r"^knos-(?:proof|take|revert|rule): (eyJ[\w-]+\.[\w-]+\.[\w-]+)[ \t\r]*$", str(c.get("body") or ""), re.M):
                if str(_claims(jwt).get("aud") or "").split(":")[2:3] == [order] and c.get("html_url"):
                    return str(c["html_url"])
        if run.clock() >= end:
            return None
        run.sleep(NEUTRAL_EVERY)


# ---- knos canary: one full round, timed --------------------------------------------------------------------------------

CANARY_WAIT, CANARY_EVERY = 300, 5      # seconds each leg may take (the payment's five minutes are the release's promise), and between looks
LEGS = ("fund", "open", "check", "merge", "pay")


def _rest(env) -> object:
    """`api(method, path, data=None)` on api.github.com with the job's GH_TOKEN, for what the canary alone does there
    (open an issue and a pull request, write one file, merge): knos.judge.github sends none of those."""
    import urllib.request

    def api(method: str, path: str, data: dict | None = None):
        req = urllib.request.Request(f"https://api.github.com/{path}", method=method, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Authorization": f"Bearer {env.get('GH_TOKEN') or env.get('GITHUB_TOKEN') or ''}", "User-Agent": "knos-canary",
                                              "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - api.github.com
            raw = resp.read()
        return json.loads(raw) if raw else None
    return api


def canary(run: Run, api=None, amount: str = "5") -> int:
    """`knos canary`: one full round on devnet from the faucet, in the repository it runs in, as a user would see it.
    It opens an issue whose description funds it (`/knos fund`), opens a pull request that closes it, waits for the
    pull request's checks to pass, merges it, and waits for Knos's comment that the payment was made. The seconds
    of each leg are printed, written to the job's outputs and summary, and logged as one `knos-canary {json}` line:

        fund    the issue opened -> Knos's comment that the money is in escrow
        open    -> the pull request is open
        check   -> every check on its last commit has finished, and none failed
        merge   -> GitHub merged it
        pay     the merge -> Knos's comment that it was paid (or is held for the payee)

    Exit 1 when a leg fails, or when the payment does not land within 5 minutes of the merge; the line says which."""
    took: dict
    api, repo, took = api or _rest(run.env), run.repo, {}
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(run.clock()))

    def wait(what, limit: float = CANARY_WAIT):
        """`what()` until it gives something, looked at every few seconds; None when the limit passes first."""
        end = run.clock() + limit
        while True:
            try:
                got = what()
            except Exception:  # noqa: BLE001 - GitHub did not answer this time
                got = None
            if got or run.clock() >= end:
                return got
            run.sleep(CANARY_EVERY)

    def knos_said(number: int, *marks: str):
        return lambda: next((str(c.get("body")) for c in api("GET", f"repos/{repo}/issues/{number}/comments?per_page=100") or []
                             if str(c.get("body") or "").startswith("Knos") and any(m in str(c.get("body")) for m in marks)), None)

    def done(ok: bool, leg: str, why: str = "") -> int:
        line = json.dumps({"repo": repo, "at": stamp, "ok": ok, **{k: took.get(k) for k in LEGS}, **({"failed": leg, "why": why} if not ok else {})},
                          separators=(",", ":"))
        for name in LEGS:
            if name in took:
                run.output(f"{name}_seconds", took[name])
        run.note(("Knos canary: paid. " if ok else f"Knos canary: the `{leg}` leg failed: {why} ")
                 + ", ".join(f"{k} {took[k]} s" for k in LEGS if k in took) + f".\n\nknos-canary {line}")
        return 0 if ok else 1

    try:
        t = run.clock()
        issue = int(api("POST", f"repos/{repo}/issues", {"title": f"knos canary {stamp}", "body": f"A timed round of Knos on test USDC.\n\n/knos fund {amount} checks: none\n"})["number"])
        said = wait(knos_said(issue, "is in escrow", "nothing was funded", "not confirmed", "stopped"))
        took["fund"] = round(run.clock() - t)
        if not said or "is in escrow" not in said:
            return done(False, "fund", _short(said or f"no reply from Knos on issue #{issue} within {CANARY_WAIT} s"))
        t = run.clock()
        base = api("GET", f"repos/{repo}")["default_branch"]
        tip = api("GET", f"repos/{repo}/git/ref/heads/{base}")["object"]["sha"]
        branch = f"knos-canary-{stamp}"
        api("POST", f"repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": tip})
        api("PUT", f"repos/{repo}/contents/canary/{stamp}.txt", {"message": f"canary {stamp}", "branch": branch,
                                                                  "content": base64.b64encode(f"{stamp}\n".encode()).decode()})
        pull = api("POST", f"repos/{repo}/pulls", {"title": f"knos canary {stamp}", "head": branch, "base": base, "body": f"Fixes #{issue}"})
        number, head = int(pull["number"]), str(pull["head"]["sha"])
        took["open"] = round(run.clock() - t)
        t = run.clock()

        def checked():
            runs = (api("GET", f"repos/{repo}/commits/{head}/check-runs?per_page=100") or {}).get("check_runs") or []
            return runs if runs and all(r.get("status") == "completed" for r in runs) else None
        runs = wait(checked)
        took["check"] = round(run.clock() - t)
        bad = [str(r.get("name")) for r in runs or [] if r.get("conclusion") not in ("success", "neutral", "skipped")]
        if not runs or bad:
            return done(False, "check", f"`{_plain(bad[0])}` did not pass on pull request #{number}" if bad else
                        f"the checks on pull request #{number} did not finish within {CANARY_WAIT} s")
        t = run.clock()
        api("PUT", f"repos/{repo}/pulls/{number}/merge", {"merge_method": "squash"})
        took["merge"] = round(run.clock() - t)
        t = run.clock()
        said = wait(knos_said(number, "paid.", "held for", "not paid", "nothing to pay", "stopped"))
        took["pay"] = round(run.clock() - t)
        if not said or not said.startswith(("Knos: paid.", "Knos: held for")):
            return done(False, "pay", _short(said) if said else f"the payment for pull request #{number} did not land within {CANARY_WAIT // 60} minutes of the merge")
        return done(True, "")
    except Exception as why:  # noqa: BLE001 - GitHub said no: the leg it was in is the one that failed
        return done(False, next((k for k in LEGS if k not in took), "pay"), f"{type(why).__name__}: {_short(why)}")


# ---- knos review and knos check --------------------------------------------------------------------------------------

def review(run: Run) -> int:
    """`knos review`: the check again where it may write. Finds the pull request of the finished "knos check" run by
    its head commit and head repository, and keeps one comment on it up to date: whether it takes a bounty and
    which, what is still missing, who would be paid and how to give an address. What the judge learned goes to the
    knos-memory issue. When the pull request closes an issue whose bounty is paid by acceptance checks, what the
    workflow's next jobs need is written to $GITHUB_OUTPUT: `tests` and `issue` (that issue's number), `pull`,
    `head` (the commit reviewed) and `terms` (the bounty's terms as funded, one line of JSON)."""
    wr, rp = run.event.get("workflow_run") or {}, _repo(run)
    pull = _pull_of(run, wr) if rp and wr.get("event") == "pull_request" else None
    if pull is None or rp is None:
        run.note("Knos review: no open pull request has this run's head commit (it has moved on, or the run was not for a pull "
                 "request), so there is nothing to review.")
        return 0
    try:
        found, head = _find(run, rp, pull), (pull.get("head") or {}).get("sha") or ""
        parts, _gate_said = _advice(run, rp, pull, found, 0, True, True)
        judged = next((c for c in _judged(found[0]) if c.terms), None)      # tests mode: the sandboxed judge runs next, on this
        if judged is not None:
            for name, value in (("tests", judged.issue), ("issue", judged.issue), ("pull", int(pull["number"])), ("head", head),
                                ("terms", judged.raw.decode("ascii"))):
                run.output(name, value)
        return 0 if _publish(run, int(pull["number"]), parts, head) else 1
    except Exception as why:  # noqa: BLE001
        run.note(f"Knos review: stopped before it was finished ({type(why).__name__}: {_short(why)}). `/knos status` on the pull "
                 "request says the same things.")
        return 1


def check(run: Run) -> int:
    """`knos check`: the advisory check on a pull request. It comments nowhere and writes nothing on any chain; its
    answer is the job's summary and its exit status: 1 only for a claim in the description that a finished check
    contradicts, or a broken rule of the repository (its CONTRIBUTING file, and what its history made required).
    Never for an issue that is not funded, a bounty this pull request does not take, or anything that is pending or
    could not be read. It waits up to ten minutes for the checks it reads to finish, so the review that follows it
    sees how they ended."""
    pull, rp = run.event.get("pull_request"), _repo(run)
    if not isinstance(pull, dict) or not pull.get("number") or rp is None:
        run.note("Knos check: this run is not for a pull request Knos could read, so nothing was checked.")
        return 0
    try:
        found = _find(run, rp, pull)
        parts, gate_said = _advice(run, rp, pull, found, CLAIMS_WAIT, False, False)
    except Exception as why:  # noqa: BLE001 - Knos's own failure is never held against a pull request
        run.note(f"Knos check: stopped before it was finished ({type(why).__name__}: {_short(why)}). Nothing is held against "
                 "this pull request.")
        return 0
    broken = bool(gate_said["reasons"])
    run.note("### Knos check\n\n" + _join(parts or ["this pull request closes no funded issue, and nothing is held against it."], "")
             + "\n\n" + ("**Failed**: a claim in the description is false, or a rule of this repository is broken (listed above)."
                         if broken else "**Passed**: no false claim and no broken rule."
                         + (" Whether this pull request takes a bounty never fails this check." if parts else "")))
    return 1 if broken else 0


def _pull_of(run: Run, wr: dict) -> dict | None:
    """The open pull request a finished workflow run was for: the one whose head is the run's head commit in the
    run's head repository. A fork's run names no pull request, so it is found by its head branch and checked."""
    sha, branch = str(wr.get("head_sha") or ""), str(wr.get("head_branch") or "")
    head = wr.get("head_repository") or {}
    owner, full = str((head.get("owner") or {}).get("login") or ""), str(head.get("full_name") or "").lower()
    found = _read(run, f"repos/{run.repo}/pulls?state=open&head={urllib.parse.quote(f'{owner}:{branch}', safe='')}&per_page=100")
    if not isinstance(found, list) or not any(isinstance(p, dict) and (p.get("head") or {}).get("sha") == sha for p in found):
        found = _read(run, f"repos/{run.repo}/commits/{sha}/pulls?per_page=100")
    for p in found if isinstance(found, list) else []:
        at = (p.get("head") or {}) if isinstance(p, dict) else {}
        if at.get("sha") == sha and p.get("state") == "open" and str((at.get("repo") or {}).get("full_name") or "").lower() == full:
            return _pull(run, p.get("number"))
    return None


def _advice(run: Run, rp: dict, pull: dict, found: tuple, wait: float, payee: bool, learn: bool) -> tuple[list[str], dict]:
    """What the automatic check says of a pull request before its merge, as paragraphs, and the gate's own verdict:
    each bounty it could take judged against GitHub's record so far (`found` is `_find`'s answer), then the free
    check on its description and on the repository's rules (knos.judge.gate), then a funded issue it mentions
    without closing. Runs none of its code. `wait`: seconds to wait for checks that have not finished; `payee`: say
    who would be paid; `learn`: write what the judge learned to its memory."""
    from .proof import claims
    cases, closes, listed, blind, _held = found
    number, head, body = int(pull["number"]), (pull.get("head") or {}).get("sha") or "", pull.get("body") or ""
    claimed = bool(claims.read(body).kinds & {"tests", "ci"})
    runs, statuses = _record(run, head, cases, wait, every=claimed and wait > 0)
    _judge(run, pull, cases, listed, False, runs, statuses, payee=payee)
    funded = sorted({c.issue for c in cases if not c.tip} | set(_mentioned(run, rp, pull, closes)))
    g = _gate(run, pull, runs, statuses, funded, learn)
    parts = [_before(run, c, pull) for c in cases]
    if g["reasons"]:
        parts.append("this is held against the pull request, bounty or not:" + "".join(f"\n- {r.split(': ', 1)[-1]}" for r in g["reasons"]))
    parts += [*(f"{u}." for u in g["evidence"]["unverified"]), *g["evidence"]["notes"], *_left_out(run, number),
              *_unseen(blind, number, "comment `/knos status`")]
    return parts, g


def _mentioned(run: Run, rp: dict, pull: dict, closes: list[int]) -> list[int]:
    """The funded issues a description names without closing: the bounty its author may have meant."""
    named = [int(a or b) for a, b in re.findall(r"#(\d{1,10})\b|/issues/(\d{1,10})\b", closing.cut(pull.get("body") or ""))]
    funded = []
    for n in list(dict.fromkeys(named))[:MAX_ISSUES]:
        if n in closes or n == pull.get("number"):
            continue
        try:
            if any(j.state == "open" for _a, j in _jobs(run, rp["id"], n)):
                funded.append(n)
        except Exception:  # noqa: BLE001 - a hint, not a decision: left out when the chain does not answer
            pass
    return funded


def _gate(run: Run, pull: dict, runs, statuses, funded: list[int], learn: bool) -> dict:
    """knos.judge.gate on a pull request, with nothing checked out: the description's claims against GitHub's record
    of its head commit, the repository's CONTRIBUTING rules as its base has them, and what the judge's memory (the
    knos-memory issue, loaded into Sibyl's local store) requires. `learn`: post what this run learned there."""
    from . import judge
    from .proof import history, memory
    root = run.scratch()
    try:
        store: Any = history.SibylStore.local(root / "memory")
        if memory.pull(run.repo, store, run.github) is None:
            run.note("Knos: the judge's memory (the knos-memory issue) could not be read; this run remembers nothing.")
    except Exception:  # noqa: BLE001 - no store: the same check, without memory
        store = history.NullStore()
    g = judge.gate(_rules(run, pull, root / "base"), _diff(_changes(run, int(pull["number"]))), store, run.repo,
                   (pull.get("user") or {}).get("login"), pull.get("body") or "", runs, statuses=statuses, funded=funded)
    if learn:
        try:
            memory.push(run.repo, store, run.github, run.github, str(run.env.get("GITHUB_RUN_ID") or ""))
        except Exception as why:  # noqa: BLE001
            run.note(f"Knos: what this run learned could not be written to the knos-memory issue ({_short(why)}).")
    return g


def _rules(run: Run, pull: dict, to: Path) -> Path:
    """The base's CONTRIBUTING file in a folder of its own. The gate reads a repository's rules from the base,
    never from the pull request, and this job checks nothing out."""
    from .proof import history
    base = pull.get("base") or {}
    ref = urllib.parse.quote(str(base.get("sha") or base.get("ref") or ""), safe="")
    to.mkdir(parents=True, exist_ok=True)
    for rel in history.CONTRIBUTING:
        got = _read(run, f"repos/{run.repo}/contents/{rel}?ref={ref}")
        if isinstance(got, dict) and got.get("encoding") == "base64" and isinstance(got.get("content"), str):
            (to / rel).parent.mkdir(parents=True, exist_ok=True)
            (to / rel).write_bytes(base64.b64decode(got["content"]))
    return to


def _diff(files: list | None) -> str | None:
    """A pull request's changes as one unified diff, from GitHub's list of its files (each file's `patch`). A file
    too large for GitHub to show has no patch, and no rule sees it. None when the list could not be read."""
    if files is None:
        return None
    out = []
    for f in files:
        if isinstance(f, dict) and f.get("filename") and isinstance(f.get("patch"), str):
            old = f.get("previous_filename") or f["filename"]
            out.append(f"diff --git a/{old} b/{f['filename']}\n--- a/{old}\n+++ b/{f['filename']}\n{f['patch']}\n")
    return "".join(out)


def _publish(run: Run, number: int, parts: list[str], head: str) -> bool:
    """The review, as the one comment this workflow keeps on a pull request: found by its marker and edited in
    place, else posted. With nothing to say, nothing is posted; a comment from an earlier run is brought up to date."""
    mine = next((c for c in terms.pages(f"repos/{run.repo}/issues/{number}/comments", run.github) or []
                 if isinstance(c, dict) and (c.get("user") or {}).get("type") == "Bot" and str(c.get("body") or "").startswith(MARK)),
                None)
    if not parts and mine is None:
        run.note(f"Knos review: pull request #{number} closes no funded issue and nothing is held against it, so nothing was "
                 "written on it.")
        return True
    text = _join(parts or ["this pull request takes no bounty now: it closes no funded issue, and nothing is held against it."])
    body = f"{MARK}\n{text}\n\nThis is how things stood at commit `{head[:7]}`. `/knos status` on this pull request says how they stand now."
    if mine is None:
        return run.say(number, body)
    try:
        run.github(f"repos/{run.repo}/issues/comments/{mine['id']}", {"body": body}, "PATCH")
    except Exception as why:  # noqa: BLE001
        run.failed = True
        run.note(f"GitHub did not take the edit of Knos's comment on #{number} ({_short(why)}):\n\n{body}")
        return False
    run.note(f"Brought Knos's comment on #{number} up to date:\n\n{body}")
    return True


# ---- `knos relay`: what the public worker runs, and a job that relays its own token -------------------------------------
# Read here and not by the full command line: the worker installs requirements/sign.txt and nothing else. (0.3.13 read
# it with typer, which the worker does not install: every run failed at once, and nobody was paid by the public relay.)

BROKEN = (ImportError, NameError)       # a build that cannot relay, never something GitHub or Solana said: it ends the loop


def relay(token_file: str = "", terms_file: str = "", serve: float = 0.0, every: float = 3.0, *, ghrelay=None, ledger=None,
          payer=None, clock=time.monotonic, sleep=time.sleep, env=None) -> int | str:
    """Carry GitHub-signed tokens to Solana and pay the transaction fees. With --token-file: that one token, now, its
    result printed as JSON (status 1 when Solana did not take it). Else one pass over what repositories posted, or
    passes for `serve` seconds. The exit status is the relay's: a pass that could not run is said in a line and is 1,
    so the job that ran it fails and is seen."""
    env = os.environ if env is None else env
    if env.get("KNOS_FEE_KEY") and not env.get("KNOS_RELAY_KEY"):     # the name a repository's own workflow may give its fee key
        env["KNOS_RELAY_KEY"] = env["KNOS_FEE_KEY"]
    try:
        if ghrelay is None:
            from .proof import ghrelay
        if ledger is None:
            from . import chain
            ledger, payer = chain.ledger(), chain.key()
    except Exception as why:  # noqa: BLE001 - a module that is not installed, or a key that is no key: one line, status 1
        return f"knos relay cannot start: {type(why).__name__}: {_short(why)}"
    if token_file:
        try:
            text = Path(token_file).read_text(encoding="utf-8")
            given = Path(terms_file).read_bytes().strip() if terms_file else None
        except OSError as why:
            return f"knos relay: {why}"
        return _relay_file(ghrelay, ledger, payer, text, given)
    if not serve:
        try:
            ghrelay.once(ledger, payer)
        except Exception as why:  # noqa: BLE001 - whatever stopped the pass, in one line
            return f"knos relay: the pass did not finish: {type(why).__name__}: {_short(why)}"
        return 0
    return _relay_serve(ghrelay, ledger, payer, serve, every, clock, sleep, env)


def _relay_file(ghrelay, ledger, payer, text: str, given: bytes | None) -> int:
    """One token from a file: the token alone, or the comment that carried it. What travels beside it is read as the
    worker reads it (ghrelay.tokens): a key token's `knos-issuer:` line, else `knos-terms:`."""
    found = ghrelay.TOKEN.search(text)
    said = (ghrelay.ISSUER if found and found.group(1) == "key" else ghrelay.TERMS).search(text)
    terms_json = given if given is not None else said.group(1).encode() if said else None
    jwt, timed, seen = found.group(2) if found else text.strip(), getattr(ghrelay, "Timed", None), time.time()
    ledger = timed(ledger) if timed is not None else ledger
    try:
        r = dict(ghrelay.carry(ledger, payer, jwt, terms_json))
    except BROKEN:
        raise
    except Exception as why:  # noqa: BLE001 - not a token, or the cluster did not answer: the result says so
        r = {"ok": False, "why": f"{type(why).__name__}: {_short(why)}"}
    if r.get("ok"):
        r["note"] = ghrelay.note(r)
        if timed is not None:       # the line the public worker would have logged, with its four times: a payment relayed by hand is timed too
            c = _claims(jwt)        # (on stderr: what is printed on stdout is the result as JSON, and nothing else)
            _err(ghrelay.own_line(found.group(1) if found else {"pay": "proof"}.get(str(r.get("kind")), str(r.get("kind") or "token")),
                                         str(c.get("repository") or "-"), int(r.get("issue") or 0), jwt, r, None, seen, time.time(), ledger))
    print(json.dumps(r, default=str), flush=True)
    return 0 if r.get("ok") else 1


def _relay_serve(ghrelay, ledger, payer, seconds: float, every: float, clock, sleep, env) -> int | str:
    """Passes for `seconds`, each starting `every` seconds after the one before (ghrelay.serve's loop), with an exit
    status that tells a relay from a build that cannot relay. One bad pass never stops it (GitHub or the cluster did
    not answer). It ends with status 1 at once when a pass cannot run at all (a module is missing), and at the end
    when not one pass finished: worker.yml then starts no next run, and the run is red."""
    if not (env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")):
        _err("relay: no GH_TOKEN, so GitHub allows 60 requests an hour: most passes will read nothing. Set GH_TOKEN (any token; public reads).")
    end, cranked, done, last = clock() + seconds, None, 0, ""
    while clock() < end:
        began = clock()
        crank = cranked is None or began - cranked >= ghrelay.CRANK_EVERY
        try:
            ghrelay.once(ledger, payer, crank=crank)
            done += 1
        except BROKEN as why:
            return f"knos relay cannot run in this install: {type(why).__name__}: {_short(why)}. Nothing was relayed."
        except Exception as why:  # noqa: BLE001 - one bad pass never stops the worker
            last = f"{type(why).__name__}: {_short(why)}"
            _err(f"relay pass: {last}")
        if crank and hasattr(ghrelay, "publish_status"):        # once a minute: the relay's own status line in its public log (never raises)
            ghrelay.publish_status()
        cranked = began if crank else cranked
        sleep(max(0.0, min(every - (clock() - began), end - clock())))
    return 0 if done else f"knos relay: not one pass finished in {seconds:g} seconds. The last one stopped at: {last or 'no pass was started'}"


def _err(line: str) -> None:
    import sys
    print(line, file=sys.stderr, flush=True)


# ---- the command line of the jobs: the standard library and solders, and nothing else ---------------------------------
# A job that signs installs solders and knos by hash and nothing more (requirements/sign.txt), so the words a workflow
# runs are read here with argparse. The `knos` console script and `python -m knos` come here for these words before
# they import the rest of the command line (typer, rich); `python -m knos.flow <word> ...` is the same thing.

WORDS = ("command", "settle", "review", "check")      # each: `knos <word> --event E --repo R`
MORE = ("attest", "canary", "relay")                         # and the commands that take other options


def takes(args: list[str]) -> bool:
    """Whether a command line is one of a workflow's (and so is read here). `knos check owner/repo#7`, a person's
    command, is not: it is the full command line's."""
    if not args or args[0] not in (*WORDS, *MORE):
        return False
    if args[0] != "check":
        return True
    ours, value = False, False
    for a in args[1:]:
        if value:                   # what --event or --repo was given
            value = False
        elif a in ("--event", "--repo"):
            ours = value = True
        elif a in ("-h", "--help") or a.startswith(("--event=", "--repo=")):
            ours = True
        elif not a.startswith("-"):
            return False            # a pull request by name, whatever else is there: the full command line says what is wrong
    return ours


def _parser():
    import argparse
    p = argparse.ArgumentParser(prog="knos", description="What a repository's workflow runs: one command per job.")
    sub = p.add_subparsers(dest="word", required=True, metavar="{" + ",".join((*WORDS, *MORE)) + "}")

    def job(name: str, about: str):
        s = sub.add_parser(name, help=about.split(": ")[0], description=about)
        s.add_argument("--event", help="the event GitHub handed the workflow (GITHUB_EVENT_PATH)")
        s.add_argument("--repo", help="owner/name (GITHUB_REPOSITORY)")
        return s
    private = ("in the repository an organisation's policy names as its attestor: do this for the repositories that policy lists "
               "(read through KNOS_READ_TOKEN, never checked out), as PRIVATE work orders")
    s = job("command", "A comment, or a new issue: act on its `/knos` line (fund, tip, take, release, the rest) and reply.")
    s.add_argument("--attestor", action="store_true", help=private)
    s.add_argument("--target", default="", metavar="OWNER/NAME", help="with --attestor: only this repository (default: every target of the policy)")
    s = job("settle", "A push to the default branch, a `/knos settle` or `/knos tip` comment, or a workflow_dispatch with a pull "
                      "request's number: pay what each merged pull request earned, and say so on it.")
    s.add_argument("--tests", action="store_true", help="the job after the sandboxed judge passed: sign for the bounty paid by "
                                                        "acceptance checks, for --pull at --head")
    s.add_argument("--pull", type=int, default=0, help="with --tests: the pull request the judge passed")
    s.add_argument("--head", default="", help="with --tests: the commit it passed at; nothing is signed unless the pull request is still at it")
    s.add_argument("--issue", type=int, default=0, help="with --tests: the issue whose acceptance checks were judged (default: the one "
                                                        "`knos review` named)")
    s.add_argument("--attestor", action="store_true", help=private)
    s.add_argument("--target", default="", metavar="OWNER/NAME", help="with --attestor: only this repository (default: every target of the policy)")
    s.add_argument("--neutral", metavar="PULL_URL", default="", help="on your own machine, alone: start `knos attest` for this merged pull "
                                                                    "request in your own knos-attest repository (through `gh`)")
    job("review", "The \"knos check\" workflow finished for a pull request: one comment on it, kept up to date, saying whether it "
                  "takes a bounty, what is missing and who would be paid.")
    job("check", "A pull request, read with a read-only token: its description's claims, the repository's rules and a funded "
                 "issue's terms so far. (One pull request by name, from your own machine: `knos check owner/repo#7`.)")
    s = sub.add_parser("attest", help="Ask GitHub to sign that a work order's terms were met, from any repository",
                       description="What attest.yml runs, in any repository: reads GitHub's public record of --repository and the work order on "
                                   "Solana, applies the rules `knos settle` applies, and asks GitHub to sign only what that record supports.")
    s.add_argument("--repository", required=True, help="the repository the work order is for, as owner/name")
    s.add_argument("--order", required=True, help="the work order's address (eval: <work order's 32-byte id in hex>.<milestone>.<rate>)")
    s.add_argument("--kind", required=True, choices=KINDS, help="pay: the merge met the terms; take: reserve it; revert: the merge was reverted "
                                                                "inside the warranty; rule: you are its arbiter; eval: one evaluation for knos_meter, "
                                                                "run in a repository of the buyer (merged: accepted, closed unmerged: rejected)")
    s.add_argument("--pull", type=int, default=0, help="the pull request's number (pay, revert, eval)")
    s.add_argument("--payees", default="", help="rule: who is paid, as id.bps.address entries separated by commas")
    s.add_argument("--plan", default="", metavar="DIR", help="the job before the one that signs: write DIR/plan.json, what to fetch to run "
                                                             "the order's acceptance suite again (nothing is signed)")
    s.add_argument("--judge", default="", metavar="DIR", help="that job's next step: run the suite on DIR/base and DIR/pr as DIR/plan.json has "
                                                              "it, in the sandbox, and write DIR/verdict.json (nothing is signed)")
    s = sub.add_parser("canary", help="One timed round on devnet: fund, pull request, merge, payment",
                       description="One full round on devnet from the faucet in the repository it runs in (GITHUB_REPOSITORY, with GH_TOKEN a token "
                                   "that may write its issues, pull requests and contents): prints the seconds of each leg, and exits 1 when "
                                   "the payment does not land within 5 minutes of the merge.")
    s.add_argument("--repo", default="", help="owner/name (default: GITHUB_REPOSITORY)")
    s.add_argument("--amount", default="5", help="test USDC to fund the issue with (default 5, the least a work order holds)")
    s = sub.add_parser("relay", help="Carry GitHub-signed tokens to Solana and pay the transaction fees",
                       description="Carry GitHub-signed tokens to Solana and pay the transaction fees (KNOS_RELAY_KEY, or KNOS_FEE_KEY). A relayer "
                                   "decides nothing: the money goes where the token says. With no option: one pass over the tokens "
                                   "repositories posted, which is what the public worker does all day with --serve.")
    s.add_argument("--token-file", "--token", default="", metavar="FILE", help="relay this one token now and print the result as JSON")
    s.add_argument("--terms-file", default="", metavar="FILE", help="a fund token's terms JSON (as its `knos-terms:` line gave them)")
    s.add_argument("--serve", type=float, default=0.0, metavar="SECONDS", help="keep making passes for this long")
    s.add_argument("--every", type=float, default=3.0, help="seconds from one pass to the next, with --serve")
    return p, sub


def _event(a) -> Run | str:
    """The Run a workflow's command gets, or the one line that says why there is none."""
    try:
        payload = json.loads(Path(a.event).read_text(encoding="utf-8"))
    except (OSError, ValueError) as why:
        return f"{a.event} is not the event GitHub handed the workflow: {why}"
    if str(a.repo).count("/") != 1:
        return "Name the repository as owner/name."
    return Run(a.repo, payload)


def _dispatch(a, sub) -> int | str:
    """Run what the command line asks: the job's exit status, or one line that says what is wrong with it."""
    if a.word == "attest":
        if a.repository.count("/") != 1:
            return "Name the repository as owner/name."
        if a.plan and a.judge:
            return "--plan and --judge are two steps: give one."
        return attest(Run(a.repository, {}), a.order, a.kind, a.pull or None, a.payees, a.plan, a.judge)
    if a.word == "relay":
        return relay(a.token_file, a.terms_file, a.serve, a.every)
    if a.word == "canary":
        repo = a.repo or os.environ.get("GITHUB_REPOSITORY") or ""
        if repo.count("/") != 1 or not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,6})?", a.amount):
            return "Name the repository as owner/name (--repo, or GITHUB_REPOSITORY), and the amount as digits, like 5."
        return canary(Run(repo, {}), amount=a.amount)
    if a.word == "settle" and a.neutral:
        m = re.fullmatch(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)/?(?:[?#].*)?", a.neutral.strip())
        if not m or a.event or a.repo or a.tests:
            return "--neutral takes a pull request's URL, like https://github.com/owner/name/pull/7, and nothing else."
        return neutral(Run(m.group(1), {}), f"https://github.com/{m.group(1)}/pull/{m.group(2)}")
    if a.word in WORDS:
        missing = [f"--{n}" for n in ("event", "repo") if not getattr(a, n)]
        if missing:
            sub.choices[a.word].error(f"the following arguments are required: {', '.join(missing)}")
        more = {}
        if a.word == "settle":
            if not a.tests and (a.pull or a.head or a.issue):
                return "--pull, --head and --issue go with --tests: the job that follows the sandboxed judge."
            more = dict(tests=True, pull=a.pull or None, head=a.head, issue=a.issue or None) if a.tests else {}
        run = _event(a)
        if isinstance(run, str):
            return run
        if getattr(a, "attestor", False) or getattr(a, "target", ""):
            if getattr(a, "tests", False) or not a.attestor or (a.target and a.target.count("/") != 1):
                return "--target goes with --attestor and names one repository as owner/name; neither goes with --tests."
            run.attestor, run.only = True, a.target
        return globals()[a.word](run, **more)
    raise ValueError(a.word)


def main(argv: list[str] | None = None) -> int:
    """`python -m knos.flow <command|settle|review|check|attest|canary> ...`, and what the `knos` console script runs for those
    words. Whatever is wrong with the command line is one line, never a traceback; the exit status is the job's."""
    import sys
    parser, sub = _parser()
    try:
        got = _dispatch(parser.parse_args(list(sys.argv[1:] if argv is None else argv)), sub)
    except SystemExit as stop:      # argparse: --help (0), or a usage line already printed (2)
        return int(stop.code or 0)
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    if isinstance(got, str):
        print(got, flush=True)
        return 1
    return int(got)


if __name__ == "__main__":
    raise SystemExit(main())
