"""A seeded state machine over work orders (knos_pay 2.1) in LiteSVM. It keeps a few repositories, issues, Balances,
wallets and orders, picks one action at random per step, and keeps every signed token it ever produced so that any
later step can send it again: as it was built, or against the accounts as they stand by then, with the order made
anew at its address first. After every step it checks, for all the state it has seen:

  (a) each order ever funded: paid out + returned + fees <= funded, with equality once the order is closed;
  (b) no token was accepted twice;
  (c) the test USDC in all token accounts together never changes;
  (d) an order that ended by a refund paid nobody, and one that ended paid returned nothing;
  (e) a Balance's spent counters equal the orders funded from it and never pass its limits;
  (f) every fee is the tier schedule's.

A failure names its seed and step: KNOS_MACHINE_SEED=<seed> replays that seed alone. KNOS_MACHINE_STEPS (steps per
seed) and KNOS_MACHINE_SEEDS (how many seeds) scale the run. The last test runs the same machine against the program
as 0.3.13 built it and requires that it finds that build's double payment within the default budget."""
from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

pytest.importorskip("solders.litesvm")

from solders.instruction import Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import DAY, HEAD, MAINT, OWNER, REPO, USDC, OrderChain, code, transfer, user  # noqa: E402
from _pay2 import TEST_CLAIM_SHA  # noqa: E402

from knos.settle.v2 import oidc, pay  # noqa: E402

DEFAULT_STEPS, DEFAULT_SEEDS = 100, 3
STEPS = int(os.environ.get("KNOS_MACHINE_STEPS", DEFAULT_STEPS))      # read at import: conftest clears KNOS_* per test
ONE = os.environ.get("KNOS_MACHINE_SEED")
SEEDS = [int(ONE)] if ONE else [3140 + k for k in range(int(os.environ.get("KNOS_MACHINE_SEEDS", DEFAULT_SEEDS)))]
OLD_COMMIT, OLD_BUILD = "567fd12", "tests/fixtures/knos_pay_v2_test.so"       # 0.3.13: a pay token could pay a re-funded order
TOTALS = {"steps": 0, "violations": 0}
ACTIONS = ["fund_wallet"] * 2 + ["fund_balance"] * 4 + ["comment"] + ["relay"] * 2 + ["top", "reserve", "cancel", "settle", "release", "revert", "close",
                                                                                     "limits"] + ["pay"] * 5 + ["refund"] * 2 + ["warp"] * 3 + ["replay"] * 6
WARPS = [5, 5, 30, 90, 600, 2 * 3600, 4 * 3600, DAY + 60, 8 * DAY]


def schedule(amount: int, bps: int = 250) -> int:
    """The fee schedule, written out here a second time: `bps` of the first 1,000, 1% up to 50,000, 0.5% above, at least 0.40."""
    first, second, third = min(amount, 1_000 * USDC), max(min(amount, 50_000 * USDC) - 1_000 * USDC, 0), max(amount - 50_000 * USDC, 0)
    return max(first * bps // 10_000 + second * 100 // 10_000 + third * 50 // 10_000, 400_000)


@dataclass
class Book:
    """One funding of one order address: what went in and where it went."""
    address: Pubkey
    source: Pubkey                  # the token account the money came from, and the only one it may go back to
    amount: int = 0                 # what the order says its payees get, as last read
    fee: int = 0
    funded: int = 0
    paid: int = 0
    returned: int = 0
    fees: int = 0                   # FEE_OWNER's part and the relayer's tips
    end: str | None = None          # the action that closed it


@dataclass
class Token:
    kind: str
    account: Pubkey                                             # the verified token account
    address: Pubkey | None                                      # the order it is about
    build: Callable[[bool], Instruction | None]                 # the instruction that carries it: as first built, or (True) for the accounts as they stand
    wins: list = field(default_factory=list)                    # (step, what the payees received) of each transaction that accepted it
    remake: Callable[[], None] | None = None                    # makes the order anew at its address, when that is possible


@dataclass
class Violation:
    letter: str
    kind: str
    text: str


class LegacyChain(OrderChain):
    """The account lists of 0.3.13: only Pay and FundOrderBalance took a marker, and their builders add it themselves."""
    def marked(self, ix):
        return ix


class Machine:
    def __init__(self, seed: int, build: str | None = None, strict: bool = True):
        self.seed, self.strict, self.legacy = seed, strict, build is not None
        self.rng = random.Random(seed)
        self.c = c = LegacyChain(pay_build=build) if build else OrderChain()
        self.step, self.trace, self.bad = 0, [], []
        # two Balances: the first with a side account of limits, the second with a Plan; two funding wallets; four people
        self.owner2, self.repo2 = user(), REPO + 7
        w, wtok = c.wallet(c.usdc, 200_000 * USDC)
        assert c.send([pay.open_balance_ix(w.pubkey(), self.owner2, c.usdc, spenders=[MAINT])], w), c.err
        self.bal2 = pay.balance_pda(self.owner2, w.pubkey(), c.usdc)
        transfer(c, wtok, pay.baltok_pda(self.bal2), 150_000 * USDC, w)
        assert c.set_plan(self.owner2, 150, c.now() + 25 * DAY), c.err
        self.limits = [3_000 * USDC, 20_000 * USDC]
        assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, *self.limits, repos=[REPO, REPO + 1])], c.owner), c.err
        self.day, self.day_spent, self.total_spent = 0, 0, 0
        self.balances = {c.bal: (OWNER, [REPO, REPO + 1], c.owner), self.bal2: (self.owner2, [self.repo2], w)}
        other = c.wallet(c.usdc, 1_000_000 * USDC)
        self.funders = {c.funder.pubkey(): (c.funder, c.funder_tok), other[0].pubkey(): other}
        self.people = [(user(), Keypair().pubkey()) for _ in range(4)]
        self.sources = {c.funder_tok, other[1], pay.baltok_pda(c.bal), pay.baltok_pda(self.bal2)}
        self.books: list[Book] = []
        self.live: dict[Pubkey, Book] = {}
        self.vault: dict[Pubkey, Pubkey] = {}       # an order's token account -> the order
        self.tokens: list[Token] = []
        self.spare: dict[Pubkey, list[Token]] = {}  # fund tokens of a second comment, not relayed yet, by order address
        self.refreshed = c.now()
        self.total = sum(self.snap().values())

    # -- reading ---------------------------------------------------------------------------------------------------
    def snap(self) -> dict[Pubkey, int]:
        """What every SPL token account on the chain holds."""
        return {a: int.from_bytes(bytes(acc.data)[64:72], "little") for a, acc in self.c.svm.get_program_accounts(pay.TOKEN) if len(bytes(acc.data)) == 165}

    def flag(self, letter: str, kind: str, text: str) -> None:
        self.bad.append(Violation(letter, kind, f"seed {self.seed} step {self.step}: ({letter}) {text}"))
        if self.strict:
            raise AssertionError(self.bad[-1].text + "\n  " + "\n  ".join(self.trace[-15:]) + f"\n  replay: KNOS_MACHINE_SEED={self.seed}")

    def rate(self, o: pay.Order) -> int:
        """The first tier's rate an order funded now pays: its owner's Plan from a Balance, 2.5% from a wallet."""
        return pay.plan_bps(pay.read_plan(self.c.data(pay.plan_pda(o.owner_id))), self.c.now()) if o.from_balance else 250

    # -- one transaction, booked -----------------------------------------------------------------------------------
    def act(self, name: str, address: Pubkey | None, send: Callable[[], bool], token: Token | None = None) -> bool:
        """Sends one transaction about one order (or none) and books every unit it moved to that order's funding."""
        c = self.c
        before, was = self.snap(), c.order(address) if address is not None else None
        ok = bool(send())
        after = self.snap()
        self.trace.append(f"{self.step} {name} {str(address)[:6] if address else '-'} {'ok' if ok else 'refused ' + str(code(c) or c.err)}")
        delta = {k: after.get(k, 0) - before.get(k, 0) for k in {*before, *after} if after.get(k, 0) != before.get(k, 0)}
        if not ok or address is None:
            if delta:
                self.flag("c", name, f"{name} moved money without an order: {delta}")
            if ok and token is not None:
                self.accepted(token, name, 0)
            return ok
        book, now = self.live.get(address), c.order(address)
        if book is None:                        # a funding: a new order at this address
            if was is not None or now is None:
                if delta:
                    self.flag("a", name, f"{name} moved money at an address with no open order: {delta}")
                return ok
            src = now.refund_to if now.from_balance else pay.ata(now.refund_to, c.usdc)
            book = self.live[address] = Book(address, src)
            self.books.append(book)
            self.vault[pay.ov_pda(address)] = address
            if now.fee_bps != self.rate(now):
                self.flag("f", name, f"an order was funded at {now.fee_bps} basis points, not {self.rate(now)}")
            if now.source == c.bal:             # counted against the first Balance's limits
                day = c.now() // DAY
                self.day, self.day_spent = day, (self.day_spent if day == self.day else 0) + now.amount + now.fee
                self.total_spent += now.amount + now.fee
        entered = left = paid = fees = 0
        for k, d in delta.items():
            if k == pay.ov_pda(address):
                continue
            if k in self.vault or (k in self.sources and k != book.source):
                self.flag("a", name, f"{name} on {address} changed another order's or another funder's account {k} by {d}")
            elif k == book.source:
                entered, left = entered + max(-d, 0), left + max(d, 0)
            elif k in (c.fee, c.tip):
                fees += d
                if d < 0 or (k == c.tip and d > pay.TIP_FIRST):
                    self.flag("f", name, f"the fee account or the tip changed by {d}")
            elif d < 0:
                self.flag("a", name, f"{name} took {-d} from {k}")
            else:
                paid += d
        book.funded, book.returned, book.paid, book.fees = book.funded + entered, book.returned + left, book.paid + paid, book.fees + fees
        if now is not None:
            if entered and now.fee != schedule(now.amount, now.fee_bps) or now.fee != pay.order_fee(now.amount, now.fee_bps):
                self.flag("f", name, f"an order of {now.amount} carries a fee of {now.fee}; the schedule says {schedule(now.amount, now.fee_bps)}")
            if entered and entered != now.amount + now.fee - (was.amount + was.fee if was else 0):
                self.flag("f", name, f"{name} took {entered} for an order of {now.amount} and a fee of {now.fee}")
            book.amount, book.fee = now.amount, now.fee
        else:
            del self.live[address]
            book.end = name
        if token is not None:
            self.accepted(token, name, paid)
        return ok

    def accepted(self, token: Token, name: str, paid: int) -> None:
        token.wins.append((self.step, paid))
        if len(token.wins) > 1:
            twice = token.kind == "pay" and all(p > 0 for _, p in token.wins)
            self.flag("b", "double payment" if twice else token.kind,
                      f"a {token.kind} token was accepted twice (steps {[s for s, _ in token.wins]})" + (f": it paid {[p for _, p in token.wins]}" if twice else ""))

    def submit(self, token: Token, fresh: bool = False, name: str | None = None) -> bool:
        ix = token.build(fresh)
        return ix is not None and self.act(name or token.kind, token.address, lambda: self.c.send([ix]), token)

    def issue_token(self, kind: str, account: Pubkey | None, address: Pubkey | None, build, remake=None) -> Token | None:
        if account is None:
            return None
        first = build(False)
        self.tokens.append(Token(kind, account, address, lambda fresh: build(True) if fresh else first, remake=remake))
        return self.tokens[-1]

    # -- the invariants, after every step ---------------------------------------------------------------------------
    def check(self) -> None:
        c, held = self.c, self.snap()
        if sum(held.values()) != self.total:
            self.flag("c", "total", f"all accounts together hold {sum(held.values())}, not {self.total}")
        for b in self.books:
            out, closed = b.paid + b.returned + b.fees, self.live.get(b.address) is not b
            if out > b.funded:
                self.flag("a", "order", f"order {b.address} gave out {out} of {b.funded}")
            if closed and (out != b.funded or (b.end in ("refund",) and (b.paid or b.fees)) or b.fees > b.fee
                           or (b.end in ("pay", "settle", "release") and (b.returned or b.paid != b.amount or b.fees != b.fee))):
                self.flag("a" if out != b.funded else "d", "order", f"order {b.address} ended by {b.end}: {b}")
            if not closed and b.funded - out != held.get(pay.ov_pda(b.address), 0):
                self.flag("a", "order", f"order {b.address} holds {held.get(pay.ov_pda(b.address), 0)}, its book says {b.funded - out}")
        for address in self.vault.values():
            if (c.data(address) is not None) != (address in self.live):
                self.flag("a", "order", f"order {address} is {'open' if c.data(address) else 'gone'} on chain and not in the books")
        x = pay.read_balx(c.data(pay.balx_pda(c.bal)))
        if x.total_spent != self.total_spent or (x.day == self.day and x.day_spent != self.day_spent) or (self.day and x.day != self.day):
            self.flag("e", "balance", f"the Balance counts {x.day_spent} today and {x.total_spent} in all; its orders say {self.day_spent} and {self.total_spent}")
        if (x.day == c.now() // DAY and x.day_spent > x.day_limit) or x.total_spent > x.total_limit:     # an earlier day's count is reset by the next funding
            self.flag("e", "balance", f"the Balance spent {x.day_spent} of {x.day_limit} a day, {x.total_spent} of {x.total_limit} in all")

    # -- the actions ----------------------------------------------------------------------------------------------
    def amount(self, wallet: bool) -> int:
        r = self.rng.random()
        if self.legacy or r < 0.75:             # 0.3.13 took at most 500 an order, where its fee and today's agree
            return self.rng.randrange(5 * USDC, 200 * USDC)
        if r < 0.92 or not wallet:
            return self.rng.randrange(950 * USDC, 1_050 * USDC)
        return self.rng.randrange(49_950 * USDC, 50_050 * USDC)

    def options(self) -> bytes:
        kind = self.rng.choice(["plain", "plain", "plain", "holdback"])
        hold = dict(holdback_bps=self.rng.choice([500, 2500, 5000]), warranty_days=1) if kind == "holdback" else {}
        return pay.opts(reserve_days=self.rng.choice([0, 1]), **hold)

    def fund_wallet(self, key: Pubkey | None = None, repo: int | None = None, n: int | None = None) -> bool:
        funder, tok = self.funders[key or self.rng.choice(list(self.funders))]
        repo, n = repo or self.rng.choice([REPO, REPO + 1, self.repo2]), n or self.rng.randrange(1, 4)
        ix = self.c.fund_wallet_ix(n, self.amount(True), funder, tok, repo=repo, work_s=self.rng.choice([60, 120, 600, 2 * DAY]), options=self.options())
        return self.act("fund_wallet", ix.accounts[1].pubkey, lambda: self.c.send([ix], funder))

    def comment(self, balance: Pubkey | None = None, repo: int | None = None, n: int | None = None) -> Token | None:
        """A maintainer's fund comment on an issue: GitHub signs a fund token, whatever became of the issue's earlier orders."""
        balance = balance or self.rng.choice(list(self.balances))
        owner, repos, _ = self.balances[balance]
        repo, n = repo or self.rng.choice(repos), n or self.rng.randrange(1, 4)
        tok = self.c.fund_token(n, self.amount(False), work=self.rng.choice([60, 120, 600, 2 * DAY]), balance=balance, options=self.options(),
                                repository_id=repo, repository_owner_id=owner)
        build = lambda fresh: self.c.fund_balance_ix(tok, n, balance, repo=repo)  # noqa: E731
        return self.issue_token("fund", tok, build(False).accounts[7].pubkey if tok else None, build)

    def fund_balance(self) -> None:
        first = self.comment()
        if first is not None and self.rng.random() < 0.5:       # two comments on one issue: two tokens for one address
            balance = first.build(False).accounts[3].pubkey
            repo, n = next((r, k) for r in self.balances[balance][1] for k in range(1, 4) if pay.order_pda(pay.scope_of(r, k), balance) == first.address)
            second = self.comment(balance, repo, n)
            if second is not None:
                self.spare.setdefault(second.address, []).append(second)
        if first is not None:
            self.submit(first)

    def relay(self, address: Pubkey | None = None) -> bool:
        """Relays a waiting second fund token (of `address`, or any)."""
        waiting = [a for a in self.spare if self.spare[a] and address in (None, a)]
        return bool(waiting) and self.submit(self.spare[self.rng.choice(waiting)].pop(0))

    def remaker(self, o: pay.Order, address: Pubkey) -> Callable[[], None]:
        """How an order's address gets an order again once the first is gone: the next fund comment's token, or the wallet funding the issue once more."""
        if o.from_balance:
            return lambda: self.relay(address)
        return lambda: self.fund_wallet(o.source, o.repo_id, o.issue)

    def pick(self, *wants) -> tuple[Pubkey, pay.Order] | None:
        """An open order that fits the first of `wants` some order fits, else any."""
        live = [(a, self.c.order(a)) for a in self.live]
        fit = next((f for f in ([x for x in live if want(x[1])] for want in wants) if f), live)
        return self.rng.choice(fit) if fit else None

    def pay(self) -> None:
        c, got = self.c, self.pick(lambda o: o.state == "open" and o.deadline >= self.c.now())
        if got is None:
            return self.fund_balance()
        address, o = got
        r, people = self.rng.random(), self.rng.sample(self.people, 2)
        if r < 0.6:
            payees = [(people[0][0], 10_000, people[0][1])]
        elif r < 0.75:
            payees = [(people[0][0], 10_000, None)]            # no address in the token: paid at the bound wallet, or held
        else:
            cut = self.rng.randrange(1, 10_000)
            payees = [(people[0][0], cut, people[0][1]), (people[1][0], 10_000 - cut, people[1][1])]
        pr = self.rng.randrange(1, 5)
        tok = c.pay_token(address, payees, o, pr=pr)
        build = lambda fresh: c.pay_ix(address, tok, payees, (c.order(address) if fresh else None) or o, pr=pr)  # noqa: E731
        t = self.issue_token("pay", tok, address, build, self.remaker(o, address))
        if t is not None:
            self.submit(t)

    def command(self, kind: str) -> None:
        """A reservation, a cancellation or a revert: each is a token of the order's repository."""
        c = self.c
        want = {"reserve": lambda o: o.state == "open" and o.reserve_days and not o.reserved_by, "cancel": lambda o: o.state == "open" and not o.cancel_at,
                "revert": lambda o: o.state == "warranty"}[kind]
        got = self.pick(want)
        if got is None:
            return
        address, o = got
        if kind == "cancel" and not o.from_balance:            # a wallet's order: the wallet signs, and there is no token
            funder = self.funders[o.source][0]
            self.act("cancel", address, lambda: c.send([pay.cancel_ix(funder.pubkey(), address)], signers=[funder]))
            return
        if kind == "reserve":
            taker = self.rng.choice(self.people)[0]
            tok = c.gh(pay.take_audience(address, taker, 1), repository_id=o.repo_id, actor_id=taker)
            build = lambda fresh: pay.reserve_ix(c.payer.pubkey(), tok, c.key, address)  # noqa: E731
        elif kind == "cancel":
            tok = c.gh(pay.cancel_audience(address), repository_id=o.repo_id, actor_id=MAINT)
            build = lambda fresh: pay.cancel_ix(c.payer.pubkey(), address, tok, c.key)  # noqa: E731
        else:
            tok, hb = c.gh(pay.revert_audience(address, HEAD), repository_id=o.repo_id), pay.read_holdback(c.data(pay.hb_pda(address)))
            if hb is None:
                return

            def build(fresh: bool):
                now = c.order(address) if fresh else None
                return pay.revert_ix(c.payer.pubkey(), tok, c.key, address, now or o, (pay.read_holdback(c.data(pay.hb_pda(address))) if now else None) or hb)
        t = self.issue_token(kind, tok, address, build, self.remaker(o, address))
        if t is not None:
            self.submit(t)

    def settle(self) -> None:
        """The seller's side: the payee an order is held for binds a wallet with a token of his own, and anyone settles."""
        c, got = self.c, self.pick(lambda o: o.state == "held")
        if got is None or got[1].state != "held":
            return
        address, o = got
        wallet = dict(self.people)[o.payee_id]
        if pay.read_bind(c.data(pay.bind_pda(o.payee_id))) is None:
            c.warp(1)
            tok = c.gh(pay.bind_audience(wallet), file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA, event_name="workflow_dispatch",
                       actor_id=o.payee_id, repository_owner_id=o.payee_id, repository=f"user{o.payee_id}/knos-claim", repository_id=70_000_000 + o.payee_id % 1_000_000)
            t = self.issue_token("bind", tok, None, lambda fresh: pay.bind_ix(c.payer.pubkey(), tok, c.key, o.payee_id))
            if t is None or not self.submit(t):
                return
        self.act("settle", address, lambda: c.settle(address, wallet))

    def simple(self, kind: str) -> None:
        c = self.c
        if kind == "top":
            got = self.pick(lambda o: o.state == "open" and o.deadline >= c.now())
            if got is not None:
                address, o = got
                signer = self.balances[o.source][2] if o.from_balance else self.funders[o.source][0]
                add = self.rng.choice([self.rng.randrange(1, 100 * USDC), max(1_000 * USDC - o.amount, 0) + self.rng.randrange(1, 50 * USDC)])
                self.act("top", address, lambda: c.send([pay.top_up_ix(signer.pubkey(), address, o, add)], signer))
        elif kind == "release":
            got = self.pick(lambda o: o.state == "warranty")
            if got is not None and got[1].state == "warranty":
                address, o = got
                self.act("release", address, lambda: c.send([pay.release_ix(c.payer.pubkey(), address, o, pay.read_holdback(c.data(pay.hb_pda(address))))]))
        elif kind == "refund":
            got = self.pick(lambda o: o.state == "open" and o.deadline < c.now())
            if got is not None:
                self.act("refund", got[0], lambda: c.refund(got[0]))
        elif kind == "close":
            used = [t for t in self.tokens if t.wins and c.data(pay.used_pda(c.data(t.account))) is not None]
            if used:
                t = self.rng.choice(used)
                marker = pay.used_pda(c.data(t.account))
                after = pay.read_marker(c.data(marker))[1]
                ok = self.act("close", None, lambda: c.send([pay.close_marker_ix(marker, c.payer.pubkey())]))
                if ok != (c.now() > after):
                    self.flag("b", "marker", f"a marker good until {after} was {'closed' if ok else 'kept'} at {c.now()}")
        elif kind == "limits":                  # the Balance's wallet moves its limits, never below what is spent
            x = pay.read_balx(c.data(pay.balx_pda(c.bal)))
            today = x.day_spent if x.day == c.now() // DAY else 0
            self.limits = [today + self.rng.randrange(1, 3_000 * USDC), x.total_spent + self.rng.randrange(1, 20_000 * USDC)]
            assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, *self.limits, repos=[REPO, REPO + 1])], c.owner), c.err
            self.trace.append(f"{self.step} limits {self.limits}")

    def warp(self, seconds: int | None = None) -> None:
        c, seconds = self.c, seconds or self.rng.choice(WARPS)
        if c.now() + seconds - self.refreshed > 20 * DAY:       # GitHub's key stays good, as a relay keeps it
            assert c.refresh(oidc.GITHUB, c.github, c.attest(oidc.GITHUB, c.github)), c.err
            self.refreshed = c.now()
        c.warp(seconds)
        self.trace.append(f"{self.step} warp {seconds}")

    def replay(self) -> None:
        """Any token ever signed, sent again: as it was first built, or built anew for the accounts as they stand,
        after its order's address was given an order again when it has none."""
        if not self.tokens:
            return
        recent = self.tokens[-8:]
        t = self.rng.choice(recent if self.rng.random() < 0.7 else self.tokens)
        fresh = self.rng.random() < 0.7
        if fresh and t.remake is not None and t.address not in self.live and self.rng.random() < 0.8:
            t.remake()
        self.submit(t, fresh, name=f"replay {t.kind}{' fresh' if fresh else ''}")

    def run(self, steps: int, until: Callable[[], bool] | None = None) -> "Machine":
        do = {"fund_wallet": self.fund_wallet, "fund_balance": self.fund_balance, "comment": lambda: self.spare_comment(), "relay": self.relay, "pay": self.pay,
              "settle": self.settle, "warp": self.warp, "replay": self.replay, **{k: (lambda k=k: self.command(k)) for k in ("reserve", "cancel", "revert")},
              **{k: (lambda k=k: self.simple(k)) for k in ("top", "release", "refund", "close", "limits")}}
        for self.step in range(1, steps + 1):
            do[self.rng.choice(ACTIONS)]()
            self.check()
            if until is not None and until():
                return self
        self.finish()
        return self

    def spare_comment(self) -> None:
        """A second fund comment for an issue that has, or had, an order: its token waits for a later step."""
        seen = [b for b in self.books if b.source in (pay.baltok_pda(self.c.bal), pay.baltok_pda(self.bal2))]
        if seen:
            b = self.rng.choice(seen)
            balance = next(k for k in self.balances if pay.baltok_pda(k) == b.source)
            repo, n = next((r, k) for r in self.balances[balance][1] for k in range(1, 4) if pay.order_pda(pay.scope_of(r, k), balance) == b.address)
            t = self.comment(balance, repo, n)
            if t is not None:
                self.spare.setdefault(t.address, []).append(t)

    def finish(self) -> None:
        """Time runs out: past every deadline, warranty and hold, each order left ends by the one instruction that still takes it."""
        c = self.c
        self.step += 1
        c.warp(pay.HOLD + 10 * DAY)
        for address in list(self.live):
            o = c.order(address)
            if o.state == "warranty":
                self.act("release", address, lambda: c.send([pay.release_ix(c.payer.pubkey(), address, o, pay.read_holdback(c.data(pay.hb_pda(address))))]))
            else:
                self.act("refund", address, lambda: c.refund(address))
        self.check()
        if self.live:
            self.flag("a", "order", f"{len(self.live)} orders did not end once every time had passed")


def old_build(tmp_path: Path) -> str:
    """The test build of knos_pay as 0.3.13 committed it."""
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(["git", "-C", str(root), "show", f"{OLD_COMMIT}:{OLD_BUILD}"], capture_output=True)
    if r.returncode != 0 or len(r.stdout) < 100_000:
        pytest.skip(f"this checkout does not have commit {OLD_COMMIT} (a shallow clone?): the 0.3.13 build cannot be read")
    (tmp_path / "knos_pay_v2_0313.so").write_bytes(r.stdout)
    return str(tmp_path / "knos_pay_v2_0313.so")


@pytest.mark.parametrize("seed", SEEDS)
def test_a_random_machine_of_orders_tokens_and_replays_keeps_every_invariant(seed):
    m = Machine(seed).run(STEPS)
    TOTALS["steps"], TOTALS["violations"] = TOTALS["steps"] + m.step, TOTALS["violations"] + len(m.bad)
    assert m.bad == [] and not m.live
    assert len(m.books) >= 3 and len(m.tokens) >= 5, (len(m.books), len(m.tokens))       # it did fund and sign: the run was not all refusals
    print(f"machine seed {seed}: {m.step} steps, {len(m.books)} orders, {len(m.tokens)} tokens, {sum(len(t.wins) for t in m.tokens)} accepted, 0 violations")


def test_the_machine_finds_the_double_payment_of_the_0_3_13_build_within_its_default_budget(tmp_path):
    build, found = old_build(tmp_path), []
    for seed in [3140 + k for k in range(DEFAULT_SEEDS)]:
        m = Machine(seed, build=build, strict=False)
        m.run(DEFAULT_STEPS, until=lambda: any(v.kind == "double payment" for v in m.bad))
        found += [v for v in m.bad if v.kind == "double payment"]
        if found:
            break
    assert found, "the machine no longer finds a pay token that pays twice on the 0.3.13 build: it has lost its teeth"
    assert found[0].letter == "b" and "it paid" in found[0].text
    print("0.3.13 build:", found[0].text)


def test_the_machine_reports_what_it_ran():
    """Last in the file: one line for a scaled-up run (`-s` shows it)."""
    print(f"machine total: {TOTALS['steps']} steps over {len(SEEDS)} seeds, {TOTALS['violations']} violations")
    assert TOTALS["violations"] == 0
