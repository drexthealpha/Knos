"""An order with a quorum pays only when 2 or 3 DISTINCT judges have passed the same artifact (knos_pay 2.1,
order_terms.rs section 5), in LiteSVM: a the order's own repository, b a neutral run, c the judge repository. Each
judge before the last leaves a marker ["q", order, kind]; the last one pays. The harness is tests/_order.py."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import HEAD, MAINT, OWNER, REPO, USDC, OrderChain, code, issue, swap, user  # noqa: E402

from knos.settle.v2 import order_auto, pay  # noqa: E402

ACCOUNTS, TERMS_REFUSED, STATE, CLAIMS, REPLAY = 80, 81, 83, 85, 91      # lib.rs E_*
JUDGE_REPO = 31_313_131
FEE = pay.order_fee(20 * USDC)
Q2 = pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(2))


@pytest.fixture(scope="module")
def chain():
    return OrderChain()


def paid_to(c: OrderChain, wallet: Pubkey) -> int:
    return c.balance(pay.ata(wallet, c.usdc))


def present(c: OrderChain, order: Pubkey, payees, tag: str | None = None, **over) -> bool:
    """One judge's pay token for these payees arrives: the order's own prove.yml unless `over` names another run."""
    return c.send([c.pay_ix(order, c.pay_token(order, payees, **over), payees)], tag=tag)


def test_two_distinct_judges_pay_and_two_tokens_of_one_kind_count_once(chain):
    c = chain
    order = c.fund_wallet(options=Q2)
    author, w = user(), Keypair().pubkey()
    payees, art = [(author, 10_000, w)], order_auto.artifact(pay.order_pay_audience(order, HEAD, c.order(order).terms, 0, 7, [(author, 10_000, w)]))
    # a: the buyer's own run passes it. Nothing is paid; its word is recorded
    assert present(c, order, payees, tag="quorum_first"), c.err
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=0 have=1 of=2"]
    since = c.order(order).not_before
    assert c.quorum(order) == {0: (0, c.payer.pubkey(), order, since, art), 1: None, 2: None}
    assert c.held(order) == 20 * USDC + FEE and paid_to(c, w) == 0
    # the same judge again, with a new token: one judge is one judge
    assert present(c, order, payees), c.err
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=0 have=1 of=2"] and paid_to(c, w) == 0
    assert c.order(order).state == "open" and c.quorum(order)[1] is None
    # its marker cannot be closed while the order is open
    close = pay.close_marker_ix(order_auto.q_pda(order, 0), c.payer.pubkey(), order)
    assert not c.send([close]) and code(c) == STATE
    # b: a neutral run, started by hand by the seller in a repository of his own, passes the same artifact: paid
    assert present(c, order, payees, tag="quorum_last", **c.neutral(author)), c.err
    assert paid_to(c, w) == 20 * USDC and c.order(order) is None and c.said("knos3:settled")[0].endswith("judge=1")
    assert c.quorum(order)[1] is None                                    # the last judge leaves no marker
    # the first judge's marker is of no use now: its rent goes back to who paid it
    rent, before = c.lamports(order_auto.q_pda(order, 0)), c.lamports(c.payer.pubkey())
    assert not c.send([swap(close, 1, Keypair().pubkey())]) and code(c) == ACCOUNTS
    assert c.send([close]) and c.data(order_auto.q_pda(order, 0)) is None, c.err
    assert rent > 0 and c.lamports(c.payer.pubkey()) > before
    print("\nCU of PayOrder on an order with a quorum: first judge", c.cu["quorum_first"][-1], "last judge", c.cu["quorum_last"][-1])


def test_the_judges_may_come_in_any_order_and_must_pass_the_same_artifact(chain):
    c = chain
    order = c.fund_wallet(options=Q2)
    author, other, w = user(), user(), Keypair().pubkey()
    payees = [(author, 10_000, w)]
    assert present(c, order, payees, **c.neutral(author)), c.err          # the seller first
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=1 have=1 of=2"]
    # the buyer's run passes something else: another commit, another pull request, another payee. None of them is the seller's artifact
    for over, who in ((dict(head_sha="b" * 40), payees), (dict(pr=8), payees), ({}, [(other, 10_000, w)])):
        assert present(c, order, who, **over), c.err
        assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=0 have=1 of=2"] and paid_to(c, w) == 0, over
    # the seller's run passes what the buyer's passed last: now they agree
    assert present(c, order, [(other, 10_000, w)], **c.neutral(author)), c.err
    assert paid_to(c, w) == 20 * USDC and c.order(order) is None and c.said("knos3:paid")[0].split()[3] == f"payee={other}"


def test_a_quorum_of_three_needs_the_judge_repository_too(chain):
    c = chain
    order = c.fund_wallet(options=pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(3), judge_repo_id=JUDGE_REPO))
    author, w = user(), Keypair().pubkey()
    payees = [(author, 10_000, w)]
    assert present(c, order, payees) and present(c, order, payees, **c.neutral(author)), c.err
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=1 have=2 of=3"] and paid_to(c, w) == 0
    assert present(c, order, payees, repository_id=JUDGE_REPO, file="attest.yml", event_name="push"), c.err
    assert paid_to(c, w) == 20 * USDC and c.said("knos3:settled")[0].endswith("judge=2")
    # two of three, when two are asked: the judge repository and the buyer's own run, with no neutral run at all
    two = c.fund_wallet(options=pay.opts(order_auto.quorum_flags(2), judge_repo_id=JUDGE_REPO))
    assert present(c, two, payees, repository_id=JUDGE_REPO) and paid_to(c, w) == 20 * USDC, c.err
    assert not present(c, two, payees, **c.neutral(author)) and code(c) == CLAIMS          # this order allows no neutral run
    assert present(c, two, payees) and paid_to(c, w) == 40 * USDC, c.err


def test_an_auto_orders_unmerged_run_is_the_buyers_judge_of_a_quorum(chain):
    c = chain
    order = c.fund_auto(flags=pay.F_NEUTRAL, quorum=2)
    author, w = user(), Keypair().pubkey()
    assert c.auto(order, author, w, tag=None), c.err                      # the suite passed in the buyer's repository, unmerged
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=0 have=1 of=2"] and paid_to(c, w) == 0
    assert present(c, order, [(author, 10_000, w)], **c.neutral(author)), c.err      # and in a neutral run: the same head, pull request, payee
    assert paid_to(c, w) == 20 * USDC and c.order(order) is None


def test_what_a_quorum_refuses(chain):
    c = chain
    # at funding: 2 or 3, no more than the judges the order can have, on a public order that is not standing
    for options in (pay.opts(order_auto.quorum_flags(2)), pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(3)), pay.opts(pay.F_NEUTRAL | 64),
                    pay.opts(order_auto.quorum_flags(3), judge_repo_id=JUDGE_REPO),
                    pay.opts(pay.F_NEUTRAL | pay.F_STANDING | order_auto.quorum_flags(2), rate=5 * USDC),
                    pay.opts(pay.F_PRIVATE | pay.F_NEUTRAL | order_auto.quorum_flags(2), judge_repo_id=JUDGE_REPO, salted=True)):
        assert not c.send([c.fund_wallet_ix(issue(), options=options)], c.funder) and code(c) == TERMS_REFUSED, options.hex()
    order, funded = c.fund_wallet(options=Q2), c.fund_balance(options=Q2)
    author, w = user(), Keypair().pubkey()
    payees = [(author, 10_000, w)]
    # a neutral run is a third party's: not one in the order's own repository, not one its funder or his Balance's owner started
    assert not present(c, order, payees, **c.neutral(OWNER, REPO)) and code(c) == CLAIMS
    for who in (MAINT, OWNER):
        assert not present(c, funded, payees, **c.neutral(who)) and code(c) == CLAIMS
    # the three markers are named, each at its own address: none left out, none counted as another, none hidden
    tok = c.pay_token(order, payees)
    ix = c.pay_ix(order, tok, payees)
    bare = pay.pay_order_ix(c.payer.pubkey(), tok, c.key, order, c.order(order), c.wallets(payees))
    assert not c.send([bare]) and code(c) == ACCOUNTS
    n = len(ix.accounts)
    assert not c.send([swap(ix, n - 2, order_auto.q_pda(order, 0))]) and code(c) == ACCOUNTS
    assert c.send([ix]), c.err
    assert not c.send([ix]) and code(c) == REPLAY                         # a token is used once, presented or paid
    last = c.pay_ix(order, c.pay_token(order, payees, **c.neutral(author)), payees)
    for at, key in ((n - 3, Keypair().pubkey()), (n - 3, order_auto.q_pda(order, 1)), (n - 1, order_auto.q_pda(order, 0))):
        assert not c.send([swap(last, at, key)]) and code(c) == ACCOUNTS
    assert paid_to(c, w) == 0 and c.held(order) == 20 * USDC + FEE
    assert c.send([last]) and paid_to(c, w) == 20 * USDC, c.err
    # the arbiter both sides accepted decides alone: a ruling waits for no quorum
    arbiter = user()
    ruled = c.fund_wallet(options=pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(2), arbiter_id=arbiter))
    tok = c.gh(pay.rule_audience(ruled, payees), **c.neutral(arbiter))
    assert c.send([c.pay_ix(ruled, tok, payees)]) and paid_to(c, w) == 40 * USDC, c.err


def test_a_marker_of_an_earlier_order_at_the_same_address_counts_for_nothing():
    c = OrderChain()
    n, author, w = issue(), user(), Keypair().pubkey()
    payees = [(author, 10_000, w)]
    order = c.fund_wallet(n, options=Q2, work_s=3600)
    assert present(c, order, payees), c.err                              # the buyer's run passed it, and nobody else did
    c.warp(3601)
    assert c.refund(order) and c.order(order) is None, c.err
    assert c.fund_wallet(n, options=Q2) == order                         # funded again: the same address, a later order
    assert c.quorum(order)[0] is not None
    assert present(c, order, payees, **c.neutral(author)), c.err
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=1 have=1 of=2"] and paid_to(c, w) == 0
    # the stale marker can be closed (its order is not the one it was made for), or is rewritten by the buyer's next run
    assert c.send([pay.close_marker_ix(order_auto.q_pda(order, 0), c.payer.pubkey(), order)]), c.err
    assert present(c, order, payees) and paid_to(c, w) == 20 * USDC, c.err


def test_the_relay_carries_an_unmerged_payment_and_a_quorum_and_takes_its_markers_rent_back():
    """knos.settle.v2.relay with the real programs: a knos3:auto token pays; an order funded without `auto` refuses it
    before any fee; a quorum's first judge is reported as waiting, its last as paid; the marker's rent comes back."""
    from test_relay2 import JWKS, Net, token

    from knos.settle.v2 import relay

    c = OrderChain()
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    net = Net(c)
    author, w = user(), Keypair().pubkey()
    payees = [(author, 10_000, w)]

    def go(aud: str, **claims) -> dict:
        c.warp(1)
        return relay.submit(net, c.payer, token(c, aud, **{"repository_id": REPO, **claims}), None, JWKS, now=c.now())
    order = c.fund_auto()
    terms = c.order(order).terms
    r = go(order_auto.auto_audience(order, HEAD, terms, 7, author, w), event_name="workflow_run")
    assert r["ok"] and (r["kind"], r["auto"], r["pr"]) == ("pay", True, 7) and [p["amount"] for p in r["paid"]] == [20 * USDC], r
    assert paid_to(c, w) == 20 * USDC and c.order(order) is None
    plain, txs = c.fund_auto(auto=False), net.txs
    r = go(order_auto.auto_audience(plain, HEAD, terms, 7, author, w), event_name="workflow_run")
    assert not r["ok"] and "funded without it" in r["why"] and net.txs == txs, r
    # a quorum of two: the buyer's run is recorded and waits, the seller's neutral run pays
    q = c.fund_wallet(options=Q2)
    aud = pay.order_pay_audience(q, HEAD, c.order(q).terms, 0, 7, payees)
    r = go(aud)
    assert r["ok"] and r["paid"] == [] and r["quorum"] == {"have": 1, "of": 2} and paid_to(c, w) == 20 * USDC, r
    assert relay.close_markers(net, c.payer, c.now()) == [] and c.quorum(q)[0] is not None      # the order is open: the marker stays
    r = go(aud, **c.neutral(author))
    assert r["ok"] and [p["amount"] for p in r["paid"]] == [20 * USDC] and "quorum" not in r and paid_to(c, w) == 40 * USDC, r
    assert len(relay.close_markers(net, c.payer, c.now())) == 1 and c.quorum(q)[0] is None
