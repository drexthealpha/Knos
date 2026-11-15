"""An AUTO order pays the first pull request its black-box suite passes, with nobody's merge, and a payment inside
its warranty can be challenged by anyone who runs the pinned judge again (knos_pay 2.1: order_judge.rs judge e,
order_terms.rs Revert), in LiteSVM. The harness is tests/_order.py. Each rule has the payment it allows and, beside
it, every way round it that is refused."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import DAY, HEAD, OWNER, REPO, SUITE, TERMS, USDC, OrderChain, code, issue, user  # noqa: E402

from knos.settle.v2 import order_auto, pay  # noqa: E402

AUTO = order_auto.F_AUTO
TERMS_REFUSED, STATE, CLAIMS, WORKFLOW, AUD, REPLAY, NO_ORDER = 81, 83, 85, 86, 87, 91, 101    # lib.rs E_*
FEE = pay.order_fee(20 * USDC)


@pytest.fixture(scope="module")
def chain():
    return OrderChain()


def paid_to(c: OrderChain, wallet: Pubkey) -> int:
    return c.balance(pay.ata(wallet, c.usdc))


def reserve(c: OrderChain, order: Pubkey, taker: int, days: int) -> bool:
    tok = c.gh(pay.take_audience(order, taker, days), repository_id=REPO, actor_id=taker)
    return c.send([pay.reserve_ix(c.payer.pubkey(), tok, c.key, order)])


def revert(c: OrderChain, order: Pubkey, tok=None, **claims) -> bool:
    tok = tok or c.gh(pay.revert_audience(order, HEAD), **claims)
    return c.send([pay.revert_ix(c.payer.pubkey(), tok, c.key, order, c.order(order), pay.read_holdback(c.data(pay.hb_pda(order))))], tag="challenge")


def release(c: OrderChain, order: Pubkey) -> bool:
    return c.send([pay.release_ix(c.payer.pubkey(), order, c.order(order), pay.read_holdback(c.data(pay.hb_pda(order))))])


# == 1. auto-accept ===================================================================================================
def test_the_first_pull_request_the_suite_passes_is_paid_with_no_merge_and_the_second_finds_the_order_closed(chain):
    c = chain
    order = c.fund_auto()
    o = c.order(order)
    assert (o.mode, o.flags & AUTO, o.state) == (pay.TESTS, AUTO, "open")
    first, second, w1, w2 = user(), user(), Keypair().pubkey(), Keypair().pubkey()
    late = c.auto_token(order, second, w2, pr=8, head="b" * 40)          # two pull requests passed; this one is relayed second
    assert c.auto(order, first, w1), c.err
    assert paid_to(c, w1) == 20 * USDC and c.order(order) is None and c.held(order) == 0
    assert c.said("knos3:settled")[0].endswith("judge=4") and c.said("knos3:paid")[0].startswith(f"knos3:paid order={order} pr=7 payee={first} ")
    assert not c.send([c.pay_ix(order, late, [(second, 10_000, w2)], o)]) and code(c) == NO_ORDER
    assert paid_to(c, w2) == 0
    # with a holdback the order stays, in its warranty, and is as closed to a second pull request
    kept = c.fund_auto(holdback_bps=2500, warranty_days=10)
    assert c.auto(kept, first, w1), c.err
    assert c.order(kept).state == "warranty" and paid_to(c, w1) == 35 * USDC
    assert not c.auto(kept, second, w2, pr=8) and code(c) == STATE and paid_to(c, w2) == 0


def test_an_author_without_a_wallet_is_held_for_and_a_merge_still_pays_an_auto_order(chain):
    c = chain
    order, author = c.fund_auto(), user()
    assert c.auto(order, author, None), c.err
    o = c.order(order)
    assert (o.state, o.payee_id) == ("held", author) and c.held(order) == 20 * USDC + FEE
    wallet = Keypair().pubkey()
    assert c.bind(author, wallet) and c.settle(order, wallet), c.err
    assert paid_to(c, wallet) == 20 * USDC and c.order(order) is None
    # the order's own judge after a merge (a pay token) is still a judge of an AUTO order
    merged, w = c.fund_auto(), Keypair().pubkey()
    assert c.pay(merged, [(author, 10_000, w)]), c.err
    assert paid_to(c, w) == 20 * USDC and c.said("knos3:settled")[0].endswith("judge=0")


def test_auto_is_the_funders_choice_at_funding_and_only_on_the_black_box_suite(chain):
    c = chain
    # merge mode has no suite to pay by: a wallet's order and a Balance's are both refused
    for mode, terms in ((pay.MERGE, TERMS), (pay.MERGE, SUITE)):
        assert not c.send([c.fund_wallet_ix(issue(), mode=mode, terms=terms, options=pay.opts(AUTO))], c.funder) and code(c) == TERMS_REFUSED
    n = issue()
    tok = c.fund_token(n, mode=pay.MERGE, options=pay.opts(AUTO))
    assert not c.send([c.fund_balance_ix(tok, n)]) and code(c) == TERMS_REFUSED
    # not a standing order (the first passing pull request closes it), not a private one (no public pull request)
    for options in (pay.opts(AUTO | pay.F_STANDING, rate=5 * USDC), pay.opts(AUTO | pay.F_PRIVATE, judge_repo_id=31_313_131, salted=True)):
        assert not c.send([c.fund_wallet_ix(issue(), mode=pay.TESTS, terms=SUITE, options=options)], c.funder) and code(c) == TERMS_REFUSED
    # a comment funds one from a Balance: the option is in the audience GitHub signed
    order = c.fund_balance(mode=pay.TESTS, terms=SUITE, options=pay.opts(AUTO))
    author, w = user(), Keypair().pubkey()
    assert c.order(order).flags & AUTO and c.auto(order, author, w) and paid_to(c, w) == 20 * USDC, c.err
    # an order funded without it takes no such token, whoever signs it: its funder waits for the repository's own word
    for plain in (c.fund_wallet(mode=pay.TESTS, terms=SUITE), c.fund_wallet(mode=pay.TESTS, terms=SUITE, options=pay.opts(pay.F_NEUTRAL))):
        assert not c.auto(plain, author, w) and code(c) == CLAIMS
        assert c.held(plain) == 20 * USDC + FEE


def test_what_an_unmerged_payment_cannot_do(chain):
    c = chain
    judge_repo = 31_313_131
    order = c.fund_auto(flags=pay.F_NEUTRAL, judge_repo_id=judge_repo)
    author, other, w = user(), user(), Keypair().pubkey()
    for over, want in [
            (dict(repository_id=REPO + 1), CLAIMS),                      # another repository's run
            (c.neutral(author), CLAIMS),                                 # a neutral run pays unmerged work for nobody: only the order's own suite
            (c.neutral(OWNER, REPO), WORKFLOW),                          # attest.yml in the order's own repository is not its prove.yml
            (dict(repository_id=judge_repo), CLAIMS),                    # nor the judge repository
            (dict(file="fund.yml"), WORKFLOW), (dict(wf_sha="d" * 40), WORKFLOW), (dict(wf_repo="evil/Knos"), WORKFLOW),   # the pinned suite at the pinned commit
            (dict(run_attempt=2), CLAIMS),
            (dict(terms=pay.terms_hash(TERMS)), AUD),                    # other terms: other checks, other path limits
            (dict(runner_environment="self-hosted"), CLAIMS)]:
        assert not c.auto(order, author, w, **over) and code(c) == want, (over, c.err)
    o = c.order(order)
    for aud in (order_auto.auto_audience(order, HEAD, o.terms, 7, author, w).replace(":1:7:", ":0:7:"),               # merge mode
                f"knos3:auto:{order}:{HEAD}:{o.terms.hex()}:1:7:{author}.5000.{w},{other}.5000.{w}",                  # a split: one author is paid
                order_auto.auto_audience(Keypair().pubkey(), HEAD, o.terms, 7, author, w),                            # another order
                f"knos3:auto:{order}:zz:{o.terms.hex()}:1:7:{author}.10000.{w}"):                                      # no head commit
        assert not c.send([c.pay_ix(order, c.gh(aud, repository_id=REPO), [(author, 10_000, w)])]) and code(c) == AUD, aud
    assert c.held(order) == 20 * USDC + FEE and paid_to(c, w) == 0
    # a verdict made before the order was funded says nothing about it
    n = issue()
    first = pay.order_pda(pay.scope_of(REPO, n), c.funder.pubkey())
    early = c.gh(order_auto.auto_audience(first, HEAD, pay.terms_hash(SUITE), 7, author, w), repository_id=REPO, event_name="workflow_run")
    c.warp(60)
    assert c.fund_auto(n) == first
    assert not c.send([c.pay_ix(first, early, [(author, 10_000, w)])]) and code(c) == STATE
    # past the deadline the money is the funder's again
    gone = c.fund_auto(work_s=3600)
    c.warp(3601)
    assert not c.auto(gone, author, w) and code(c) == STATE
    # single use: the token that paid does not pay the order a later funding puts at the same address
    paid = c.auto_token(first, author, w)
    assert c.send([c.pay_ix(first, paid, [(author, 10_000, w)])], tag="pay_order_auto") and c.order(first) is None, c.err
    assert c.fund_auto(n) == first
    assert not c.send([c.pay_ix(first, paid, [(author, 10_000, w)])]) and code(c) == REPLAY
    assert c.held(first) == 20 * USDC + FEE and paid_to(c, w) == 20 * USDC


def test_a_reserved_auto_order_pays_only_its_taker_until_the_reservation_ends(chain):
    c = chain
    order = c.fund_auto(reserve_days=3)
    taker, other, wt, wo = user(), user(), Keypair().pubkey(), Keypair().pubkey()
    assert reserve(c, order, taker, 2), c.err
    assert not c.auto(order, other, wo) and code(c) == CLAIMS and paid_to(c, wo) == 0
    assert c.auto(order, taker, wt) and paid_to(c, wt) == 20 * USDC, c.err
    # once the reservation has run out the order is anyone's again
    free = c.fund_auto(reserve_days=3)
    assert reserve(c, free, taker, 1), c.err
    assert not c.auto(free, other, wo) and code(c) == CLAIMS
    c.warp(DAY + 1)
    assert c.auto(free, other, wo) and paid_to(c, wo) == 20 * USDC, c.err


# == 2. challenge =====================================================================================================
def test_a_strangers_neutral_failing_run_inside_the_window_stops_the_release_and_after_it_does_not():
    """The review window of a payment is the order's warranty: the holdback waits in the order. A stranger who runs
    the pinned judge again (attest.yml, by hand, in a repository of his own) and finds that the paid head fails the
    terms sends its token: everything the order still holds goes back to the funder (Revert). No bond: the token is
    GitHub's signature over the pinned file's own verdict, so nobody can make one for a head that passes."""
    c = OrderChain()
    author, w, stranger = user(), Keypair().pubkey(), user()
    hit, kept, strict = (c.fund_auto(flags=f, holdback_bps=2500, warranty_days=10) for f in (pay.F_NEUTRAL, pay.F_NEUTRAL, 0))
    before = c.gh(pay.revert_audience(hit, HEAD), **c.neutral(stranger))        # a verdict older than the payment is not about it
    c.warp(5)
    for k in (hit, kept, strict):
        assert c.auto(k, author, w), c.err
    held = 5 * USDC + FEE // 4
    assert paid_to(c, w) == 45 * USDC and [c.held(k) for k in (hit, kept, strict)] == [held] * 3
    funder0 = c.balance(c.funder_tok)
    # what is not a challenge: an old verdict, a run nobody answers for, another file, another commit, a re-run
    assert not revert(c, hit, tok=before) and code(c) == STATE
    c.warp(DAY)
    for over, want in ((dict(event_name="push"), CLAIMS), (dict(repository_owner_id=user()), CLAIMS), (dict(run_attempt=2), CLAIMS),
                       (dict(file="prove.yml"), WORKFLOW), (dict(wf_sha="d" * 40), WORKFLOW), (dict(wf_repo="evil/Knos"), WORKFLOW)):
        assert not revert(c, hit, **{**c.neutral(stranger), **over}) and code(c) == want, over
    assert not revert(c, hit, tok=c.auto_token(hit, author, w)) and code(c) == CLAIMS          # a passing verdict challenges nothing
    # an order whose funder did not allow a neutral run is challenged only from its own repository
    assert not revert(c, strict, **c.neutral(stranger)) and code(c) == CLAIMS
    assert c.balance(c.funder_tok) == funder0
    # the challenge: the release is stopped, the funder has the holdback and its fee, what was paid stays paid
    assert not release(c, hit) and code(c) == STATE                                           # the window is still open
    assert revert(c, hit, **c.neutral(stranger)), c.err
    assert c.said("knos3:reverted") == [f"knos3:reverted order={hit} amount={held} head={HEAD}"]
    assert c.balance(c.funder_tok) == funder0 + held and paid_to(c, w) == 45 * USDC
    assert all(c.data(x) is None for x in (hit, pay.ov_pda(hit), pay.hb_pda(hit)))
    print("\nCU of a challenge (Revert on a neutral run's token):", c.cu["challenge"][-1])
    # after the window the same run stops nothing: the holdback is the author's
    c.warp(9 * DAY + 1)
    assert not revert(c, kept, **c.neutral(stranger)) and code(c) == STATE
    assert release(c, kept) and release(c, strict), c.err
    assert paid_to(c, w) == 55 * USDC and c.balance(c.funder_tok) == funder0 + held


def test_compute_units_of_an_unmerged_payment(chain):
    if not chain.cu.get("pay_order_auto"):     # run alone (or on another worker): make the payment this measures
        test_what_an_unmerged_payment_cannot_do(chain)
    cu = chain.cu["pay_order_auto"]
    print("\nCU of PayOrder on an auto token:", min(cu), "to", max(cu))
    assert max(cu) < 200_000
