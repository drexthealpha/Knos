"""Graduation in the Solana runtime (LiteSVM, the knos_pay 2.2 test build): a verdict that passed opens a milestone
vault and a pre-order pool as private knos_pay orders; the pool is read back from the chain and handed to the
referee's demand book; the vault pays the contributor split (fees.yaml splits) to four payees in one transaction,
with the fee leaving for the treasury and the relayer exactly as the program divides it; a pre-order nobody
delivers is refunded with its fee. And everything a plan refuses."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402

from _order import USDC, OrderChain, user  # noqa: E402
from _pay2 import ChainLedger, WF_SHA  # noqa: E402

from knos import graduation, splits  # noqa: E402
from knos.money import fees_config  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

JUDGE_REPO = 31_415_926
PASSED = {"passed": True, "spec_hash": "ab" * 32, "checks": {}}


@pytest.fixture(scope="module")
def chain():
    return OrderChain()


def contributors(ids, wallets=None):
    roles = ("researcher", "agent", "lab", "referee")
    return [{"role": r, "github_id": i, **({"address": str(w)} if wallets and w else {})} for r, i, w in zip(roles, ids, wallets or [None] * 4)]


def _plan(claim: str, amount: int = 100 * USDC + 3, ids=None, **kw):
    ids = ids or [user() for _ in range(4)]
    return graduation.plan(PASSED, claim_id=claim, repo_id=JUDGE_REPO, amount=amount, contributors=contributors(ids), wf_sha=WF_SHA, **kw), ids


def test_a_passing_verdict_opens_an_escrow_that_pays_the_split_and_the_treasury(chain):
    c, cfg = chain, fees_config.load()
    p, ids = _plan("claim-escrow")
    fee_before, tip_before, funder_before = c.balance(c.fee), c.balance(c.tip), c.balance(c.funder_tok)
    ix = graduation.escrow_ix(p, c.funder.pubkey(), c.funder_tok, c.usdc)
    assert c.send([ix], c.funder, tag="graduation_escrow"), c.err
    order = graduation.address(p, "escrow", c.funder.pubkey())
    o = c.order(order)
    # a private order: no repository, no issue; the plan's scope and terms hash; the judge is the research repository
    assert (o.repo_id, o.issue, o.flags & pay.F_PRIVATE, o.judge_repo_id) == (0, 0, pay.F_PRIVATE, JUDGE_REPO)
    assert o.scope.hex() == p["escrow"]["scope"] and o.terms.hex() == p["escrow"]["terms_hash"]
    assert (o.amount, o.fee) == (p["escrow"]["amount"], p["escrow"]["payout_fee"]) == (100 * USDC + 3, cfg.fee("payout", 100 * USDC + 3))
    assert funder_before - c.balance(c.funder_tok) == p["escrow"]["funder_pays"]
    assert graduation.escrow(ChainLedger(c), p, str(c.usdc))["locked"] == 100 * USDC + 3
    # the judge's token pays the four contributors the split of fees.yaml, in one transaction
    wallets = [Keypair().pubkey() for _ in ids]
    payees = [(i, b, w) for (i, b, _), w in zip(p["payees"], wallets)]
    assert [b for _, b, _ in payees] == [b for _, b in cfg.shares()]
    assert c.pay(order, payees, repository_id=JUDGE_REPO, tag="graduation_payout"), c.err
    got = [c.balance(pay.ata(w, c.usdc)) for w in wallets]
    assert got == [s["amount"] for s in p["split"]] and sum(got) == 100 * USDC + 3
    # the fee: the relayer's tip, the rest to the treasury (the fee owner's account), as billing.release_split says
    paid_fee = (c.balance(c.fee) - fee_before) + (c.balance(c.tip) - tip_before)
    assert paid_fee == o.fee and c.data(order) is None


def test_the_pool_is_read_from_the_chain_and_counted_by_the_demand_book(chain):
    c = chain
    p, _ = _plan("claim-pool", min_buyers=2, min_locked=30 * USDC, pool_work_s=120)
    led = ChainLedger(c)
    assert graduation.pool(led, p, str(c.usdc)) == {"mint": str(c.usdc), "orders": [], "ignored": [], "buyers": 0, "locked": 0, "fees_held": 0,
                                                    "bar": {"min_buyers": 2, "min_locked": 30 * USDC, "met": False}}
    buyers = [c.wallet(c.usdc, 100 * USDC) for _ in range(2)]
    for k, (b, tok) in enumerate(buyers):
        assert c.send([graduation.preorder_ix(p, b.pubkey(), tok, c.usdc, (10 + 10 * k) * USDC)], b, tag="graduation_preorder"), c.err
    # the same buyer twice is one buyer
    b0, tok0 = buyers[0]
    assert c.send([graduation.preorder_ix(p, b0.pubkey(), tok0, c.usdc, 5 * USDC, seq=1)], b0), c.err
    s = graduation.pool(led, p, str(c.usdc))
    assert (s["buyers"], s["locked"], s["bar"]["met"]) == (2, 35 * USDC, True)
    assert s["fees_held"] == sum(fees_config.load().fee("payout", a) for a in (10 * USDC, 20 * USDC, 5 * USDC))
    demand = graduation.demand_orders(p, s)
    assert sorted(d["amount"] for d in demand) == [5 * USDC, 10 * USDC, 20 * USDC]
    assert {d["buyer"] for d in demand} == {str(b.pubkey()) for b, _ in buyers} and all(d["status"] == "locked" for d in demand)
    # an order of another claim is not in this pool
    other, _ = _plan("claim-other", pool_work_s=120)
    assert c.send([graduation.preorder_ix(other, b0.pubkey(), tok0, c.usdc, 5 * USDC)], b0), c.err
    assert graduation.pool(led, p, str(c.usdc))["locked"] == 35 * USDC
    # nobody delivers: past the deadline the pool no longer counts, and each buyer gets the amount AND the fee back
    before = c.balance(tok0)
    c.warp(121 + pay.CLOCK_SLACK)
    assert graduation.pool(led, p, str(c.usdc))["bar"]["met"] is False
    order = graduation.address(p, "pool", b0.pubkey())
    o = c.order(order)
    assert c.send([graduation.refund_ix(c.payer.pubkey(), order, o)], tag="graduation_refund"), c.err
    assert c.balance(tok0) - before == o.amount + o.fee and c.data(order) is None


def test_a_plan_refuses_what_must_not_graduate():
    ids = [11, 12, 13, 14]
    ok = dict(claim_id="c", repo_id=JUDGE_REPO, amount=20 * USDC, contributors=contributors(ids))
    for verdict in ({"passed": False, "spec_hash": "a"}, {"passed": "yes", "spec_hash": "a"}, {"spec_hash": "a"}, None, {"passed": True}):
        with pytest.raises(graduation.GraduationError):
            graduation.plan(verdict, **ok)
    bad = [dict(amount=4 * USDC), dict(repo_id=0), dict(claim_id=""), dict(contributors=[]),
           dict(contributors=contributors([11, 11])), dict(contributors=[{"role": "investor", "github_id": 3}]),
           dict(contributors=[{"role": "agent", "github_id": 3}, {"role": "agent", "github_id": 4}]), dict(work_s=10)]
    for over in bad:
        with pytest.raises(graduation.GraduationError):
            graduation.plan(PASSED, **{**ok, **over})


def test_the_split_follows_the_config_and_absent_roles_leave_their_share():
    cfg = fees_config.load()
    two = splits.payees([{"role": "agent", "github_id": 2}, {"role": "researcher", "github_id": 1}], cfg)
    assert [i for i, _, _ in two] == [1, 2] and sum(b for _, b, _ in two) == 10_000
    r, a = cfg.roles["researcher"], cfg.roles["agent"]
    assert two[1][1] == a * 10_000 // (r + a)
    for amount in (5 * USDC, 5 * USDC + 1, 99_999_999_999, 7 * USDC + 3):
        got = splits.amounts(amount, contributors([1, 2, 3, 4]), cfg)
        assert sum(x for _, _, x in got) == amount
        assert [x for _, _, x in got[:-1]] == [amount * b // 10_000 for b in list(cfg.roles.values())[:-1]]


def test_fake_demand_in_the_pools_public_scope_is_never_counted(chain):
    """Finding 24: the scope is public, so anyone can fund orders in it. Only the plan's own orders in the accepted
    mint count: a worthless mint, other terms, other pinned workflows or a public order are listed as ignored."""
    c = chain
    p, _ = _plan("claim-fake", min_buyers=1, min_locked=5 * USDC)
    led = ChainLedger(c)
    junk = c.new_mint()
    w, wtok = c.wallet(junk, 1_000_000 * USDC)
    assert c.send([graduation.preorder_ix(p, w.pubkey(), wtok, junk, 90_000 * USDC)], w), c.err          # a worthless mint
    o2 = dict(p, pool=dict(p["pool"], terms_hash=pay.terms_hash(b"{}").hex()))
    w2, w2tok = c.wallet(c.usdc, 100 * USDC)
    assert c.send([graduation.preorder_ix(o2, w2.pubkey(), w2tok, c.usdc, 50 * USDC)], w2), c.err          # other terms
    o3 = dict(p, wf_sha="d" * 40)
    assert c.send([graduation.preorder_ix(o3, w2.pubkey(), w2tok, c.usdc, 5 * USDC, seq=1)], w2), c.err    # other workflows
    s = graduation.pool(led, p, str(c.usdc))
    assert (s["buyers"], s["locked"], s["bar"]["met"]) == (0, 0, False)
    assert sorted(i["why"].split(" ")[0] for i in s["ignored"]) == ["mint", "other", "other"]
    assert graduation.pool(led, p, str(junk))["locked"] == 90_000 * USDC     # only a caller who accepts that mint counts it
