"""The six guarantees of docs/reference/INVARIANTS.md that had no test of their own (knos_pay 2.2 in LiteSVM):

  4. a pay or fund token of one deployment is refused by the same build at other program ids;
  5. every ordering of two and of three of pay, cancel, expiry, refund, settle, release and revert, from an order that
     pays at once, one that is held and one with a holdback, ends the order exactly once, as a small model says
     (after the orderings, time runs out and the one instruction that still takes each order is sent);
  6. RefundOrder on the committed build with real-money rules, sent by a stranger, with funding paused;
  7. two relayers sending one token in one slot: exactly one transaction is accepted, whichever comes first;
  8. a top-up pays the difference between the two schedule values, across the floor and at every size (one rate, no tiers);
  9. a random walk over a Balance's day and total counters: they equal what was funded and never pass a limit."""
from __future__ import annotations

import itertools
import random

import pytest

pytest.importorskip("solders.litesvm")

from solders.compute_budget import set_compute_unit_limit  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.message import MessageV0  # noqa: E402
from solders.transaction import VersionedTransaction  # noqa: E402

from _order import DAY, HEAD, MAINT, OWNER, REPO, TERMS, TH, USDC, OrderChain, code, issue, transfer, user  # noqa: E402
from _pay2 import FIX, GUARDIAN, WF_REPO, WF_SHA, github_claims  # noqa: E402
from _settle import sign_jwt, signing_key  # noqa: E402

from knos.settle.v2 import oidc, pay  # noqa: E402

OTHER = Keypair.from_seed(bytes([41]) * 32).pubkey()        # where a second deployment of the same build lives in the first test


def schedule(amount: int, bps: int = 30) -> int:
    """The fee schedule, written out here and not taken from the client: `bps` of the amount (0.30%, or a Plan's rate), at least 0.05. One rate."""
    return max(amount * bps // 10_000, 50_000)


def test_a_pay_or_fund_token_of_one_deployment_is_refused_by_the_same_build_at_other_program_ids():
    c = OrderChain()
    c.svm.add_program_from_file(OTHER, str(FIX / "knos_pay_v2_test.so"))       # the same bytes, another id: every address it derives differs
    me, n, (wallet, dest) = c.payer.pubkey(), issue(), c.wallet(c.usdc)
    payees = [(user(), 10_000, wallet.pubkey())]
    # the same wallet funds the same issue at both: two orders, two addresses
    here = c.fund_wallet(n, 20 * USDC)
    ix = pay.fund_order_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, 20 * USDC, WF_REPO, WF_SHA, TERMS, program=OTHER)
    there = ix.accounts[1].pubkey
    assert c.send([ix], c.funder) and there != here, c.err
    o_here, o_there = c.order(here), pay.read_order(c.data(there))
    assert o_there is not None and o_there.address(OTHER) == there and c.balance(pay.ov_pda(there, OTHER)) == 20 * USDC + schedule(20 * USDC)

    def pay_there(tok, order=there, o=o_there):
        return c.send([pay.pay_order_ix(me, tok, c.key, order, o, c.wallets(payees), program=OTHER, used=pay.used_pda(c.data(tok), OTHER))], mark=False)
    # a pay token names its order's address, so it names its deployment: the other one's order is not the one it names
    mine = c.pay_token(here, payees)
    assert not pay_there(mine) and code(c) == 87
    assert not pay_there(mine, here, o_here)                                   # nor does the other deployment own the order it does name
    assert c.balance(dest) == 0 and c.balance(pay.ov_pda(there, OTHER)) == 20 * USDC + schedule(20 * USDC)
    # and the reverse: a token for the other deployment's order pays nothing here, and does pay there
    theirs = c.pay_token(there, payees, o_there)
    assert not c.send([c.pay_ix(here, theirs, payees)]) and code(c) == 87 and c.balance(dest) == 0
    assert pay_there(theirs) and c.balance(dest) == 20 * USDC and c.data(there) is None, c.err
    assert c.send([c.pay_ix(here, mine, payees)]) and c.balance(dest) == 40 * USDC, c.err
    # a fund token names a Balance's address: the same wallet's Balance at the other deployment is another address
    assert c.send([pay.open_balance_ix(c.owner.pubkey(), OWNER, c.usdc, spenders=[MAINT], program=OTHER)], c.owner), c.err
    bal = pay.balance_pda(OWNER, c.owner.pubkey(), c.usdc, OTHER)
    transfer(c, c.owner_tok, pay.baltok_pda(bal, OTHER), 100 * USDC, c.owner)
    assert bal != c.bal

    def fund_there(tok, issue_n):
        return c.send([pay.fund_order_balance_ix(me, tok, c.key, bal, c.usdc, OWNER, REPO, issue_n, TERMS, pay.used_pda(c.data(tok), OTHER), program=OTHER)], mark=False)
    k = issue()
    mine = c.fund_token(k, 20 * USDC)                                          # names this deployment's Balance
    assert not fund_there(mine, k) and code(c) == 87 and c.balance(pay.baltok_pda(bal, OTHER)) == 100 * USDC
    theirs = c.fund_token(k, 20 * USDC, balance=bal)
    assert not c.send([c.fund_balance_ix(theirs, k)]) and code(c) == 87
    assert fund_there(theirs, k) and c.balance(pay.baltok_pda(bal, OTHER)) == 80 * USDC - schedule(20 * USDC), c.err
    assert c.send([c.fund_balance_ix(mine, k)]), c.err


# == 5. every ordering of the instructions that can end an order ======================================================
MOVES = ("pay", "cancel", "expiry", "refund", "settle", "release", "revert")
AMOUNT, FEE, HOLDBACK = 20 * USDC, schedule(20 * USDC), 2500


class Model:
    """What each move does to an order, in a few lines: the state, whether its clock has run out, and how it ended."""
    def __init__(self, kind: str):
        self.kind, self.state, self.late, self.cancelled, self.end = kind, "open", False, False, None

    def move(self, m: str) -> bool:
        """Whether the chain should accept `m` now."""
        if self.end is not None:
            return m == "expiry"
        if m == "expiry":
            self.late = True
        elif self.state == "open" and m == "pay" and not self.late:
            self.state, self.end = {"plain": ("open", "pay"), "held": ("held", None), "holdback": ("warranty", None)}[self.kind]
        elif self.state == "open" and m == "cancel" and not self.late and not self.cancelled:
            self.cancelled = True
        elif (self.state, m) in (("open", "refund"), ("held", "refund"), ("warranty", "release")) and self.late:
            self.end = m
        elif (self.state, m) in (("held", "settle"), ("warranty", "revert")) and not self.late:
            self.end = m
        else:
            return False
        return True


class Clock:
    """Moves a chain's time and keeps GitHub's key verifying, as a relay does: it is refreshed before it is 25 days old."""
    def __init__(self, c: OrderChain):
        self.c, self.at = c, c.now()

    def warp(self, seconds: int) -> None:
        while seconds > 0:
            hop = min(seconds, 20 * DAY)
            if self.c.now() - self.at + hop > 25 * DAY:
                assert self.c.refresh(oidc.GITHUB, self.c.github, self.c.attest(oidc.GITHUB, self.c.github)), self.c.err
                self.at = self.c.now()
            self.c.warp(hop)
            seconds -= hop


class Run:
    """One order and one sequence of moves on it."""
    def __init__(self, c: OrderChain, clock: Clock, kind: str, moves: tuple):
        self.c, self.clock, self.kind, self.moves, self.model = c, clock, kind, moves, Model(kind)
        self.who, self.wallet = user(), Keypair().pubkey()
        self.order = c.fund_wallet(amount=AMOUNT, work_s=600, options=pay.opts(holdback_bps=HOLDBACK, warranty_days=1) if kind == "holdback" else None)
        self.o = c.order(self.order)
        self.payees = [(self.who, 10_000, None if kind == "held" else self.wallet)]
        self.ends, self.returned, self.fees = [], 0, 0

    def send(self, m: str) -> bool:
        c, order = self.c, self.order
        o, hb = c.order(order) or self.o, pay.read_holdback(c.data(pay.hb_pda(order))) or pay.Holdback(c.payer.pubkey(), 0, [])
        self.o = o
        if m in ("pay", "revert") and len(self.moves) == 3 and c.data(order) is None:
            return False        # no order is left to name: the orderings of two do send a token at a closed order, these do not sign one
        if m == "pay":
            return c.send([c.pay_ix(order, c.pay_token(order, self.payees, o), self.payees, o)])
        if m == "cancel":
            return c.send([pay.cancel_ix(c.funder.pubkey(), order)], signers=[c.funder])
        if m == "refund":
            return c.send([pay.refund_order_ix(c.payer.pubkey(), order, o)])
        if m == "settle":
            if c.data(order) is not None and o.state == "held" and c.now() <= o.hold_until and pay.read_bind(c.data(pay.bind_pda(self.who))) is None:
                assert c.bind(self.who, self.wallet), c.err                       # the seller's own step: he names his wallet
            return c.send([pay.settle_order_ix(c.payer.pubkey(), order, o, self.wallet)])
        if m == "release":
            return c.send([pay.release_ix(c.payer.pubkey(), order, o, hb)])
        return c.send([pay.revert_ix(c.payer.pubkey(), c.gh(pay.revert_audience(order, HEAD), repository_id=REPO), c.key, order, o, hb)])

    def step(self, m: str) -> None:
        """One move: the chain accepts it exactly when the model does, a refusal moves nothing, and a closed order stays closed."""
        c = self.c
        watch = (c.funder_tok, c.fee, c.tip)
        want, before, was = self.model.move(m), [c.balance(a) for a in watch], c.data(self.order) is not None
        got = self.send(m)
        after = [c.balance(a) for a in watch]
        assert got == want, (self.kind, self.moves, m, c.err)
        assert got or after == before, (self.kind, self.moves, m)
        self.returned, self.fees = self.returned + after[0] - before[0], self.fees + after[1] - before[1] + after[2] - before[2]
        if was and c.data(self.order) is None:
            self.ends.append(m)
        assert (c.data(self.order) is None) == (self.model.end is not None), (self.kind, self.moves, m)

    def play(self):
        """A generator: it stops once, before the 180 days of a held order's hold, so that all such runs share one wait."""
        for m in self.moves:
            if m != "expiry":
                self.step(m)
                continue
            o = self.c.order(self.order)
            if o is not None and o.state == "held":
                yield
            elif o is not None:
                self.clock.warp((o.deadline if o.state == "open" else o.hold_until) - self.c.now() + 1)
            assert self.model.move(m)

    def finish(self) -> None:
        """After every clock has run out: the one instruction that still takes the order ends it, and the money adds up."""
        if self.model.end is None:
            self.model.late = True
            self.step("release" if self.model.state == "warranty" else "refund")
        paid = self.c.balance(pay.ata(self.wallet, self.c.usdc))
        assert len(self.ends) == 1 and self.ends[0] == self.model.end, (self.kind, self.moves, self.ends)
        assert paid + self.returned + self.fees == AMOUNT + FEE, (self.kind, self.moves, paid, self.returned, self.fees)
        want = {"refund": (0, AMOUNT + FEE, 0), "revert": (AMOUNT - AMOUNT * HOLDBACK // 10_000, None, None)}.get(self.ends[0], (AMOUNT, 0, FEE))
        assert all(w is None or w == g for w, g in zip(want, (paid, self.returned, self.fees))), (self.kind, self.moves, paid, self.returned, self.fees)


@pytest.mark.parametrize("kind", ["plain", "held", "holdback"])
def test_every_ordering_of_two_and_of_three_of_pay_cancel_expiry_refund_settle_release_and_revert_ends_an_order_exactly_once(kind):
    c = OrderChain()
    clock = Clock(c)
    orderings = [*itertools.permutations(MOVES, 2), *itertools.permutations(MOVES, 3)]
    assert len(orderings) == 42 + 210
    runs, waiting = [], []
    for moves in orderings:
        r = Run(c, clock, kind, moves)
        runs.append(r)
        g = r.play()
        if next(g, "done") != "done":
            waiting.append(g)                   # a held order before its expiry: it waits for the others
    clock.warp(pay.HOLD + 1)
    for g in waiting:
        assert next(g, "done") == "done"
    clock.warp(pay.HOLD + 10 * DAY)             # past every deadline, warranty and hold
    for r in runs:
        r.finish()
    ends = {r.ends[0] for r in runs}
    assert ends == {"plain": {"pay", "refund"}, "held": {"settle", "refund"}, "holdback": {"release", "revert", "refund"}}[kind], ends
    assert len(waiting) == (15 if kind == "held" else 0)        # pay, then expiry while the order is held: with nothing, or a refused move, around them


# == 6. a refund on the committed build with real-money rules =========================================================
def test_refund_order_on_the_committed_real_money_build_needs_no_token_no_funder_and_no_open_funding():
    """tests/fixtures/knos_pay_v2_nodevnet.so: the build without the devnet feature (no faucet, real-money rules). It
    is the nearest committed build to the deployed one: it trusts the test keys, and no knos_pay build with the real
    keys, and no copy of the deployed bytes, is in the repository."""
    c = OrderChain(pay_build="knos_pay_v2_nodevnet.so")
    stranger = c.fund(1)                         # a key with SOL for a fee and nothing else
    before = c.balance(c.funder_tok)
    order = c.fund_wallet(amount=300 * USDC, work_s=3600)
    of_balance = c.fund_balance(amount=40 * USDC, work=3600)
    in_balance = c.balance(pay.baltok_pda(c.bal))
    assert before - c.balance(c.funder_tok) == 300 * USDC + schedule(300 * USDC)
    refund = lambda a: c.send([pay.refund_order_ix(stranger.pubkey(), a, c.order(a))], stranger)  # noqa: E731
    assert not refund(order) and code(c) == 83 and not refund(of_balance) and code(c) == 83          # not before the deadline
    c.warp(3601)
    assert c.send([pay.pause_ix(GUARDIAN.pubkey(), c.payer.pubkey(), 3 * DAY)], signers=[GUARDIAN]), c.err
    assert not c.send([c.fund_wallet_ix(issue())], c.funder) and code(c) == 96                         # funding is paused
    # the destination is fixed: not the stranger's own account, not another wallet's
    _, elsewhere = c.wallet(c.usdc)
    assert not c.send([pay.refund_order_ix(stranger.pubkey(), order, c.order(order), elsewhere)], stranger) and code(c) == 88
    was = c.order(order)
    assert refund(order) and refund(of_balance), c.err
    assert c.balance(c.funder_tok) == before and c.balance(pay.baltok_pda(c.bal)) == in_balance + 40 * USDC + schedule(40 * USDC)
    assert c.order(order) is None and c.data(pay.ov_pda(order)) is None and c.balance(c.fee) == 0 and c.balance(c.tip) == 0
    assert not c.send([pay.refund_order_ix(stranger.pubkey(), order, was)], stranger) and c.balance(c.funder_tok) == before        # once


# == 7. two relayers, one token, one slot =============================================================================
def one_block(c: OrderChain, *sends) -> list[bool]:
    """Every (instruction, relayer) as a transaction on one blockhash, all sent before the chain moves on: one slot."""
    blockhash, slot = c.svm.latest_blockhash(), c.svm.get_clock().slot
    txs = [VersionedTransaction(MessageV0.try_compile(r.pubkey(), [set_compute_unit_limit(1_400_000), c.marked(ix)], [], blockhash), [r]) for ix, r in sends]
    one_slot = getattr(c.svm, "_inner", c.svm)      # under the harness's wrapper, which gives every transaction a slot of its own
    out = ["Failed" not in type(one_slot.send_transaction(tx)).__name__ for tx in txs]
    assert c.svm.get_clock().slot == slot and c.svm.latest_blockhash() == blockhash
    c.svm.expire_blockhash()
    return out


def test_two_relayers_send_one_token_in_one_slot_and_exactly_one_is_accepted():
    c = OrderChain()
    first, second = c.payer, c.fund()
    tips = {first.pubkey(): c.tip, second.pubkey(): c.token_account(second.pubkey(), c.usdc)}

    def token(aud: str, **claims) -> tuple:
        """One JWT, verified by each relayer into a token account of its own, as two relays of one workflow run do."""
        now = c.now()
        jwt = sign_jwt(signing_key(), github_claims(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"race{now}{aud[-6:]}", job_workflow_sha=WF_SHA, **claims))
        a, b = (c.verify(jwt, oidc.GITHUB, c.github, r) for r in (first, second))
        assert a is not None and b is not None and a != b and pay.used_pda(c.data(a)) == pay.used_pda(c.data(b))
        return a, b

    for winner, loser in ((first, second), (second, first)):
        for options in (None, pay.opts(holdback_bps=2500, warranty_days=1)):     # paid and closed; paid in part and still there
            # a fund token: both relayers fund from the Balance
            n, in_balance = issue(), c.balance(pay.baltok_pda(c.bal))
            c.warp(1)
            toks = token(pay.order_fund_audience(n, 50 * USDC, pay.MERGE, TH, c.bal, 14 * DAY, 0, options), event_name="issue_comment", actor_id=MAINT,
                         repository_id=REPO, repository_owner_id=OWNER, job_workflow_ref=f"{WF_REPO}/.github/workflows/fund.yml@refs/tags/v0.3.12")
            tok = dict(zip((first.pubkey(), second.pubkey()), toks))
            fund = lambda r: (pay.fund_order_balance_ix(r.pubkey(), tok[r.pubkey()], c.key, c.bal, c.usdc, OWNER, REPO, n, TERMS, c.data(tok[r.pubkey()])), r)  # noqa: E731
            order = fund(first)[0].accounts[7].pubkey
            assert one_block(c, fund(winner), fund(loser)) == [True, False]
            assert in_balance - c.balance(pay.baltok_pda(c.bal)) == 50 * USDC + schedule(50 * USDC) == c.held(order)
            # a pay token: both relayers pay the order
            o, (wallet, dest) = c.order(order), c.wallet(c.usdc)
            payees = [(user(), 10_000, wallet.pubkey())]
            toks = token(pay.order_pay_audience(order, HEAD, o.terms, o.mode, 7, payees), repository_id=REPO,
                         job_workflow_ref=f"{WF_REPO}/.github/workflows/prove.yml@refs/tags/v0.3.12")
            tok = dict(zip((first.pubkey(), second.pubkey()), toks))
            pays = lambda r: (pay.pay_order_ix(r.pubkey(), tok[r.pubkey()], c.key, order, o, c.wallets(payees), pr=7), r)  # noqa: E731
            before = {k: c.balance(t) for k, t in tips.items()}
            assert one_block(c, pays(winner), pays(loser)) == [True, False]
            assert c.balance(dest) == (50 * USDC if options is None else 50 * USDC * 3 // 4)
            assert c.balance(tips[winner.pubkey()]) - before[winner.pubkey()] == pay.TIP and c.balance(tips[loser.pubkey()]) == before[loser.pubkey()]
            assert (c.order(order) is None) == (options is None)
            # and the loser's transaction is refused later too, in a slot of its own
            assert not c.send([pays(loser)[0]], loser) and c.balance(dest) == (50 * USDC if options is None else 50 * USDC * 3 // 4)


# == 8. a top-up, across the floor and at every size =================================================================
@pytest.fixture(scope="module")
def chain():
    return OrderChain()


@pytest.mark.parametrize("start,add", [(5, 11), (16, 1), (16, 4), (900, 200), (999, 1), (5_000, 95_000), (400, 99_600)])
def test_a_top_up_pays_the_difference_between_the_two_schedule_values_at_every_size(chain, start, add):
    c = chain
    # the floor holds to 16.666666; then 0.30% of the whole amount, with no tier's edge anywhere
    assert (schedule(5 * USDC), schedule(16 * USDC), schedule(17 * USDC), schedule(1_100 * USDC), schedule(100_000 * USDC)) == (50_000, 50_000, 51_000, 3_300_000, 300 * USDC)
    before = c.balance(c.funder_tok)
    order = c.fund_wallet(amount=start * USDC)
    assert before - c.balance(c.funder_tok) == start * USDC + schedule(start * USDC)
    assert c.send([pay.top_up_ix(c.funder.pubkey(), order, c.order(order), add * USDC)], c.funder), c.err
    o, total = c.order(order), (start + add) * USDC
    # the funder has paid, in all, what one funding of the new amount costs
    assert (o.amount, o.fee) == (total, schedule(total)) and before - c.balance(c.funder_tok) == total + schedule(total) == c.held(order)
    assert schedule(total) == pay.order_fee(total)
    # and the whole of it is paid out: the amount to the payee, the fee to FEE_OWNER and the relayer
    wallet, fees = Keypair().pubkey(), c.balance(c.fee) + c.balance(c.tip)
    assert c.pay(order, [(user(), 10_000, wallet)]), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == total and c.balance(c.fee) + c.balance(c.tip) - fees == schedule(total)


def test_a_top_up_of_a_balances_order_keeps_the_plans_rate(chain):
    c, owner = chain, user()
    w, wtok = c.wallet(c.usdc, 5_000 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), owner, c.usdc, spenders=[MAINT])], w), c.err
    bal = pay.balance_pda(owner, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(bal), 5_000 * USDC, w)
    assert c.set_plan(owner, 10, c.now() + 10 * DAY), c.err
    order = c.fund_balance(amount=900 * USDC, balance=bal, repository_owner_id=owner)
    assert c.order(order).fee == 900_000 == schedule(900 * USDC, 10)
    assert c.send([pay.top_up_ix(w.pubkey(), order, c.order(order), 200 * USDC)], w), c.err
    o = c.order(order)
    assert (o.amount, o.fee, o.fee_bps) == (1_100 * USDC, 1_100_000, 10) and o.fee == schedule(1_100 * USDC, 10)
    assert c.balance(pay.baltok_pda(bal)) == 5_000 * USDC - 1_100 * USDC - 1_100_000


# == 9. a Balance's counters ==========================================================================================
@pytest.mark.parametrize("seed", [9, 99])
def test_a_random_walk_over_a_balances_day_and_total_counters_never_passes_a_limit(seed):
    c, rng, owner = OrderChain(), random.Random(seed), user()
    clock = Clock(c)
    w, wtok = c.wallet(c.usdc, 50_000 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), owner, c.usdc, spenders=[MAINT])], w), c.err
    bal = pay.balance_pda(owner, w.pubkey(), c.usdc)
    baltok = pay.baltok_pda(bal)
    transfer(c, wtok, baltok, 3_000 * USDC, w)
    limits = [300 * USDC, 1_500 * USDC]
    set_limits = lambda: c.send([pay.set_balance_x_ix(w.pubkey(), bal, *limits)], w) or pytest.fail(c.err)  # noqa: E731
    set_limits()
    day, today, total, orders, done = c.now() // DAY, 0, 0, [], dict.fromkeys(["funded", "day", "total", "empty", "refunded", "topped", "new day"], 0)
    for _ in range(70):
        kind = rng.choice(["fund"] * 6 + ["refund", "refund", "top", "warp", "warp", "day", "limits", "feed"])
        if kind == "fund":
            amount = rng.choice([rng.randrange(5 * USDC, 150 * USDC), rng.randrange(5 * USDC, 400 * USDC)])
            n, cost = issue(), amount + schedule(amount)
            tok = c.fund_token(n, amount, work=rng.choice([60, 3600, 2 * DAY]), balance=bal, repository_owner_id=owner)
            if c.now() // DAY != day:
                day, today, done["new day"] = c.now() // DAY, 0, done["new day"] + 1
            ix, held = c.fund_balance_ix(tok, n, bal), c.balance(baltok)
            ok = c.send([ix])
            # the model: refused whole when the day's or the total limit would be passed, or the Balance does not hold it
            over = {k for k, hit in (("day", today + cost > limits[0]), ("total", total + cost > limits[1]), ("empty", cost > held)) if hit}
            assert ok == (not over), (kind, amount, today, total, limits, c.err)
            if ok:
                today, total, done["funded"] = today + cost, total + cost, done["funded"] + 1
                orders.append(ix.accounts[7].pubkey)
            else:
                assert code(c) in {100 if over - {"empty"} else 94, 94 if "empty" in over else 100}, (over, c.err)
                for k in over:
                    done[k] += 1
        elif kind == "refund" and orders:       # money comes back to the Balance; what was spent stays spent
            order = orders.pop(rng.randrange(len(orders)))
            o, held = c.order(order), c.balance(baltok)
            clock.warp(max(o.deadline - c.now() + 1, 0))
            assert c.refund(order) and c.balance(baltok) == held + o.amount + o.fee, c.err
            done["refunded"] += 1
        elif kind == "top" and orders:          # the wallet's own top-up is not spending by comment: no counter moves
            order = rng.choice(orders)
            done["topped"] += c.send([pay.top_up_ix(w.pubkey(), order, c.order(order), rng.randrange(1, 20 * USDC))], w)
        elif kind in ("warp", "day"):
            clock.warp(rng.choice([600, 7_200]) if kind == "warp" else DAY)
        elif kind == "limits":                  # the wallet moves its limits, never below what is spent
            limits = [(today if c.now() // DAY == day else 0) + rng.randrange(1, 400 * USDC), total + rng.randrange(1, 1_500 * USDC)]
            set_limits()
        elif kind == "feed":
            transfer(c, wtok, baltok, rng.randrange(1, 500 * USDC), w)
        x = pay.read_balx(c.data(pay.balx_pda(bal)))
        assert (x.day_limit, x.total_limit) == tuple(limits) and x.total_spent == total <= x.total_limit
        assert x.day != day or x.day_spent == today
        assert x.day != c.now() // DAY or x.day_spent <= x.day_limit
    assert all(done[k] for k in ("funded", "day", "total", "refunded", "new day")), done


# == the list a program reads ==========================================================================================
def test_invariants_json_names_nine_invariants_and_only_tests_and_instructions_that_exist():
    import json
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    doc, page = json.loads((root / "docs" / "invariants.json").read_text(encoding="utf-8")), (root / "docs" / "reference" / "INVARIANTS.md").read_text(encoding="utf-8")
    assert [i["id"] for i in doc["invariants"]] == list(range(1, 10))
    lib, proofs = (root / doc["program"] / "src" / "lib.rs").read_text(encoding="utf-8"), (root / doc["kani_file"]).read_text(encoding="utf-8")
    for i in doc["invariants"]:
        assert f"### {i['id']}. {i['invariant']}" in page and i["enforced_by"] and i["tests"], i["id"]
        for t in i["tests"]:
            source = (root / t["file"]).read_text(encoding="utf-8")
            assert t["test"] is None or re.search(rf"^def {t['test']}\(", source, re.M), t
        for name in i["enforced_by"]:
            assert re.search(rf"^//!\s+\d+ {name.split()[-1]}\b", lib if "knos_meter" not in name else (root / "programs-v2/knos_meter/src/lib.rs").read_text(encoding="utf-8"), re.M), name
        assert all(f"fn {h}()" in proofs for h in i["kani"]), i["id"]
