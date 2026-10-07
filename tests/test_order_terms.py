"""What a work order can promise (knos_pay 2.1, order_terms.rs) in the Solana runtime (LiteSVM): a holdback kept
through a warranty (Release, Revert), a standing offer paid once per pull request, a reservation, a cancellation with
notice and a kill fee, an assigned payment, and markers closed once they no longer matter. Every refusal an attacker
would try, and a random walk over every instruction in which what entered each order equals what left it plus what
it holds, and no unit is made or lost anywhere."""
from __future__ import annotations

import os
import random

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import DAY, HEAD, MAINT, OWNER, REPO, USDC, OrderChain, code, issue, swap, transfer, user  # noqa: E402

from knos.settle.v2 import oidc, pay  # noqa: E402

WALK_N = int(os.environ.get("KNOS_FUZZ_N", "500"))   # read at import: conftest clears KNOS_* per test
WALK_SEED = int(os.environ.get("KNOS_FUZZ_SEED", "313"))
FEE = pay.order_fee(20 * USDC)                       # 0.50 on an order of 20


def bal(c: OrderChain, *accounts: Pubkey) -> list[int]:
    return [c.balance(a) for a in accounts]


def wallets(c: OrderChain, order: Pubkey, payees) -> list:
    """(id, wallet) for each payee as the program resolves it: its assignee, else the token's address, else its Bind."""
    o = c.order(order)
    return [(i, pay.payee_wallet(c.data(pay.assign_pda(order, i)), o, pay.read_bind(c.data(pay.bind_pda(i))), a)) for i, _, a in payees]


def pay_ix(c: OrderChain, order: Pubkey, payees, pr: int = 7, to=None):
    tok = c.pay_token(order, payees, pr=pr)
    return pay.pay_order_ix(c.payer.pubkey(), tok, c.key, order, c.order(order), to or wallets(c, order, payees), pr=pr)


def pay_pr(c: OrderChain, order: Pubkey, payees, pr: int = 7, to=None) -> bool:
    return c.send([pay_ix(c, order, payees, pr, to)])


def hb_of(c: OrderChain, order: Pubkey) -> pay.Holdback | None:
    return pay.read_holdback(c.data(pay.hb_pda(order)))


def release(c: OrderChain, order: Pubkey) -> bool:
    return c.send([pay.release_ix(c.payer.pubkey(), order, c.order(order), hb_of(c, order))])


def revert_token(c: OrderChain, order: Pubkey, **over):
    return c.gh(pay.revert_audience(order, HEAD), **{"repository_id": REPO, **over})


def revert(c: OrderChain, order: Pubkey, tok=None, **over) -> bool:
    tok = tok or revert_token(c, order, **over)
    return c.send([pay.revert_ix(c.payer.pubkey(), tok, c.key, order, c.order(order), hb_of(c, order))])


def reserve(c: OrderChain, order: Pubkey, taker: int, days: int, **over) -> bool:
    """The taker's own run signs the take token: a person reserves for himself (prove.yml in the order's repository
    unless `over` says another run)."""
    tok = c.gh(pay.take_audience(order, taker, days), **{"repository_id": REPO, "actor_id": taker, **over})
    return c.send([pay.reserve_ix(c.payer.pubkey(), tok, c.key, order)])


def cancel(c: OrderChain, order: Pubkey, signer: Keypair | None = None, **over) -> bool:
    """The funding wallet signs (a wallet's order), or the order's repository signs a cancel token (a Balance's)."""
    if c.order(order).from_balance and signer is None:
        tok = c.gh(pay.cancel_audience(order), **{"repository_id": REPO, "actor_id": MAINT, **over})
        return c.send([pay.cancel_ix(c.payer.pubkey(), order, tok, c.key)])
    signer = signer or c.funder
    return c.send([pay.cancel_ix(signer.pubkey(), order)], signers=[signer])


def refund(c: OrderChain, order: Pubkey, kill_token: Pubkey | None = None) -> bool:
    return c.send([pay.refund_order_ix(c.payer.pubkey(), order, c.order(order), kill_token=kill_token)])


# == 1. holdback and warranty =========================================================================================
def test_a_holdback_stays_in_the_order_through_the_warranty_and_then_goes_to_the_wallets_it_recorded():
    c = OrderChain()
    a, b, wa, wb = user(), user(), Keypair().pubkey(), Keypair().pubkey()
    order = c.fund_wallet(options=pay.opts(holdback_bps=1000, warranty_days=30))
    payees = [(a, 7000, wa), (b, 3000, wb)]
    ta, tb = pay.ata(wa, c.usdc), pay.ata(wb, c.usdc)
    fee0, tip0 = bal(c, c.fee, c.tip)
    assert pay_pr(c, order, payees), c.err
    o, h = c.order(order), hb_of(c, order)
    # nine tenths are paid now, in the payees' shares; the tenth and the fee on it stay in the order
    assert bal(c, ta, tb) == [12_600_000, 5_400_000] and (o.state, o.paid, o.hold_until) == ("warranty", 18 * USDC, c.now() + 30 * DAY)
    # (nine tenths of the fee of 20.00 are 0.054: the relayer's tip for creating two token accounts takes all of it)
    assert bal(c, c.fee, c.tip) == [fee0, tip0 + FEE * 9 // 10] and c.held(order) == 2 * USDC + FEE // 10
    assert h.payees == [(a, wa, 1_400_000), (b, wb, 600_000)] and (h.payer, h.until) == (c.payer.pubkey(), o.hold_until)
    assert c.said("knos3:warranty") == [f"knos3:warranty order={order} held={2 * USDC} until={o.hold_until}"]
    # in warranty nothing else moves it: no second payment, no refund, no top-up, no release before its time
    assert not pay_pr(c, order, payees, pr=8) and code(c) == 83
    assert not refund(c, order) and code(c) == 83
    assert not c.send([pay.top_up_ix(c.funder.pubkey(), order, o, USDC)], c.funder) and code(c) == 83
    assert not release(c, order) and code(c) == 83
    c.warp(30 * DAY)
    assert not release(c, order) and code(c) == 83          # the last second of the warranty is still inside it
    c.warp(1)
    # the wallets are the recorded ones, and the record is the order's own
    ix = pay.release_ix(c.payer.pubkey(), order, o, h)
    other = c.fund_wallet(options=pay.opts(holdback_bps=1000, warranty_days=1))
    assert not c.send([swap(ix, 13, Keypair().pubkey())]) and code(c) == 88
    assert not c.send([swap(ix, 3, pay.hb_pda(other))]) and code(c) == 80
    assert not c.send([swap(ix, 8, Keypair().pubkey())]) and code(c) == 80        # the record's rent goes to who paid it
    rent = c.lamports(pay.hb_pda(order))
    before, fee1, tip1 = c.lamports(c.payer.pubkey()), *bal(c, c.fee, c.tip)
    assert c.send([ix]), c.err
    assert bal(c, ta, tb) == [14 * USDC, 6 * USDC] and bal(c, c.fee, c.tip) == [fee1, tip1 + FEE // 10]
    assert c.data(order) is None and c.data(pay.ov_pda(order)) is None and c.data(pay.hb_pda(order)) is None and rent > 0
    assert c.lamports(c.payer.pubkey()) > before             # the three rents came back, less the transaction's fee


def test_a_revert_inside_the_warranty_returns_the_holdback_and_its_fee_to_the_funder():
    c = OrderChain()
    a, wa = user(), Keypair().pubkey()
    opts = pay.opts(holdback_bps=2500, warranty_days=10)
    order, early = c.fund_wallet(options=opts), None
    early = revert_token(c, order)                           # signed before the payment: it says nothing about it
    c.warp(5)
    assert pay_pr(c, order, [(a, 10_000, wa)]), c.err
    assert c.balance(pay.ata(wa, c.usdc)) == 15 * USDC and c.held(order) == 5 * USDC + FEE // 4
    assert not revert(c, order, tok=early) and code(c) == 83
    c.warp(DAY)
    assert not revert(c, order, repository_id=REPO + 1) and code(c) == 85         # another repository is not this order's judge
    assert not revert(c, order, file="fund.yml") and code(c) == 86
    assert not revert(c, order, wf_sha="d" * 40) and code(c) == 86
    assert not revert(c, order, tok=c.gh(pay.revert_audience(Keypair().pubkey(), HEAD), repository_id=REPO)) and code(c) == 87
    assert not revert(c, order, tok=c.gh(f"knos3:revert:{order}:zz", repository_id=REPO)) and code(c) == 87
    assert not revert(c, order, tok=c.pay_token(order, [(a, 10_000, wa)])) and code(c) == 87      # a pay token is not a revert
    ix = pay.revert_ix(c.payer.pubkey(), revert_token(c, order), c.key, order, c.order(order), hb_of(c, order))
    assert not c.send([swap(ix, 6, c.tip)]) and code(c) == 88                                    # only back to the funder
    funder0 = c.balance(c.funder_tok)
    assert c.send([ix]), c.err
    assert c.balance(c.funder_tok) == funder0 + 5 * USDC + FEE // 4 and c.balance(pay.ata(wa, c.usdc)) == 15 * USDC
    assert c.data(order) is None and c.data(pay.ov_pda(order)) is None and c.data(pay.hb_pda(order)) is None
    assert c.said("knos3:reverted") == [f"knos3:reverted order={order} amount={5 * USDC + FEE // 4} head={HEAD}"]
    # after the warranty a revert is too late, and the holdback is the payee's
    late = c.fund_wallet(options=pay.opts(holdback_bps=2500, warranty_days=1))
    assert pay_pr(c, late, [(a, 10_000, wa)]), c.err
    c.warp(DAY + 1)
    assert not revert(c, late) and code(c) == 83
    assert release(c, late) and c.balance(pay.ata(wa, c.usdc)) == 35 * USDC


def test_judges_a_b_and_c_sign_a_revert_and_nobody_else():
    c = OrderChain()
    a, wa, judge_repo = user(), Keypair().pubkey(), 31_313_131
    # b: the pinned attest.yml, started by hand in the runner's own repository; c: the order's judge repository
    hand = dict(file="attest.yml", event_name="workflow_dispatch", repository_id=700_700_700, repository_owner_id=a, actor_id=a)
    strict = c.fund_wallet(options=pay.opts(holdback_bps=2500, warranty_days=10))
    neutral = c.fund_wallet(options=pay.opts(pay.F_NEUTRAL, holdback_bps=2500, warranty_days=10))
    judged = c.fund_wallet(options=pay.opts(holdback_bps=2500, warranty_days=10, judge_repo_id=judge_repo))
    for k in (strict, neutral, judged):
        assert pay_pr(c, k, [(a, 10_000, wa)]), c.err
    paid, kept = c.balance(pay.ata(wa, c.usdc)), 5 * USDC + FEE // 4
    c.warp(1)
    # an order whose funder allowed neither: only its own repository's prove.yml
    assert not revert(c, strict, **hand) and code(c) == 85
    assert not revert(c, strict, repository_id=judge_repo) and code(c) == 85
    # b is refused everything a neutral payment is refused
    for over, want in ((dict(event_name="push"), 85), (dict(repository_owner_id=user()), 85), (dict(actor_id=user()), 85), (dict(run_attempt=2), 85),
                       (dict(file="prove.yml"), 86), (dict(file="fund.yml"), 86), (dict(wf_sha="d" * 40), 86), (dict(wf_repo="evil/Knos"), 86)):
        assert not revert(c, neutral, **{**hand, **over}) and code(c) == want, over
    assert not revert(c, judged, repository_id=judge_repo, file="fund.yml") and code(c) == 86
    assert not revert(c, judged, **hand) and code(c) == 85
    # a ruling is not a revert, and a revert is not the arbiter's
    assert not revert(c, neutral, tok=c.gh(f"knos3:rule:{neutral}:{a}.10000.-", **hand)) and code(c) == 85
    assert [c.held(k) for k in (strict, neutral, judged)] == [kept] * 3
    funder0 = c.balance(c.funder_tok)
    assert revert(c, neutral, **hand), c.err
    assert c.said("knos3:reverted") == [f"knos3:reverted order={neutral} amount={kept} head={HEAD}"]
    assert revert(c, judged, repository_id=judge_repo, file="attest.yml", event_name="push"), c.err
    assert revert(c, strict), c.err
    # each only returned what the order still held, to its funder: what was paid stays paid
    assert c.balance(c.funder_tok) == funder0 + 3 * kept and c.balance(pay.ata(wa, c.usdc)) == paid
    assert all(c.data(x) is None for k in (strict, neutral, judged) for x in (k, pay.ov_pda(k), pay.hb_pda(k)))


def test_an_order_with_a_holdback_is_never_held_and_a_standing_one_cannot_have_a_holdback(chain):
    c = chain
    nobody, somebody, w = user(), user(), Keypair().pubkey()
    order = c.fund_wallet(options=pay.opts(holdback_bps=1000, warranty_days=5))
    before = c.held(order)
    assert not pay_pr(c, order, [(nobody, 10_000, None)]) and code(c) == 88                      # no wallet: refused, not held
    assert not pay_pr(c, order, [(somebody, 5000, w), (nobody, 5000, None)]) and code(c) == 88
    assert (c.order(order).state, c.held(order)) == ("open", before)
    ix = pay_ix(c, order, [(somebody, 10_000, w)])
    assert not c.send([swap(ix, len(ix.accounts) - 1, pay.hb_pda(Keypair().pubkey()))]) and code(c) == 80   # the record is this order's
    assert c.bind(nobody, w) and pay_pr(c, order, [(nobody, 10_000, None)]) and c.order(order).state == "warranty"
    both = c.fund_wallet(options=pay.opts(pay.F_STANDING, holdback_bps=1000, warranty_days=5, rate=5 * USDC))
    assert not pay_pr(c, both, [(somebody, 10_000, w)]) and code(c) == 103
    # a mint so coarse that the holdback rounds to nothing: the order is paid whole and closed
    coarse = c.new_mint(decimals=0)
    f, ft = c.wallet(coarse, 1000)
    c.token_account(pay.FEE_OWNER, coarse); c.token_account(c.payer.pubkey(), coarse)
    tiny = c.fund_wallet(amount=5, funder=f, funder_tok=ft, mint=coarse, options=pay.opts(holdback_bps=100, warranty_days=5))
    assert pay_pr(c, tiny, [(somebody, 10_000, w)]) and c.data(tiny) is None and c.balance(pay.ata(w, coarse)) == 5


# == 2. standing orders ==============================================================================================
def test_a_standing_order_pays_its_rate_once_per_pull_request_until_less_than_one_rate_is_left(chain):
    c = chain
    a, wa, nobody = user(), Keypair().pubkey(), user()
    order = c.fund_wallet(options=pay.opts(pay.F_STANDING, rate=6 * USDC))
    one, ta = [(a, 10_000, wa)], pay.ata(wa, c.usdc)
    fee0, tip0 = bal(c, c.fee, c.tip)
    assert not pay_pr(c, order, [(nobody, 10_000, None)], pr=1) and code(c) == 88       # never held: others are waiting
    assert pay_pr(c, order, one, pr=1), c.err
    o = c.order(order)
    # the order is kept as what is left of it: the amount its payees can still receive, and the fee still escrowed
    assert (o.state, o.amount, o.fee, o.paid, c.balance(ta), c.held(order)) == ("open", 14 * USDC, FEE - FEE * 6 // 20, 0, 6 * USDC, 14 * USDC + FEE - FEE * 6 // 20)
    assert pay.read_marker(c.data(pay.done_pda(order, 1))) == (c.payer.pubkey(), order)
    assert not pay_pr(c, order, one, pr=1) and code(c) == 91                            # one pull request is paid once
    ix = pay_ix(c, order, one, pr=2)
    assert not c.send([swap(ix, len(ix.accounts) - 1, pay.done_pda(order, 1))]) and code(c) == 80   # nor under another's marker
    assert not c.send([swap(ix, len(ix.accounts) - 1, pay.done_pda(order, 3))]) and code(c) == 80
    assert c.send([ix]) and pay_pr(c, order, one, pr=3), c.err
    o = c.order(order)
    assert (o.state, o.amount, o.fee, o.paid, c.balance(ta), c.held(order)) == ("open", 2 * USDC, FEE // 10, 0, 18 * USDC, 2 * USDC + FEE // 10)
    assert bal(c, c.fee, c.tip) == [fee0, tip0 + 3 * (FEE * 6 // 20)]       # the fee's share of each payment (0.018) is less than a tip: the relayer takes it
    # less than one rate is left: nothing more is paid, and the rest goes back without waiting for the deadline
    assert o.deadline < c.now() and not pay_pr(c, order, one, pr=4) and code(c) == 83
    marker = pay.done_pda(order, 2)
    assert not c.send([pay.close_marker_ix(marker, c.payer.pubkey(), order)]) and code(c) == 83   # its order is still there
    funder0 = c.balance(c.funder_tok)
    assert refund(c, order) and c.balance(c.funder_tok) == funder0 + 2 * USDC + FEE // 10 and c.data(order) is None
    # a small standing order topped up to a large one: the fee floor made the first payment's fee share larger than
    # the later ones', and still every rate is paid in full and the last payment closes the order
    small = c.fund_wallet(amount=5 * USDC, options=pay.opts(pay.F_STANDING, rate=2_500_000))
    assert pay_pr(c, small, one, pr=1) and (c.order(small).amount, c.order(small).fee) == (2_500_000, 25_000)
    assert c.send([pay.top_up_ix(c.funder.pubkey(), small, c.order(small), 95 * USDC)], c.funder), c.err
    assert (c.order(small).amount, c.order(small).fee, c.held(small)) == (97_500_000, 292_500, 97_500_000 + 292_500)
    at0 = c.balance(ta)
    for pr in range(2, 41):
        assert pay_pr(c, small, one, pr=pr), (pr, c.err)
    assert c.balance(ta) == at0 + 97_500_000 and c.data(small) is None and c.data(pay.ov_pda(small)) is None
    # a standing order whose amount is a whole number of rates closes with its last payment
    exact = c.fund_wallet(amount=10 * USDC, options=pay.opts(pay.F_STANDING, rate=5 * USDC))
    assert pay_pr(c, exact, one, pr=1) and pay_pr(c, exact, one, pr=2) and c.data(exact) is None and c.data(pay.ov_pda(exact)) is None
    # 5. a done marker is closed once its order is, its rent back to who paid it, and to nobody else
    assert not c.send([pay.close_marker_ix(marker, Keypair().pubkey(), order)]) and code(c) == 80
    assert not c.send([pay.close_marker_ix(marker, c.payer.pubkey(), exact)]) and code(c) == 83
    assert not c.send([pay.close_marker_ix(pay.bind_pda(a), c.payer.pubkey(), order)]) and code(c) == 80
    rent, before = c.lamports(marker), c.lamports(c.payer.pubkey())
    assert c.send([pay.close_marker_ix(marker, c.payer.pubkey(), order)]), c.err
    assert c.data(marker) is None and c.lamports(c.payer.pubkey()) == before + rent - 5000


# == 3. reserve, cancel, kill fee ====================================================================================
def test_a_reservation_a_cancellation_with_notice_and_the_kill_fee():
    c = OrderChain()
    opts = pay.opts(kill_bps=1000, reserve_days=3)
    t1, t2, t3, w1 = user(), user(), user(), Keypair().pubkey()
    direct, heldk, stale, paid, never = (c.fund_wallet(options=opts) for _ in range(5))
    fromb = c.fund_balance(options=opts)
    # -- reserve: a judge names the taker, for at most the days the funder allowed, one taker at a time
    assert not reserve(c, direct, t1, 4) and code(c) == 87
    assert not reserve(c, direct, t1, 0) and code(c) == 87
    assert not reserve(c, direct, 0, 1) and code(c) == 87
    assert not reserve(c, direct, t1, 2, repository_id=REPO + 1) and code(c) == 85
    assert not reserve(c, direct, t1, 2, run_attempt=2) and code(c) == 85
    tok = c.gh(pay.take_audience(heldk, t1, 2), repository_id=REPO)
    assert not c.send([pay.reserve_ix(c.payer.pubkey(), tok, c.key, direct)]) and code(c) == 87    # another order's token
    assert not reserve(c, c.fund_wallet(), t1, 1) and code(c) == 87                               # an order funded with no reserve days
    assert reserve(c, direct, t1, 3), c.err
    o = c.order(direct)
    assert (o.reserved_by, o.reserved_until) == (t1, c.now() + 3 * DAY)
    assert not reserve(c, direct, t2, 1) and code(c) == 83
    assert reserve(c, heldk, t2, 3) and reserve(c, stale, t3, 1) and reserve(c, paid, t1, 3) and reserve(c, never, t3, 3) and reserve(c, fromb, t1, 3), c.err
    # a person reserves for himself: the token's actor is the taker it names, whoever's run it is
    cmd, open_to_all = c.fund_wallet(options=opts), c.fund_wallet(options=pay.opts(pay.F_NEUTRAL, kill_bps=1000, reserve_days=3))
    assert not reserve(c, cmd, t1, 3, actor_id=t2) and code(c) == 85
    assert not reserve(c, cmd, t1, 3, actor_id=MAINT) and code(c) == 85                           # not even the repository's maintainer
    # the COMMAND job mints it: the pinned fund.yml in the order's repository, on the taker's own comment
    comment = dict(file="fund.yml", event_name="issue_comment")
    assert not reserve(c, cmd, t1, 3, **comment, actor_id=t2) and code(c) == 85
    assert not reserve(c, cmd, t1, 3, **comment, wf_sha="d" * 40) and code(c) == 86               # the order's workflows commit
    assert not reserve(c, cmd, t1, 3, **comment, wf_repo="evil/Knos") and code(c) == 86
    assert not reserve(c, cmd, t1, 3, **comment, run_attempt=2) and code(c) == 85
    assert not reserve(c, cmd, t1, 3, **comment, repository_id=REPO + 1) and code(c) == 85        # another repository's command job
    assert not reserve(c, cmd, t1, 3, file="attest.yml") and code(c) == 86                        # not a file that reserves there
    assert reserve(c, cmd, t1, 3, **comment), c.err
    assert (c.order(cmd).reserved_by, c.order(cmd).reserved_until) == (t1, c.now() + 3 * DAY)
    # a NEUTRAL order: the taker starts the pinned attest.yml by hand in a repository of his own, and names himself
    hand = dict(file="attest.yml", event_name="workflow_dispatch", repository_id=700_700_700)
    assert not reserve(c, open_to_all, t1, 3, **hand, repository_owner_id=t2, actor_id=t2) and code(c) == 85     # t2 cannot reserve for t1
    assert not reserve(c, open_to_all, t1, 3, **hand, repository_owner_id=t2) and code(c) == 85   # nor t1 in a repository that is not his
    assert not reserve(c, open_to_all, t1, 3, **{**hand, "event_name": "push"}, repository_owner_id=t1) and code(c) == 85
    assert not reserve(c, open_to_all, t1, 3, **{**hand, "file": "fund.yml"}, repository_owner_id=t1) and code(c) == 86
    assert not reserve(c, c.fund_wallet(options=opts), t1, 3, **hand, repository_owner_id=t1) and code(c) == 85  # an order that is not NEUTRAL
    assert reserve(c, open_to_all, t1, 3, **hand, repository_owner_id=t1), c.err
    assert c.order(open_to_all).reserved_by == t1
    c.warp(DAY + 1)
    assert reserve(c, stale, t2, 1), c.err                    # a reservation that ran out makes room
    c.warp(DAY + 1)
    # -- cancel: the funding wallet, or the Balance order's own repository; once
    assert not cancel(c, direct, signer=c.owner) and code(c) == 80
    assert not c.send([pay.cancel_ix(c.owner.pubkey(), fromb)], signers=[c.owner])                # a Balance's order needs the token
    assert not cancel(c, fromb, actor_id=t1) and code(c) == 85
    assert not cancel(c, fromb, repository_id=REPO + 1) and code(c) == 85
    tok = c.gh(pay.cancel_audience(direct), repository_id=REPO, actor_id=MAINT)
    assert not c.send([pay.cancel_ix(c.payer.pubkey(), fromb, tok, c.key)]) and code(c) == 87
    # the COMMAND job mints a cancel token too (fund.yml on the funder's or the owner's comment); a NEUTRAL run cancels nothing
    byc, byn = c.fund_balance(options=opts), c.fund_balance(options=pay.opts(pay.F_NEUTRAL, kill_bps=1000, reserve_days=3))
    comment = dict(file="fund.yml", event_name="issue_comment")
    assert not cancel(c, byc, **comment, actor_id=t1) and code(c) == 85
    assert not cancel(c, byc, **comment, repository_id=REPO + 1) and code(c) == 85
    assert not cancel(c, byc, **comment, wf_sha="d" * 40) and code(c) == 86
    assert not cancel(c, byc, **comment, run_attempt=2) and code(c) == 85
    assert not cancel(c, byc, file="attest.yml") and code(c) == 86
    for who in (MAINT, OWNER):
        assert not cancel(c, byn, file="attest.yml", event_name="workflow_dispatch", repository_id=700_700_700, repository_owner_id=who, actor_id=who) and code(c) == 85
    d0 = c.order(byc).deadline
    assert cancel(c, byc, **comment, actor_id=OWNER), c.err
    assert (c.order(byc).cancel_at, c.order(byc).deadline) == (c.now(), min(d0, c.now() + pay.NOTICE))
    assert cancel(c, byn, **comment), c.err                                                       # the commenter who funded it
    for k in (direct, heldk, stale, paid, never, fromb):
        d0 = c.order(k).deadline
        assert cancel(c, k), c.err
        o = c.order(k)
        assert (o.cancel_at, o.deadline) == (c.now(), min(d0, c.now() + pay.NOTICE)) and o.deadline < d0
        assert not cancel(c, k) and code(c) == 83
    assert not reserve(c, stale, t1, 1) and code(c) == 83     # nobody takes a cancelled order for its kill fee
    assert not refund(c, direct) and code(c) == 83            # the notice runs
    # -- inside the notice a pay token still pays, and a paid order owes no kill fee
    assert pay_pr(c, paid, [(t1, 10_000, w1)]) and c.data(paid) is None and c.balance(pay.ata(w1, c.usdc)) == 20 * USDC
    c.warp(pay.NOTICE + 1)
    assert c.bind(t1, w1), c.err
    # -- the kill fee: to the taker's bound wallet, before the refund
    ix = pay.refund_order_ix(c.payer.pubkey(), direct, c.order(direct), kill_token=pay.ata(w1, c.usdc))
    assert pay.kill_fee(c.order(direct)) == 2 * USDC and len(ix.accounts) == 10
    assert not c.send([swap(ix, 8, pay.bind_pda(t2))]) and code(c) == 88                          # the taker's Bind cannot be hidden
    funder0, taker0 = bal(c, c.funder_tok, pay.ata(w1, c.usdc))
    assert c.send([ix]), c.err
    assert bal(c, c.funder_tok, pay.ata(w1, c.usdc)) == [funder0 + 18 * USDC + FEE, taker0 + 2 * USDC] and c.data(direct) is None
    assert c.said("knos3:kill") == [f"knos3:kill order={direct} taker={t1} amount={2 * USDC} held=0"]
    # a Balance's order: the same, the rest back to the Balance
    b0, taker0 = bal(c, pay.baltok_pda(c.bal), pay.ata(w1, c.usdc))
    assert refund(c, fromb, kill_token=pay.ata(w1, c.usdc)), c.err
    assert bal(c, pay.baltok_pda(c.bal), pay.ata(w1, c.usdc)) == [b0 + 18 * USDC + FEE, taker0 + 2 * USDC]
    # -- no kill fee when the reservation had run out before the cancellation
    funder0 = c.balance(c.funder_tok)
    assert pay.kill_fee(c.order(stale)) == 0 and refund(c, stale) and c.balance(c.funder_tok) == funder0 + 20 * USDC + FEE
    # -- a taker with no wallet: the rest goes back now, the fee is held for him, and the order closes when he is paid
    for k, taker in ((heldk, t2), (never, t3)):
        funder0 = c.balance(c.funder_tok)
        assert refund(c, k, kill_token=c.tip), c.err          # a token account that is not his changes nothing
        o = c.order(k)
        assert c.balance(c.funder_tok) == funder0 + 18 * USDC + FEE and c.held(k) == 2 * USDC
        assert (o.state, o.payee_id, o.amount, o.fee, o.paid, o.hold_until, o.reserved_by, o.kill_bps) == ("held", taker, 2 * USDC, 0, 0, c.now() + pay.HOLD, 0, 0)
        assert not refund(c, k) and code(c) == 83
    w2 = Keypair().pubkey()
    assert not c.settle(heldk, w2) and code(c) == 88
    assert c.bind(t2, w2) and c.settle(heldk, w2), c.err
    assert c.balance(pay.ata(w2, c.usdc)) == 2 * USDC and c.data(heldk) is None and c.data(pay.ov_pda(heldk)) is None
    # he never binds one: after the hold it is the funder's again
    c.warp(pay.HOLD + 1)
    funder0 = c.balance(c.funder_tok)
    assert refund(c, never) and c.balance(c.funder_tok) == funder0 + 2 * USDC and c.data(never) is None and c.data(pay.ov_pda(never)) is None


# == 4. assign =======================================================================================================
def test_a_payee_assigns_an_orders_payment_and_only_the_assignee_can_change_it(chain):
    c = chain
    a, b, x = user(), user(), user()
    wa, wb, lender, lender2 = c.fund(), c.fund(), c.fund(), Keypair().pubkey()
    assert c.bind(a, wa.pubkey()) and c.bind(b, wb.pubkey()), c.err
    order = c.fund_wallet()
    asg = lambda signer, who, to, o=order: c.send([pay.assign_ix(signer.pubkey(), o, who, to)], signers=[signer])  # noqa: E731
    assert not asg(wb, a, lender.pubkey()) and code(c) == 80                 # only the payee's own bound wallet
    assert not asg(lender, a, lender.pubkey()) and code(c) == 80
    assert not asg(wa, x, lender.pubkey()) and code(c) == 88                 # an id with no bound wallet assigns nothing
    assert not asg(wa, a, pay.auth_pda()) and code(c) == 88
    ix = pay.assign_ix(wa.pubkey(), order, a, lender.pubkey())
    assert not c.send([swap(ix, 3, pay.assign_pda(order, b))], signers=[wa]) and code(c) == 88
    assert not c.send([swap(ix, 1, c.bal)], signers=[wa]) and code(c) == 101
    assert asg(wa, a, lender.pubkey()), c.err
    assert pay.read_assign(c.data(pay.assign_pda(order, a)), c.order(order)) == lender.pubkey()
    assert c.said("knos3:assigned") == [f"knos3:assigned order={order} payee={a} to={lender.pubkey()}"]
    # the payee cannot take it back or assign it twice; the assignee can pass it on
    assert not asg(wa, a, wa.pubkey()) and code(c) == 80
    assert asg(lender, a, lender2) and not asg(lender, a, lender.pubkey()) and code(c) == 80
    # PayOrder pays the assignee whatever address the token carries, and the assignment cannot be left out
    payees = [(a, 6000, None), (b, 4000, None)]
    assert not pay_pr(c, order, payees, to=c.wallets(payees)) and code(c) == 88
    good = pay_ix(c, order, payees)
    assert not c.send([swap(good, 23, pay.assign_pda(order, x))]) and code(c) == 88
    assert not c.send([swap(good, 23, pay.SYSTEM)]) and code(c) == 88
    assert c.send([good]), c.err
    assert bal(c, pay.ata(lender2, c.usdc), pay.ata(wb.pubkey(), c.usdc), pay.ata(wa.pubkey(), c.usdc)) == [12 * USDC, 8 * USDC, 0]
    # another order of the same payee is not assigned
    plain = c.fund_wallet()
    assert pay_pr(c, plain, [(a, 10_000, Keypair().pubkey())], to=[(a, wa.pubkey())]) is False and code(c) == 88
    assert pay_pr(c, plain, [(a, 10_000, None)]) and c.balance(pay.ata(wa.pubkey(), c.usdc)) == 20 * USDC
    # SettleOrder pays the assignee too: a held order's payee binds a wallet, then assigns
    wx, held = c.fund(), c.fund_wallet()
    assert pay_pr(c, held, [(x, 10_000, None)]) and c.order(held).state == "held"
    assert c.bind(x, wx.pubkey()) and asg(wx, x, lender2, held), c.err
    assert not c.settle(held, wx.pubkey()) and code(c) == 88
    ix = pay.settle_order_ix(c.payer.pubkey(), held, c.order(held), lender2)
    assert not c.send([swap(ix, 16, pay.assign_pda(order, x))]) and code(c) == 88
    assert c.send([ix]) and c.balance(pay.ata(lender2, c.usdc)) == 32 * USDC and c.balance(pay.ata(wx.pubkey(), c.usdc)) == 0
    # an assignment made for an order that is gone is not the next order's at the same address
    n = issue()
    first = c.fund_wallet(n)
    assert asg(wa, a, lender2, first), c.err
    c.warp(14 * DAY + 1)
    assert refund(c, first) and c.fund_wallet(n) == first
    assert pay.read_assign(c.data(pay.assign_pda(first, a))) == lender2 and pay.read_assign(c.data(pay.assign_pda(first, a)), c.order(first)) is None
    assert asg(wa, a, lender.pubkey(), first), c.err          # so the payee, not the old assignee, assigns it


# == 5. markers ======================================================================================================
def test_a_used_marker_is_closed_once_no_token_it_stands_for_can_be_accepted():
    from test_order_chain import fund_job, job_token, pay_job

    c = OrderChain()
    n, payee, w = issue(), user(), Keypair().pubkey()
    tok = c.fund_token(n)
    assert c.send([c.fund_balance_ix(tok, n)]), c.err
    used = pay.used_pda(c.data(tok))
    assert pay.read_marker(c.data(used)) == (c.payer.pubkey(), c.now() + pay.USED_KEEP)
    # the 2.0 Pay path's marker stores the same
    m = issue()
    assert fund_job(c, m, 5 * USDC)
    job = pay.job_pda(REPO, m, c.funder.pubkey())
    jt = job_token(c, job, payee, w)
    assert pay_job(c, job, jt, payee, w), c.err
    used2 = pay.used_pda(c.data(jt))
    assert pay.read_marker(c.data(used2)) == (c.payer.pubkey(), c.now() + pay.USED_KEEP)
    assert not c.send([pay.close_marker_ix(used, c.payer.pubkey())]) and code(c) == 83
    c.warp(pay.USED_KEEP)
    assert not c.send([pay.close_marker_ix(used, c.payer.pubkey())]) and code(c) == 83
    assert not c.send([c.fund_balance_ix(tok, n, seq=1)])    # and by then the token itself is long refused
    c.warp(1)
    assert not c.send([pay.close_marker_ix(used, c.funder.pubkey())]) and code(c) == 80
    assert not c.send([pay.close_marker_ix(pay.ov_pda(used), c.payer.pubkey())]) and code(c) == 80
    for marker in (used, used2):
        rent, before = c.lamports(marker), c.lamports(c.payer.pubkey())
        assert c.send([pay.close_marker_ix(marker, c.payer.pubkey())]), c.err
        assert c.data(marker) is None and c.lamports(c.payer.pubkey()) == before + rent - 5000


# == every instruction, at random ====================================================================================
def test_a_random_walk_over_every_promise_conserves_every_orders_money():
    c, rng = OrderChain(), random.Random(WALK_SEED)
    people = [(user(), c.fund()) for _ in range(6)]
    lender = Keypair().pubkey()
    key_of = dict(people)
    for who, k in people[:4]:
        assert c.bind(who, k.pubkey()), c.err
    for who, k in people[:2]:
        c.token_account(k.pubkey(), c.usdc)
    watched = [c.funder_tok, pay.baltok_pda(c.bal), c.fee, c.tip, c.owner_tok, pay.ata(lender, c.usdc), *(pay.ata(k.pubkey(), c.usdc) for _, k in people)]
    orders: dict[Pubkey, dict] = {}     # order -> entered, left
    markers: list[tuple[Pubkey, Pubkey | None]] = []
    total = lambda: sum(c.balance(a) for a in watched)  # noqa: E731
    everything = total()

    def step(order: Pubkey | None, action) -> bool:
        """Runs one action and books what the watched accounts lost or gained to the order it was about."""
        before = total()
        ok = action()
        delta = total() - before
        if ok and order is not None:
            book = orders.setdefault(order, {"entered": 0, "left": 0})
            book["entered" if delta < 0 else "left"] += abs(delta)
        else:
            assert delta == 0
        return ok

    def options(amount: int) -> bytes:
        kind = rng.choice(["plain", "plain", "holdback", "holdback", "standing"])
        extra = dict(kill_bps=rng.choice([0, 500, 2000, 2000]), reserve_days=rng.choice([0, 1, 3, 3]))
        if kind == "holdback":
            return pay.opts(holdback_bps=rng.choice([1, 500, 2500, 5000]), warranty_days=rng.choice([1, 2]), **extra)
        if kind == "standing":
            return pay.opts(pay.F_STANDING, rate=rng.randrange(USDC, amount + 1), **extra)
        return pay.opts(**extra)

    done = dict.fromkeys(["funded", "paid", "held", "settled", "refunded", "topped", "dust", "reserved", "cancelled", "released", "reverted", "assigned",
                          "closed", "kill", "warranty", "standing", "refused"], 0)
    kinds = ["fund", "fund", "pay", "pay", "pay", "pay", "top", "dust", "refund", "refund", "settle", "settle", "reserve", "reserve", "cancel", "cancel",
             "release", "release", "revert", "assign", "close", "warp", "warp"]
    for _ in range(WALK_N):
        live = [k for k in orders if c.data(k) is not None]
        kind = rng.choice(kinds)
        if kind == "fund" or not live:
            amount, n = rng.randrange(5 * USDC, 120 * USDC), issue()
            if rng.random() < 0.5:
                ix = c.fund_wallet_ix(n, amount, work_s=rng.choice([2 * DAY, 6 * DAY]), options=options(amount))
                done["funded"] += step(ix.accounts[1].pubkey, lambda: c.send([ix], c.funder))
            else:
                tok = c.fund_token(n, amount, work=rng.choice([2 * DAY, 6 * DAY]), options=options(amount))
                ix = c.fund_balance_ix(tok, n)
                done["funded"] += step(ix.accounts[7].pubkey, lambda: c.send([ix]))
                markers.append((pay.used_pda(c.data(tok)), None))
            continue
        if kind == "warp":
            c.warp(rng.choice([3600, DAY]))
            assert c.refresh(oidc.GITHUB, c.github, c.attest(oidc.GITHUB, c.github)), c.err     # GitHub's key stays good
            continue
        if kind == "close":
            if markers:
                marker, of = markers[rng.randrange(len(markers))]
                ok = step(None, lambda: c.send([pay.close_marker_ix(marker, c.payer.pubkey(), of)]))
                done["closed" if ok else "refused"] += 1
                assert ok == (c.data(marker) is None)
                if ok:
                    markers.remove((marker, of))
            continue
        # the rarer moves look for an order they can apply to
        t = c.now()
        wanted = {"release": [lambda o: o.state == "warranty"], "revert": [lambda o: o.state == "warranty"], "settle": [lambda o: o.state == "held"],
                  "cancel": [lambda o: o.state == "open" and not o.cancel_at and o.reserved_until >= t and o.kill_bps, lambda o: o.state == "open" and not o.cancel_at],
                  "reserve": [lambda o: o.state == "open" and o.reserve_days > 0 and not o.cancel_at],
                  "pay": [lambda o: o.state == "open" and o.deadline >= t],
                  "refund": [lambda o: pay.kill_fee(o) and o.deadline < t, lambda o: o.state == "open" and o.deadline < t]}.get(kind, [])
        fit = next((f for f in ([k for k in live if want(c.order(k))] for want in wanted) if f), live)
        order = rng.choice(fit)
        o = c.order(order)
        if kind == "pay":
            chosen = rng.sample(people, rng.randrange(1, 5)) if rng.random() < 0.8 else [people[rng.randrange(4, 6)]]
            cuts = sorted(rng.sample(range(1, 10_000), len(chosen) - 1))
            shares = [b - a for a, b in zip([0, *cuts], [*cuts, 10_000])]
            payees = [(who, bps, k.pubkey() if rng.random() < 0.5 else None) for (who, k), bps in zip(chosen, shares)]
            pr = rng.randrange(1, 7)
            ok = step(order, lambda: pay_pr(c, order, payees, pr=pr))
            now = c.order(order) if c.data(order) is not None else None
            if ok and o.flags & pay.F_STANDING:
                markers.append((pay.done_pda(order, pr), order))
                assert c.data(pay.done_pda(order, pr)) is not None
            if ok and now is not None and now.state == "held":
                done["held"] += 1
            elif ok and now is not None and now.state == "warranty":
                done["warranty"] += 1
                assert sum(x for _, _, x in hb_of(c, order).payees) == now.amount - now.paid > 0
            elif ok and now is not None:
                done["standing"] += 1
                assert o.flags & pay.F_STANDING and (now.amount, now.paid) == (o.amount - o.rate, 0) and c.held(order) >= now.amount + now.fee
            else:
                done["paid" if ok else "refused"] += 1
        elif kind == "top":
            add = rng.randrange(1, 50 * USDC)
            signer = c.owner if o.from_balance else c.funder
            done["topped"] += step(order, lambda: c.send([pay.top_up_ix(signer.pubkey(), order, o, add)], signer))
        elif kind == "dust":
            done["dust"] += step(order, lambda: (transfer(c, c.owner_tok, pay.ov_pda(order), rng.randrange(1, 1000), c.owner), True)[1])
        elif kind == "refund":
            kill, kt = pay.kill_fee(o), None
            taker = pay.read_bind(c.data(pay.bind_pda(o.reserved_by))) if kill else None
            if taker is not None and rng.random() < 0.7:
                kt = c.token_account(taker.wallet, c.usdc)
            ok = step(order, lambda: refund(c, order, kt))
            done["refunded" if ok else "refused"] += 1
            done["kill"] += bool(ok and kill)
            if ok and kill and kt is None:
                assert c.order(order).state == "held" and c.held(order) == kill
        elif kind == "settle":
            if o.state == "held":
                who = o.payee_id
                if pay.read_bind(c.data(pay.bind_pda(who))) is None and rng.random() < 0.5:
                    assert c.bind(who, key_of[who].pubkey()), c.err
                to = wallets(c, order, [(who, 10_000, None)])[0][1]
                if to is not None:
                    done["settled"] += step(order, lambda: c.send([pay.settle_order_ix(c.payer.pubkey(), order, o, to)]))
        elif kind == "reserve":
            ok = step(order, lambda: reserve(c, order, rng.choice(people)[0], rng.choice([1, 2, 3]), repository_id=o.repo_id))
            done["reserved" if ok else "refused"] += 1
        elif kind == "cancel":
            ok = step(order, lambda: cancel(c, order))
            done["cancelled" if ok else "refused"] += 1
        elif kind == "release":
            if o.state == "warranty":
                ok = step(order, lambda: release(c, order))
                done["released" if ok else "refused"] += 1
        elif kind == "revert":
            if o.state == "warranty":
                ok = step(order, lambda: revert(c, order))
                done["reverted" if ok else "refused"] += 1
        elif kind == "assign":
            who, k = rng.choice(people)
            ok = step(order, lambda: c.send([pay.assign_ix(k.pubkey(), order, who, lender)], signers=[k]))
            done["assigned" if ok else "refused"] += 1
        # every order: what entered it is what left it plus what it holds; a closed order holds nothing and leaves no record
        for k, book in orders.items():
            holds = c.held(k) if c.data(k) is not None else 0
            assert book["entered"] == book["left"] + holds, (k, book, holds)
            if c.data(k) is None:
                assert c.data(pay.ov_pda(k)) is None and c.data(pay.hb_pda(k)) is None
            else:
                x = c.order(k)
                assert holds >= x.amount - x.paid + x.fee - x.fee * x.paid // x.amount, (k, x, holds)
                assert (x.state == "warranty") == (c.data(pay.hb_pda(k)) is not None)
        # and nothing was made or lost anywhere
        assert total() + sum(c.held(k) for k in orders if c.data(k) is not None) == everything
    for name in () if (WALK_N, WALK_SEED) != (500, 313) else ("paid", "held", "settled", "refunded", "topped", "reserved", "cancelled", "released", "reverted", "assigned", "closed", "kill", "warranty",
                 "standing"):
        assert done[name] > 0, f"{name}: {done}"
    assert done["funded"] > 5, done


@pytest.fixture(scope="module")
def chain():
    return OrderChain()
