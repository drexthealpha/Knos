#!/usr/bin/env python3
"""Writes programs-v2/testdata/adv_*.json: the scenarios programs-v2/handlers/tests/adversarial.rs replays.

The same recorder as scripts/rust_test_vectors.py (every call that reaches LiteSVM is written down, each transaction
as its signed bytes with what the program answered), over scenarios an opponent would try: accounts closed and made
again at the same address, the second before, at and after every time limit, a payment and a refund sent together,
one token sent twice, one judge alone where an order asks for two or three, one owner behind two judges, a marker
of the order that was at an address before, a token shown after a deadline it was issued before, and orders and
markers as knos_pay 2.1 wrote them.

    python scripts/adversarial_vectors.py            # write the files
    python scripts/adversarial_vectors.py --check    # fail if a committed file differs from what this would write

`adv_quorum_same_account` and `adv_quorum_same_second` recorded two defects of knos_pay 2.1 (one account counted as
two judges; a judge's marker counted for the order funded next at its address). 2.2 fixed both, and the Rust tests
that replay them are ordinary tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src"), str(ROOT / "tests")]

import rust_test_vectors as rv  # noqa: E402  (puts the recorder under the harnesses)

import _meter  # noqa: E402
import _order  # noqa: E402
import test_order_terms as terms  # noqa: E402
from _order import HEAD, OWNER, REPO, USDC  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from knos.settle.v2 import meter, order_auto, pay  # noqa: E402

E_STATE, E_TOKEN, E_AUD, E_REPLAY, E_ORDER = 83, 84, 87, 91, 101
HOUR = 3600
Q2 = pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(2))
JUDGE_REPO = 31_313_131
FIRM = 9_000            # owns the judge repository when the buyer does not
MAINT = _order.MAINT


def _chain(r: rv.Recorder) -> "_order.OrderChain":
    c = _order.OrderChain()
    r.name_it(fee=c.fee, funder_tok=c.funder_tok, relayer_tok=c.tip)
    return c


def _payee(c, r: rv.Recorder):
    """A payee with a wallet and a token account that exists, so every tip is the smaller one."""
    wallet, dest = c.wallet(c.usdc)
    r.name_it(dest=dest)
    return [(_order.user(), 10_000, wallet.pubkey())]


def _fund(c, r: rv.Recorder, name: str, n: int | None = None, **kw):
    order = c.fund_wallet(n, **kw)
    r.name_it(**{name: order, f"{name}_tok": pay.ov_pda(order)})
    return order


def _send(c, r: rv.Recorder, label: str, ixs, want: int | None = None, **kw) -> None:
    """Sends one transaction under this label; `want`: the custom error it must be refused with, None: accepted."""
    r.label(label)
    ok = c.send(ixs, **kw)
    assert ok is (want is None) and (ok or _order.code(c) == want), f"{r.name} {label}: {c.err}"


def _money(c, r: rv.Recorder, label: str) -> None:
    r.check(c.svm, label, tokens=sorted(n for n in r.names if n.endswith("_tok") or n in ("fee", "dest")))


# == 1. accounts closed and made again at the same address ================================================================
def adv_reopen() -> rv.Recorder:
    """An order is paid and its address funded again: the token's marker cannot be closed early, the old token is
    refused while the marker stands and after it was closed. An order is refunded and its address funded again: a
    token signed for the first order and never used does not pay the second; a new one pays it once."""
    r = rv.scenario("adv_reopen")
    c = _chain(r)
    payees = _payee(c, r)
    n = _order.issue()
    order = _fund(c, r, "paid", n)
    c.warp(5)
    old = c.pay_token(order, payees)
    o1 = c.order(order)
    first = c.marked(c.pay_ix(order, old, payees))
    used = first.accounts[13].pubkey
    r.name_it(used=used)
    _send(c, r, "pay", [first])
    close = pay.close_marker_ix(used, c.payer.pubkey(), order)
    _send(c, r, "close_marker_early", [close], E_STATE)
    assert c.fund_wallet(n) == order
    _send(c, r, "old_token_while_its_marker_stands", [c.pay_ix(order, old, payees, o1)], E_REPLAY)
    after = int.from_bytes(c.data(used)[pay_U_AFTER():pay_U_AFTER() + 8], "little", signed=True)
    c.warp(after - c.now())
    _send(c, r, "close_marker_at_its_time", [close], E_STATE)
    c.warp(1)
    _send(c, r, "close_marker", [close])
    assert c.data(used) is None and c.order(order).paid == 0
    r.label("old_token_after_its_marker_closed")
    assert not c.send([c.pay_ix(order, old, payees, o1)]), "a token paid again once its marker was closed"
    _money(c, r, "reopened_after_pay")
    # refunded, then funded again
    n = _order.issue()
    order = _fund(c, r, "refunded", n, work_s=HOUR)
    c.warp(HOUR - 100)
    unused = c.pay_token(order, payees)
    o1 = c.order(order)
    c.warp(101)
    _send(c, r, "refund", [pay.refund_order_ix(c.payer.pubkey(), order, o1)])
    assert c.fund_wallet(n, work_s=HOUR) == order
    r.label("unused_token_of_the_refunded_order")
    assert not c.send([c.pay_ix(order, unused, payees, o1)]), "a token of the refunded order paid the next one"
    _money(c, r, "reopened_after_refund")
    c.warp(1)
    fresh = c.pay_token(order, payees)
    o2 = c.order(order)
    _send(c, r, "new_token_pays_the_new_order", [c.pay_ix(order, fresh, payees)])
    _send(c, r, "new_token_again", [c.pay_ix(order, fresh, payees, o2)], E_ORDER)
    _money(c, r, "end")
    return r


def pay_U_AFTER() -> int:
    """state.rs U_AFTER: where a used marker keeps the time after which it may be closed."""
    import re
    m = re.search(r"pub const U_AFTER: usize = (\d+);", (ROOT / "programs-v2/knos_pay/src/state.rs").read_text(encoding="utf-8"))
    return int(m.group(1))


# == 2. the second before, at, and after ================================================================================
def adv_deadline() -> rv.Recorder:
    """Three orders whose deadlines are one second apart, and two AUTO orders, all tried in one second: a second
    before the deadline and at it a proof pays and a refund is refused; a second after, the reverse."""
    r = rv.scenario("adv_deadline")
    c = _chain(r)
    payees = _payee(c, r)
    after = _fund(c, r, "after", work_s=HOUR)
    auto_after = c.fund_auto(work_s=HOUR)
    c.warp(1)
    at = _fund(c, r, "at", work_s=HOUR)
    auto_at = c.fund_auto(work_s=HOUR)
    c.warp(1)
    before = _fund(c, r, "before", work_s=HOUR)
    r.name_it(auto_at=auto_at, auto_at_tok=pay.ov_pda(auto_at), auto_after=auto_after, auto_after_tok=pay.ov_pda(auto_after))
    t = c.order(at).deadline
    assert (c.order(before).deadline, c.order(after).deadline, c.order(auto_at).deadline, c.order(auto_after).deadline) == (t + 1, t - 1, t, t - 1)
    c.warp(t - 100 - c.now())
    o = {k: c.order(k) for k in (before, at, after, auto_at, auto_after)}
    tok = {k: c.pay_token(k, payees) for k in (before, at, after)}
    auto = {k: c.auto_token(k, payees[0][0], payees[0][2]) for k in (auto_at, auto_after)}
    c.warp(t - c.now())
    assert c.now() == t
    _money(c, r, "start")

    def refund(k):
        return pay.refund_order_ix(c.payer.pubkey(), k, o[k])

    _send(c, r, "refund_one_second_before", [refund(before)], E_STATE)
    _send(c, r, "pay_one_second_before", [c.pay_ix(before, tok[before], payees)])
    _send(c, r, "refund_at_the_deadline", [refund(at)], E_STATE)
    _send(c, r, "pay_and_refund_at_the_deadline", [c.pay_ix(at, tok[at], payees), refund(at)], E_ORDER)
    _send(c, r, "refund_and_pay_at_the_deadline", [refund(at), c.pay_ix(at, tok[at], payees)], E_STATE)
    _send(c, r, "pay_at_the_deadline", [c.pay_ix(at, tok[at], payees)])
    _send(c, r, "refund_after_the_payment", [refund(at)], E_ORDER)
    _send(c, r, "pay_one_second_after", [c.pay_ix(after, tok[after], payees)], E_STATE)
    _send(c, r, "pay_and_refund_one_second_after", [c.pay_ix(after, tok[after], payees), refund(after)], E_STATE)
    _send(c, r, "refund_and_pay_one_second_after", [refund(after), c.pay_ix(after, tok[after], payees, o[after])], E_ORDER)
    _send(c, r, "refund_one_second_after", [refund(after)])
    _send(c, r, "pay_after_the_refund", [c.pay_ix(after, tok[after], payees, o[after])], E_ORDER)
    _send(c, r, "auto_at_the_deadline", [c.pay_ix(auto_at, auto[auto_at], payees)])
    _send(c, r, "auto_one_second_after", [c.pay_ix(auto_after, auto[auto_after], payees)], E_STATE)
    _send(c, r, "refund_auto_one_second_after", [refund(auto_after)])
    _money(c, r, "end")
    return r


def adv_hold() -> rv.Recorder:
    """Orders held for a payee without a wallet, whose holds end one second apart; the payee binds a wallet. A
    second before the hold ends and at it SettleOrder pays and a refund is refused; a second after, the reverse.
    Both in one transaction, in either order, on either side: refused whole."""
    r = rv.scenario("adv_hold")
    c = _chain(r)
    who = _order.user()
    payees = [(who, 10_000, None)]
    orders = {name: _fund(c, r, name) for name in ("after", "at", "before")}
    c.warp(5)
    for name in ("after", "at", "before"):
        r.label(f"hold_{name}")
        assert c.pay(orders[name], payees, tag=None), c.err
        assert c.order(orders[name]).state == "held"
        c.warp(1)
    wallet, dest = c.wallet(c.usdc)
    r.name_it(dest=dest)
    assert c.bind(who, wallet.pubkey()), c.err
    o = {k: c.order(v) for k, v in orders.items()}
    t = o["at"].hold_until
    assert (o["before"].hold_until, o["after"].hold_until) == (t + 1, t - 1)
    c.warp(t - c.now())
    _money(c, r, "start")

    def settle(k):
        return pay.settle_order_ix(c.payer.pubkey(), orders[k], o[k], wallet.pubkey())

    def refund(k):
        return pay.refund_order_ix(c.payer.pubkey(), orders[k], o[k])

    _send(c, r, "refund_one_second_before", [refund("before")], E_STATE)
    _send(c, r, "settle_one_second_before", [settle("before")])
    _send(c, r, "refund_at_the_end", [refund("at")], E_STATE)
    _send(c, r, "settle_and_refund_at_the_end", [settle("at"), refund("at")], E_ORDER)
    _send(c, r, "refund_and_settle_at_the_end", [refund("at"), settle("at")], E_STATE)
    _send(c, r, "settle_at_the_end", [settle("at")])
    _send(c, r, "refund_after_the_settlement", [refund("at")], E_ORDER)
    _send(c, r, "settle_one_second_after", [settle("after")], E_STATE)
    _send(c, r, "settle_and_refund_one_second_after", [settle("after"), refund("after")], E_STATE)
    _send(c, r, "refund_and_settle_one_second_after", [refund("after"), settle("after")], E_ORDER)
    _send(c, r, "refund_one_second_after", [refund("after")])
    _send(c, r, "settle_after_the_refund", [settle("after")], E_ORDER)
    _money(c, r, "end")
    return r


def adv_warranty() -> rv.Recorder:
    """Two orders with a tenth held back for a day, paid one second apart. In one second: the first is past its
    warranty (a challenge is refused, the holdback is released), the second is in its last second (a release is
    refused, the challenge returns the holdback)."""
    r = rv.scenario("adv_warranty")
    c = _chain(r)
    payees = _payee(c, r)
    options = pay.opts(holdback_bps=1000, warranty_days=1)
    over, last = _fund(c, r, "over", options=options), _fund(c, r, "last", options=options)
    c.warp(5)
    for k in (over, last):
        assert terms.pay_pr(c, k, payees), c.err
        c.warp(1)
    t = c.order(last).hold_until
    assert c.order(over).hold_until == t - 1 and c.order(last).state == "warranty"
    c.warp(t - 100 - c.now())
    challenge = {k: terms.revert_token(c, k) for k in (over, last)}
    c.warp(t - c.now())
    _money(c, r, "start")

    def release(k):
        return pay.release_ix(c.payer.pubkey(), k, c.order(k), terms.hb_of(c, k))

    def revert(k):
        return pay.revert_ix(c.payer.pubkey(), challenge[k], c.key, k, c.order(k), terms.hb_of(c, k))

    _send(c, r, "release_in_the_last_second", [release(last)], E_STATE)
    _send(c, r, "release_and_challenge_in_the_last_second", [release(last), revert(last)], E_STATE)
    _send(c, r, "challenge_one_second_after", [revert(over)], E_STATE)
    _send(c, r, "challenge_and_release_one_second_after", [revert(over), release(over)], E_STATE)
    late = release(over), revert(over)
    _send(c, r, "release_one_second_after", [late[0]])
    _send(c, r, "challenge_after_the_release", [late[1]], E_ORDER)
    early = revert(last), release(last)
    _send(c, r, "challenge_in_the_last_second", [early[0]])
    _send(c, r, "release_after_the_challenge", [early[1]], E_ORDER)
    _money(c, r, "end")
    return r


# == 4. one token, twice ================================================================================================
def adv_duplicates() -> rv.Recorder:
    """One pay token twice in one transaction and in two, on an order that closes with the payment and on a standing
    order that stays open; and a token signed for the meter shown to PayOrder."""
    r = rv.scenario("adv_duplicates")
    c = _chain(r)
    payees = _payee(c, r)
    once = _fund(c, r, "once")
    standing = _fund(c, r, "standing", options=pay.opts(pay.F_STANDING, rate=6 * USDC))
    c.warp(5)
    _money(c, r, "start")
    tok, o = c.pay_token(once, payees), c.order(once)
    ix = c.pay_ix(once, tok, payees)
    _send(c, r, "twice_in_one_transaction", [ix, ix], E_ORDER)
    _send(c, r, "once", [ix])
    _send(c, r, "again_in_a_second_transaction", [c.pay_ix(once, tok, payees, o)], E_ORDER)
    ix = terms.pay_ix(c, standing, payees, pr=1)
    _send(c, r, "standing_twice_in_one_transaction", [ix, ix], E_REPLAY)
    _send(c, r, "standing_once", [ix])
    _send(c, r, "standing_again_in_a_second_transaction", [ix], E_REPLAY)
    assert c.order(standing).state == "open"
    # an evaluation's token (the meter's audience), from the order's own repository's pinned run
    aud = meter.eval_audience(OWNER, _meter.SELLER, _meter.ORDER, HEAD, _meter.POLICY, 0, 1, 2 * USDC)
    evaluation = c.gh(aud, repository_id=REPO, repository_owner_id=OWNER)
    _send(c, r, "meter_token_to_pay_order", [_order.swap(terms.pay_ix(c, standing, payees, pr=2), 1, evaluation)], E_AUD)
    _money(c, r, "end")
    return r


def adv_meter_duplicates() -> rv.Recorder:
    """One evaluation's token twice in one transaction and again in a second: billed and counted once. A token signed
    for a payment (knos3:pay) shown to Record: refused, nothing billed."""
    r = rv.scenario("adv_meter_duplicates")
    c = _meter.Meter()
    mint = c.new_mint()
    wallet, credits = c.open(mint, _meter.BUYER, 0)
    wallet_tok = meter.ata(wallet.pubkey(), mint, c.token_program(mint))
    c.mint_to(mint, wallet_tok, 1000 * USDC)
    assert c.send([meter.deposit_ix(wallet_tok, wallet.pubkey(), credits, mint, 1000 * USDC, 6, c.token_program(mint))], wallet), c.err
    fee = c.token_account(meter.FEE_OWNER, mint)
    c.set_used(_meter.BUYER, meter.FREE_PER_MONTH)
    month = meter.yyyymm(c.now())
    r.name_it(credits=credits, credits_tok=meter.crtok_pda(credits), fee=fee, month=meter.month_pda(_meter.BUYER, _meter.SELLER, month))
    aud = c.aud("0" * 40, verdict=1, rate=2 * USDC)
    token = c.token(aud)
    ix = meter.record_ix(c.payer.pubkey(), token, c.key_of(token), credits, c.credits(credits), aud, c.now())
    r.label("twice_in_one_transaction")
    assert c.send([ix, ix]), c.err
    r.check(c.svm, "billed_once", tokens=["credits_tok", "fee"], data=["credits", "month"])
    r.label("again_in_a_second_transaction")
    assert c.send([ix]), c.err
    r.check(c.svm, "still_once", tokens=["credits_tok", "fee"], data=["credits", "month"])
    other = c.aud("1" * 40, verdict=1, rate=2 * USDC)
    payment = c.gh(f"knos3:pay:{credits}:{HEAD}:{'ab' * 32}:0:7:{_meter.SELLER}.10000.-", file="attest.yml", repository_owner_id=_meter.BUYER, run_attempt=1)
    r.label("pay_token_to_record")
    assert not c.send([meter.record_ix(c.payer.pubkey(), payment, c.key_of(payment), credits, c.credits(credits), other, c.now())])
    assert c.code == 116, c.err
    r.check(c.svm, "refused", tokens=["credits_tok", "fee"], data=["credits", "month"])
    return r


# == 5. one judge where two or three are asked ===========================================================================
def _present(c, r: rv.Recorder, label: str | None, order, payees, **over) -> bool:
    """One judge's token for the order's work, shown to PayOrder. The token is signed and its key put in place first,
    so the label is on the PayOrder transaction itself and a test stops right after it."""
    token = c.pay_token(order, payees, **over)
    if label:
        r.label(label)
    return c.send([c.pay_ix(order, token, payees)])


def adv_quorum() -> rv.Recorder:
    """A quorum of 2: one judge's token moves nothing, nor does a second token of the same judge; another judge's
    pays. A quorum of 3: two judges move nothing; the third pays."""
    r = rv.scenario("adv_quorum")
    c = _chain(r)
    payees = _payee(c, r)
    author = payees[0][0]
    two = _fund(c, r, "two", options=Q2)
    three = _fund(c, r, "three", options=pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(3), judge_repo_id=JUDGE_REPO))
    c.warp(5)
    _money(c, r, "start")
    for label, order, over in (("two_first_judge", two, {}), ("two_first_judge_again", two, {}), ("two_first_judge_a_third_time", two, {"actor_id": 77}),
                               ("two_second_judge", two, c.neutral(author)),
                               ("three_first_judge", three, {}), ("three_second_judge", three, c.neutral(author)),
                               ("three_second_judge_again", three, c.neutral(author)), ("three_first_judge_again", three, {}),
                               ("three_third_judge", three, dict(repository_id=JUDGE_REPO, repository_owner_id=FIRM, file="attest.yml", event_name="push"))):
        assert _present(c, r, label, order, payees, **over), c.err
        _money(c, r, label)
    return r


def adv_quorum_same_account() -> rv.Recorder:
    """FINDING 1 of 2.1, fixed. A wallet's order with a quorum of 2: the run in the order's repository is started by
    one account, and the same account then starts the neutral run in a repository it owns: one judge, nothing paid.
    Once with the repository's owner as that account, once with a maintainer who owns nothing of the order's; then a
    third party's neutral run pays."""
    r = rv.scenario("adv_quorum_same_account")
    c = _chain(r)
    payees = _payee(c, r)
    order = _fund(c, r, "order", options=Q2)
    other = _fund(c, r, "other", options=Q2)
    c.warp(5)
    _money(c, r, "start")
    assert _present(c, r, "own_run_started_by_the_account", order, payees, actor_id=OWNER), c.err
    assert _present(c, r, "neutral_run_started_by_the_same_account", order, payees, **c.neutral(OWNER)), c.err
    _money(c, r, "owner")
    assert _present(c, r, "own_run_started_by_a_maintainer", other, payees, actor_id=MAINT), c.err
    assert _present(c, r, "neutral_run_started_by_that_maintainer", other, payees, **c.neutral(MAINT)), c.err
    _money(c, r, "maintainer")
    assert _present(c, r, "neutral_run_of_a_third_party", other, payees, **c.neutral(_order.user())), c.err
    _money(c, r, "end")
    return r


def adv_quorum_same_second() -> rv.Recorder:
    """FINDING 2 of 2.1, fixed. An order with a quorum of 2 is paid by its two judges and its address funded again
    within the same second of the chain's clock: the first judge's marker of the first order carries the first
    order's stamp, and the second judge's new token alone moves nothing. Before that: the address funded and judged
    in ONE transaction (one slot) is refused whole."""
    r = rv.scenario("adv_quorum_same_second")
    c = _chain(r)
    payees = _payee(c, r)
    author, n = payees[0][0], _order.issue()
    order = _fund(c, r, "order", n, options=Q2)
    r.name_it(q_own=order_auto.q_pda(order, 0), q_neutral=order_auto.q_pda(order, 1))
    o1 = c.order(order)
    assert _present(c, r, "first_judge", order, payees) and _present(c, r, "second_judge", order, payees, **c.neutral(author)), c.err
    assert c.order(order) is None
    alone = c.pay_token(order, payees, o1, **c.neutral(author))
    _send(c, r, "fund_and_judge_in_one_slot", [c.fund_wallet_ix(n, options=Q2), c.pay_ix(order, alone, payees, o1)], E_STATE, payer=c.funder, signers=[c.payer])
    r.label("fund_again_in_the_same_second")
    assert c.fund_wallet(n, options=Q2) == order
    assert (c.order(order).not_before, c.order(order).stamp != o1.stamp) == (o1.not_before, True)
    _money(c, r, "funded_again")
    _send(c, r, "one_judge_alone", [c.pay_ix(order, alone, payees)])
    _money(c, r, "end")
    return r


def adv_quorum_owners() -> rv.Recorder:
    """Judges are counted by the owners of the repositories their runs were in. A wallet's orders: the order's
    repository and a judge repository of the same owner are one judge; of different owners, two; a quorum of 3 with
    two owners behind three judges does not pay until a third owner's run; a neutral run and a judge repository do
    not pay a wallet's order before its own repository has spoken. A Balance's order (funded by a comment on the
    forge): the same account behind the own run and the neutral run is one judge, and a third party's pays."""
    r = rv.scenario("adv_quorum_owners")
    c = _chain(r)
    payees = _payee(c, r)
    seller = payees[0][0]
    named = dict(repository_id=JUDGE_REPO, file="attest.yml", event_name="push")
    two = pay.opts(order_auto.quorum_flags(2), judge_repo_id=JUDGE_REPO)
    same, different = _fund(c, r, "same", options=two), _fund(c, r, "different", options=two)
    three = _fund(c, r, "three", options=pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(3), judge_repo_id=JUDGE_REPO))
    late = _fund(c, r, "late", options=pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(2), judge_repo_id=JUDGE_REPO))
    bal = c.fund_balance(options=Q2)
    r.name_it(bal=bal, bal_tok=pay.ov_pda(bal), baltok=pay.baltok_pda(c.bal))
    c.warp(5)
    _money(c, r, "start")
    steps = (("same_own", same, {}), ("same_owner_two_repositories", same, dict(named, repository_owner_id=OWNER)),
             ("different_own", different, {}), ("different_owners", different, dict(named, repository_owner_id=FIRM)),
             ("three_own", three, {}), ("three_neutral", three, c.neutral(seller)), ("three_judge_repository_of_the_owner", three, dict(named, repository_owner_id=OWNER)),
             ("three_third_owner", three, dict(named, repository_owner_id=FIRM)),
             ("late_neutral", late, c.neutral(seller)), ("late_judge_repository", late, dict(named, repository_owner_id=FIRM)), ("late_own", late, {}),
             ("balance_own_run_by_an_account", bal, dict(actor_id=seller)), ("balance_neutral_run_by_that_account", bal, c.neutral(seller)),
             ("balance_neutral_run_of_a_third_party", bal, c.neutral(_order.user())))
    for label, order, over in steps:
        assert _present(c, r, label, order, payees, **over), f"{label}: {c.err}"
        _money(c, r, label)
    return r


def adv_grace() -> rv.Recorder:
    """The presentation grace (orders funded with opts(grace=True)), at every boundary. A token the forge issued by
    the deadline pays a second after it and in the last second such a token can live; one issued a second after the
    deadline does not; a refund is refused through the whole grace and goes through the second after it; a payment
    and a refund in one transaction are refused whole. An order without the grace is refunded a second after its
    deadline, as before."""
    r = rv.scenario("adv_grace")
    c = _chain(r)
    payees = _payee(c, r)
    graced = pay.opts(grace=True)
    g1, g2, g3 = (_fund(c, r, name, work_s=HOUR, options=graced) for name in ("first", "last", "over"))
    plain = _fund(c, r, "plain", work_s=HOUR)
    o = {k: c.order(k) for k in (g1, g2, g3, plain)}
    t = o[g1].deadline
    assert all(x.deadline == t for x in o.values()) and o[g1].grace and not o[plain].grace and o[g1].pay_until == t + pay.GRACE
    c.warp(t - 10 - c.now())
    early = c.pay_token(g1, payees)
    c.warp(10)
    at = {k: c.pay_token(k, payees, exp=t + pay.TOKEN_LIFE) for k in (g2, g3)}      # the longest a token may live
    at[plain] = c.pay_token(plain, payees)
    c.warp(1)
    after = c.pay_token(g1, payees)
    assert c.now() == t + 1
    _money(c, r, "start")

    def refund(k):
        return pay.refund_order_ix(c.payer.pubkey(), k, o[k])

    _send(c, r, "refund_a_second_after_the_deadline", [refund(g1)], E_STATE)
    _send(c, r, "token_issued_after_the_deadline", [c.pay_ix(g1, after, payees)], E_STATE)
    _send(c, r, "pay_and_refund_in_the_grace", [c.pay_ix(g1, early, payees), refund(g1)], E_ORDER)
    _send(c, r, "refund_and_pay_in_the_grace", [refund(g1), c.pay_ix(g1, early, payees)], E_STATE)
    _send(c, r, "token_issued_before_the_deadline", [c.pay_ix(g1, early, payees)])
    _send(c, r, "refund_after_the_payment", [refund(g1)], E_ORDER)
    _send(c, r, "no_grace_no_payment", [c.pay_ix(plain, at[plain], payees)], E_STATE)
    _send(c, r, "no_grace_refund", [refund(plain)])
    c.warp(t + pay.GRACE - 1 - c.now())
    _send(c, r, "refund_in_the_last_second_a_token_lives", [refund(g2)], E_STATE)
    _send(c, r, "pay_in_the_last_second_a_token_lives", [c.pay_ix(g2, at[g2], payees)])
    c.warp(1)
    _send(c, r, "refund_at_the_end_of_the_grace", [refund(g3)], E_STATE)
    _send(c, r, "pay_at_the_end_of_the_grace", [c.pay_ix(g3, at[g3], payees)], E_TOKEN)
    c.warp(1)
    _send(c, r, "pay_after_the_grace", [c.pay_ix(g3, at[g3], payees)], E_TOKEN)
    _send(c, r, "refund_after_the_grace", [refund(g3)])
    _send(c, r, "pay_after_the_refund", [c.pay_ix(g3, at[g3], payees, o[g3])], E_ORDER)
    _money(c, r, "end")
    return r


# == orders and markers as knos_pay 2.1 wrote them ========================================================================
FEE_21 = 500_000        # what 2.1 charged on 20.00: 2.5%


def _as_2_1(c, order) -> None:
    """Rewrites an order this build funded into the account 2.1 would have left: no incarnation, no grace (bytes 432 to
    512 zero), the rate 250 and the fee 2.1 charged, which its token account then holds."""
    from solders.account import Account
    a, o = c.svm.get_account(order), c.order(order)
    d = bytearray(a.data)
    d[72:80] = FEE_21.to_bytes(8, "little")
    d[424:426] = (250).to_bytes(2, "little")
    d[432:512] = bytes(80)
    c.svm.set_account(order, Account(a.lamports, bytes(d), a.owner))
    c.mint_to(c.usdc, pay.ov_pda(order), FEE_21 - o.fee)
    assert (c.order(order).inc, c.order(order).fee, c.order(order).stamp, c.held(order)) == (0, FEE_21, o.not_before, o.amount + FEE_21)


def _marker_2_1(c, address, data: bytes) -> None:
    """A marker as 2.1 wrote it, at its address, with the rent of its length, paid by the chain's payer."""
    from solders.account import Account
    c.svm.set_account(address, Account(c.svm.minimum_balance_for_rent_exemption(len(data)), data, pay.PAY_ID))


def adv_compat_2_1() -> rv.Recorder:
    """Orders funded under 2.1 (their accounts as 2.1 wrote them: the fee of 2.1, its rate, no incarnation) under this
    build: one is paid (its own fee, not today's), one refunded a second after its deadline (no grace), one paid with
    a holdback and reverted in its warranty. A quorum marker of 2.1 (106 bytes, naming no run) counts for nothing:
    the judge signs again and the marker is made whole, then a second judge pays. A standing order of 2.1 does not
    pay a pull request its 65-byte marker names; an order of this build at an address with such a marker does."""
    r = rv.scenario("adv_compat_2_1")
    c = _chain(r)
    payees = _payee(c, r)
    seller = payees[0][0]
    paid, refunded = _fund(c, r, "paid"), _fund(c, r, "refunded", work_s=HOUR)
    reverted = _fund(c, r, "reverted", options=pay.opts(holdback_bps=1000, warranty_days=1))
    quorum, alone = _fund(c, r, "quorum", options=Q2), _fund(c, r, "alone", options=Q2)
    standing_opts = pay.opts(pay.F_STANDING, rate=6 * USDC)
    standing, fresh = _fund(c, r, "standing", options=standing_opts), _fund(c, r, "fresh", options=standing_opts)
    for k in (paid, refunded, reverted, quorum, alone, standing):
        _as_2_1(c, k)
    # the own repository's judge passed pull request 7 for both quorum orders under 2.1: its markers, as 2.1 wrote them
    for k in (quorum, alone):
        o = c.order(k)
        q, bump = Pubkey.find_program_address([b"q", bytes(k), bytes([0])], pay.PAY_ID)
        art = order_auto.artifact(pay.order_pay_audience(k, HEAD, o.terms, o.mode, 7, payees))
        _marker_2_1(c, q, bytes([bump, 0]) + bytes(c.payer.pubkey()) + bytes(k) + o.not_before.to_bytes(8, "little", signed=True) + art)
    r.name_it(q_own=order_auto.q_pda(quorum, 0), done_standing=pay.done_pda(standing, 1), done_fresh=pay.done_pda(fresh, 1))
    for k in (standing, fresh):
        _marker_2_1(c, pay.done_pda(k, 1), bytes([1]) + bytes(c.payer.pubkey()) + bytes(k))
    c.warp(5)
    _money(c, r, "start")
    _send(c, r, "pay", [c.pay_ix(paid, c.pay_token(paid, payees), payees)])
    _money(c, r, "paid")
    assert terms.pay_pr(c, reverted, payees), c.err
    c.warp(5)
    challenge = terms.revert_token(c, reverted)
    _send(c, r, "revert", [pay.revert_ix(c.payer.pubkey(), challenge, c.key, reverted, c.order(reverted), terms.hb_of(c, reverted))])
    _money(c, r, "reverted")
    # the quorum: a second judge alone does not pay on the word of a marker that names nobody
    assert _present(c, r, "second_judge_on_a_marker_of_2_1", alone, payees, **c.neutral(seller)), c.err
    assert _present(c, r, "first_judge_signs_again", quorum, payees), c.err
    assert _present(c, r, "second_judge", quorum, payees, **c.neutral(seller)), c.err
    _money(c, r, "quorum")
    # standing orders and their done markers
    _send(c, r, "standing_pull_request_marked_by_2_1", [terms.pay_ix(c, standing, payees, pr=1)], E_REPLAY)
    _send(c, r, "standing_another_pull_request", [terms.pay_ix(c, standing, payees, pr=2)])
    _send(c, r, "a_new_order_ignores_a_marker_of_2_1", [terms.pay_ix(c, fresh, payees, pr=1)])
    _send(c, r, "and_marks_it_for_itself", [terms.pay_ix(c, fresh, payees, pr=1)], E_REPLAY)
    _money(c, r, "standing")
    o = c.order(refunded)
    c.warp(o.deadline - c.now())
    _send(c, r, "refund_at_the_deadline", [pay.refund_order_ix(c.payer.pubkey(), refunded, o)], E_STATE)
    c.warp(1)
    _send(c, r, "refund_a_second_after", [pay.refund_order_ix(c.payer.pubkey(), refunded, o)])
    _money(c, r, "end")
    return r


def adv_reassign() -> rv.Recorder:
    """An assignment is for one funding of an address. A payee assigns an order's payment to a lender and the lender
    is paid; the address is funded again in the same second, and the next payment goes to the payee's own wallet."""
    r = rv.scenario("adv_reassign")
    c = _chain(r)
    who = _order.user()
    wallet, dest = c.wallet(c.usdc)
    lender, lender_tok = c.wallet(c.usdc)
    r.name_it(dest=dest, lender_tok=lender_tok)
    assert c.bind(who, wallet.pubkey()), c.err
    payees, n = [(who, 10_000, None)], _order.issue()
    order = _fund(c, r, "order", n)
    assign = pay.assign_ix(wallet.pubkey(), order, who, lender.pubkey())
    r.label("assign")
    assert c.send([assign], wallet), c.err
    _send(c, r, "pay_the_assignee", [terms.pay_ix(c, order, payees)])
    _money(c, r, "assigned")
    assert c.order(order) is None
    _send(c, r, "fund_and_assign_in_one_slot", [c.fund_wallet_ix(n), assign], E_STATE, payer=c.funder, signers=[wallet])
    r.label("fund_again_in_the_same_second")
    assert c.fund_wallet(n) == order
    _send(c, r, "pay_the_payee", [terms.pay_ix(c, order, payees)])
    _money(c, r, "end")
    return r


SCENARIOS = (adv_reopen, adv_deadline, adv_hold, adv_warranty, adv_duplicates, adv_meter_duplicates, adv_quorum, adv_quorum_same_account,
             adv_quorum_same_second, adv_quorum_owners, adv_grace, adv_compat_2_1, adv_reassign)


def main(argv: list[str]) -> int:
    check, stale = "--check" in argv, []
    only = [a for a in argv if not a.startswith("--")]
    for make in SCENARIOS:
        if only and make.__name__ not in only:
            continue
        r = make()
        path, doc = rv.OUT / f"{r.name}.json", r.doc()
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != doc:
                stale.append(path.name)
        else:
            path.write_text(doc, encoding="utf-8")
        txs = [s for s in r.steps if s["op"] == "tx"]
        print(f"{path.relative_to(ROOT)}: {len(txs)} transactions, {sum(not s['ok'] for s in txs)} refused, {len(doc):,} bytes")
    if stale:
        print("stale (run scripts/adversarial_vectors.py and commit): " + " ".join(stale), file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
