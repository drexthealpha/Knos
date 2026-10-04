"""knos_pay 2.1 in the Solana runtime (LiteSVM), beside the second deployment's verifier: the four fixes to the 2.0
paths (whole units and counted mints, the Token-2022 allow-list, a Balance's side account, single-use pay tokens),
Version, SetBalanceX, SetPlan, and work orders: funded by a wallet or from a Balance with the fee on top, paid by the
order's own repository to one to four payees, held, settled, topped up, refunded. Every refusal an attacker would
try, and a random walk in which what entered each order equals what left it plus what it holds."""
from __future__ import annotations

import os
import random

import pytest

pytest.importorskip("solders.litesvm")

from solders.account import Account  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import DAY, HEAD, MAINT, OWNER, REPO, TERMS, TH, USDC, OrderChain, code, issue, swap, transfer, user  # noqa: E402
from _pay2 import WF_REPO, WF_SHA  # noqa: E402

from knos.settle.v2 import pay  # noqa: E402

WALK_N = int(os.environ.get("KNOS_FUZZ_N", "120"))   # read at import: conftest clears KNOS_* per test
WALK_SEED = int(os.environ.get("KNOS_FUZZ_SEED", "313"))
NEUTRAL = pay.opts(pay.F_NEUTRAL)
# PayOrder's accounts by position (idl/knos_pay_v2.json): the shared ones, then five per payee
RELAYER, TOKEN_ACC, KEY, ORDER, OV, TIP_TOKEN, FEE_TOKEN, AUTH, RENT_TO, MINT, TOKEN_PROGRAM, SYSTEM, ATA_PROGRAM, BIND, WALLET, DEST, REP, PAIR = range(18)


@pytest.fixture(scope="module")
def chain():
    return OrderChain()


def raw_mint22(c: OrderChain, tlv: bytes, decimals: int = 6) -> Pubkey:
    """A Token-2022 mint account written as it would stand on chain with the given extension list: for extensions the
    local token program cannot create, and for ids nobody has defined yet."""
    base = (1).to_bytes(4, "little") + bytes(c.payer.pubkey()) + bytes(8) + bytes([decimals, 1]) + bytes(36)
    key = Keypair().pubkey()
    c.svm.set_account(key, Account(10 ** 9, base + bytes(165 - 82) + b"\x01" + tlv, pay.TOKEN_2022))
    return key


def ext(kind: int, value: bytes) -> bytes:
    return kind.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value


def job_token(c: OrderChain, job: Pubkey, payee: int, address: Pubkey | None):
    j = pay.read_job(c.data(job))
    return c.gh(pay.pay_audience(j.repo_id, j.issue, payee, HEAD, j.terms, j.mode, address), repository_id=j.repo_id)


def pay_job(c: OrderChain, job: Pubkey, tok: Pubkey, payee: int, wallet: Pubkey) -> bool:
    j = pay.read_job(c.data(job))
    c.token_account(wallet, j.mint); c.token_account(pay.FEE_OWNER, j.mint)
    return c.send([pay.pay_ix(c.payer.pubkey(), tok, c.key, job, j, payee, wallet, used=c.data(tok))])


def fund_job(c: OrderChain, n: int, amount: int, mint: Pubkey | None = None, funder=None, funder_tok=None) -> bool:
    f, mint = funder or c.funder, mint or c.usdc
    return c.send([pay.fund_wallet_ix(f.pubkey(), funder_tok or c.funder_tok, mint, REPO, n, amount, WF_REPO, WF_SHA, TERMS,
                                      token_program=c.token_program(mint))], f)


# == 1. the four fixes to the 2.0 paths ===============================================================================
def test_a_jobs_bounds_and_fee_floor_are_whole_units_of_its_mint(chain):
    c = chain
    nine = c.new_mint(decimals=9)
    w, wtok = c.wallet(nine, 2_000 * 10 ** 9)
    n = issue()
    # half a unit is under the minimum of 1, and 501 units over the maximum of 500, whatever the smallest unit is
    assert not fund_job(c, n, 5 * 10 ** 8, nine, w, wtok) and code(c) == 81
    assert not fund_job(c, n, 501 * 10 ** 9, nine, w, wtok) and code(c) == 81
    assert fund_job(c, n, 10 ** 9, nine, w, wtok), c.err
    job, payee, wallet = pay.job_pda(REPO, n, w.pubkey()), user(), Keypair().pubkey()
    assert pay_job(c, job, job_token(c, job, payee, wallet), payee, wallet), c.err
    # 2.5% of one unit is under the floor of 0.05 of a unit
    assert c.balance(pay.ata(pay.FEE_OWNER, nine)) == 5 * 10 ** 7 == pay.fee_of(10 ** 9, 9)
    assert c.balance(pay.ata(wallet, nine)) == 10 ** 9 - 5 * 10 ** 7


def test_the_record_counts_real_money_only_in_circles_usdc(chain):
    c = chain
    other = c.new_mint()
    w, wtok = c.wallet(other, 1_000 * USDC)
    payee, wallet, n = user(), Keypair().pubkey(), issue()
    assert fund_job(c, n, 100 * USDC, other, w, wtok), c.err
    job = pay.job_pda(REPO, n, w.pubkey())
    assert pay_job(c, job, job_token(c, job, payee, wallet), payee, wallet), c.err
    # anybody's mint: a test payment, and its amount is added to nothing
    r = pay.read_rep(c.data(pay.rep_pda(payee)))
    assert (r.paid, r.total, r.funders, r.test_paid, r.test_total) == (0, 0, 0, 1, 0)
    assert c.data(pay.pair_pda(payee, w.pubkey())) is None
    n = issue()
    assert fund_job(c, n, 100 * USDC), c.err
    job = pay.job_pda(REPO, n, c.funder.pubkey())
    assert pay_job(c, job, job_token(c, job, payee, wallet), payee, wallet), c.err
    r = pay.read_rep(c.data(pay.rep_pda(payee)))
    assert (r.paid, r.total, r.funders, r.test_paid) == (1, 100 * USDC - pay.fee_of(100 * USDC), 1, 1)


def test_money_enters_only_in_a_mint_whose_every_extension_is_on_the_list(chain):
    c = chain
    me = c.payer.pubkey()
    refused = {
        "a transfer hook that names only an authority": c.new_mint22(hook=(me, None)),
        "a transfer fee of nothing": c.new_mint22(fee=(0, 0)),
        "a permanent delegate": c.new_mint22(permanent_delegate=me),
        "a default account state": c.new_mint22(default_state=1),
        "pausable": raw_mint22(c, ext(26, bytes(33))),
        "an id added later": raw_mint22(c, ext(29, bytes(8))),
        "an unknown id after a listed one": raw_mint22(c, ext(3, bytes(32)) + ext(999, b"\x01")),
        "a list that does not parse": raw_mint22(c, ext(3, bytes(32))[:-5]),
    }
    for why, mint in refused.items():
        w = c.fund()
        assert not c.send([pay.open_balance_ix(w.pubkey(), OWNER, mint, token_program=pay.TOKEN_2022)], w) and code(c) == 95, why
        ix = pay.fund_order_wallet_ix(w.pubkey(), Keypair().pubkey(), mint, REPO, issue(), 20 * USDC, WF_REPO, WF_SHA, TERMS, token_program=pay.TOKEN_2022)
        assert not c.send([ix], w) and code(c) == 95, why
        ix = pay.fund_wallet_ix(w.pubkey(), Keypair().pubkey(), mint, REPO, issue(), 20 * USDC, WF_REPO, WF_SHA, TERMS, token_program=pay.TOKEN_2022)
        assert not c.send([ix], w) and code(c) == 95, why
    for mint in (c.new_mint22(), c.new_mint22(close_authority=True), c.new_mint22(confidential=True)):
        w = c.fund()
        assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, mint, token_program=pay.TOKEN_2022)], w), c.err


def test_a_balance_with_a_side_account_enforces_all_of_it(chain):
    c = chain
    w, wtok = c.wallet(c.usdc, 10_000 * USDC)
    owner = user()
    assert c.send([pay.open_balance_ix(w.pubkey(), owner, c.usdc, spenders=[MAINT])], w), c.err
    bal = pay.balance_pda(owner, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(bal), 5_000 * USDC, w)

    def fund(amount: int, repo: int = REPO, balx: bool = True, wf_sha: str = WF_SHA) -> bool:
        n = issue()
        c.warp(1)
        tok = c.gh(pay.fund_audience(n, amount, pay.MERGE, TH, bal), file="fund.yml", event_name="issue_comment", actor_id=MAINT,
                   repository_owner_id=owner, repository_id=repo, wf_sha=wf_sha)
        return c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, bal, c.usdc, repo, n, TERMS, balx=balx)])

    assert fund(10 * USDC, balx=False), c.err                 # no side account yet: the twelve accounts of 2.0 are enough
    # only the wallet that opened the Balance sets it
    stranger = c.fund()
    assert not c.send([pay.set_balance_x_ix(stranger.pubkey(), bal, day_limit=30 * USDC)], stranger) and code(c) == 98
    assert not c.send([pay.set_balance_x_ix(w.pubkey(), bal, wf_sha="Z" * 40)], w) and code(c) == 81
    assert c.send([pay.set_balance_x_ix(w.pubkey(), bal, day_limit=30 * USDC, total_limit=70 * USDC, repos=[REPO, 5], wf_sha=WF_SHA)], w), c.err
    x = pay.read_balx(c.data(pay.balx_pda(bal)))
    assert (x.day_limit, x.total_limit, x.repos, x.wf_sha, x.total_spent) == (30 * USDC, 70 * USDC, (REPO, 5), WF_SHA, 0)
    assert pay.read_balance(c.data(bal)).has_x
    # a relayer cannot leave the side account out, nor pass another
    assert not fund(10 * USDC, balx=False) and "NotEnoughAccountKeys" in c.err
    assert not fund(10 * USDC, repo=REPO + 1) and code(c) == 92          # a repository that is not listed
    assert not fund(10 * USDC, wf_sha="d" * 40) and code(c) == 86        # another commit of the workflows
    assert fund(20 * USDC), c.err
    assert not fund(11 * USDC) and code(c) == 100                        # 31 in one day
    assert fund(10 * USDC), c.err
    c.warp(DAY)
    assert fund(30 * USDC), c.err                                        # a new day
    c.warp(DAY)
    assert not fund(11 * USDC) and code(c) == 100                        # 71 in all
    assert fund(10 * USDC), c.err
    x = pay.read_balx(c.data(pay.balx_pda(bal)))
    assert (x.day_spent, x.total_spent) == (10 * USDC, 70 * USDC)
    # an order from that Balance is held to the same limits: the amount and the fee on top count
    n = issue()
    tok = c.fund_token(n, 5 * USDC, balance=bal, repository_owner_id=owner)
    assert not c.send([c.fund_balance_ix(tok, n, bal)]) and code(c) == 100
    assert c.send([pay.set_balance_x_ix(w.pubkey(), bal)], w), c.err     # lifted; the counters stay
    assert pay.read_balx(c.data(pay.balx_pda(bal))).total_spent == 70 * USDC
    assert c.send([c.fund_balance_ix(tok, n, bal)]), c.err


def test_a_pay_token_pays_exactly_one_job(chain):
    c = chain
    n, payee, wallet = issue(), user(), Keypair().pubkey()
    second, second_tok = c.wallet(c.usdc, 100 * USDC)
    assert fund_job(c, n, 10 * USDC) and fund_job(c, n, 10 * USDC, funder=second, funder_tok=second_tok), c.err
    a, b = pay.job_pda(REPO, n, c.funder.pubkey()), pay.job_pda(REPO, n, second.pubkey())
    tok = job_token(c, a, payee, wallet)
    # the marker must be the token's own
    j = pay.read_job(c.data(a))
    c.token_account(wallet, c.usdc)
    assert not c.send([pay.pay_ix(c.payer.pubkey(), tok, c.key, a, j, payee, wallet, used=pay.used_pda(bytes(32)))]) and code(c) == 80
    assert pay_job(c, a, tok, payee, wallet), c.err
    assert c.data(pay.used_pda(c.data(tok)))[:1] == b"\x01"
    # the same token, also written again by another relayer, does not pay the other job on the issue
    assert not pay_job(c, b, tok, payee, wallet) and code(c) == 91
    assert c.data(b) is not None and c.balance(pay.ata(wallet, c.usdc)) == 10 * USDC - pay.fee_of(10 * USDC)
    assert pay_job(c, b, job_token(c, b, payee, wallet), payee, wallet), c.err      # a new run's token does


# == 2. Version, SetPlan ==============================================================================================
def test_version_says_two_point_one_is_live(chain):
    c = chain
    assert c.send([pay.version_ix()]) and c.said("knos2:version") == ["knos2:version 1"]


def test_only_the_fee_owner_sets_a_plan_and_only_to_lower_the_rate():
    c = OrderChain()        # a chain of its own: it ends a month later, when the verifier's key has expired
    owner, soon = user(), c.now() + 30 * DAY
    stranger = c.fund()
    assert not c.set_plan(owner, 100, soon, signer=stranger) and code(c) == 102
    for bps, expires in ((49, soon), (251, soon), (100, c.now())):
        assert not c.set_plan(owner, bps, expires) and code(c) == 102
    assert not c.set_plan(0, 100, soon) and code(c) == 102
    assert c.set_plan(owner, 100, soon), c.err
    p = pay.read_plan(c.data(pay.plan_pda(owner)))
    assert (p.fee_bps, p.owner_id, p.expires) == (100, owner, soon) and pay.plan_bps(p, c.now()) == 100 and pay.plan_bps(p, soon) == 250
    assert c.set_plan(owner, 50, soon + 1) and pay.read_plan(c.data(pay.plan_pda(owner))).fee_bps == 50
    # an order from a Balance of that owner pays the plan's rate; any other pays 2.5%
    w, wtok = c.wallet(c.usdc, 1_000 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), owner, c.usdc)], w), c.err
    bal = pay.balance_pda(owner, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(bal), 1_000 * USDC, w)
    n = issue()
    tok = c.fund_token(n, 400 * USDC, balance=bal, repository_owner_id=owner, actor=owner)
    ix = c.fund_balance_ix(tok, n, bal)
    assert not c.send([swap(ix, 6, pay.plan_pda(OWNER))]) and code(c) == 80        # another owner's plan account
    assert c.send([ix]), c.err
    o = c.order(ix.accounts[7].pubkey)
    assert (o.fee, o.fee_bps) == (2 * USDC, 50) and c.held(ix.accounts[7].pubkey) == 402 * USDC
    c.warp(31 * DAY)        # the plan has run out: an order from that Balance would pay 2.5% again, as a wallet's does
    assert pay.plan_bps(pay.read_plan(c.data(pay.plan_pda(owner))), c.now()) == 250
    order = c.fund_wallet(amount=400 * USDC)
    assert c.order(order).fee == 10 * USDC


# == 3. funding an order ==============================================================================================
def test_a_wallet_funds_an_order_for_any_issue_and_pays_the_fee_on_top():
    c = OrderChain()
    n, before = issue(), c.balance(c.funder_tok)
    options = pay.opts(pay.F_NEUTRAL, holdback_bps=1000, warranty_days=30, kill_bps=500, reserve_days=7, arbiter_id=77, judge_repo_id=88)
    order = c.fund_wallet(n, 100 * USDC, options=options, work_s=3 * DAY, seq=4, mode=pay.TESTS)
    assert order == pay.order_pda(pay.scope_of(REPO, n), c.funder.pubkey(), 4)
    o = c.order(order)
    assert (o.state, o.mode, o.from_balance, o.flags, o.decimals, o.repo_id, o.issue, o.seq) == ("open", pay.TESTS, False, pay.F_NEUTRAL, 6, REPO, n, 4)
    assert (o.amount, o.fee, o.paid, o.rate, o.fee_bps) == (100 * USDC, 2_500_000, 0, 0, 250) and o.fee == pay.order_fee(100 * USDC)
    assert (o.holdback_bps, o.warranty_s, o.kill_bps, o.reserve_days, o.arbiter_id, o.judge_repo_id) == (1000, 30 * DAY, 500, 7, 77, 88)
    assert (o.deadline, o.not_before, o.source, o.refund_to, o.rent_to, o.mint) == (c.now() + 3 * DAY, c.now() - 30, c.funder.pubkey(), c.funder.pubkey(),
                                                                                    c.funder.pubkey(), c.usdc)
    assert (o.terms, o.wf_repo_hash, o.wf_sha, o.scope) == (TH, pay.wf_repo_hash(WF_REPO), WF_SHA, pay.scope_of(REPO, n))
    assert (o.funder_id, o.owner_id, o.payee_id, o.reserved_by, o.cancel_at, o.hold_until) == (0, 0, 0, 0, 0, 0)
    assert o.address() == order and bytes(c.data(order)[432:]) == bytes(80)
    # the order's money is alone in its own account: the amount and the fee
    assert c.held(order) == 102_500_000 == before - c.balance(c.funder_tok)
    assert c.said("knos3:terms") == ["knos3:terms " + TERMS.decode()]
    funded = c.said("knos3:funded")[0]
    assert f"order={order} repo={REPO} issue={n} seq=4 amount=100000000 fee=2500000 mode=1 by=0 source={c.funder.pubkey()} flags=4" in funded
    # the fee has a floor of 0.40 and a ceiling of 25, and the amount is between 5 and 500
    assert c.order(c.fund_wallet(amount=5 * USDC)).fee == 400_000
    assert c.order(c.fund_wallet(amount=500 * USDC)).fee == 12_500_000
    for amount in (5 * USDC - 1, 500 * USDC + 1, 0):
        assert not c.send([c.fund_wallet_ix(issue(), amount)], c.funder) and code(c) == 81
    # the same wallet funds the same issue again under another seq, and never the same one twice
    assert c.fund_wallet(n, seq=5) != order
    assert not c.send([c.fund_wallet_ix(n, seq=5)], c.funder) and code(c) == 101


def test_what_a_funding_wallet_cannot_do(chain):
    c = chain
    n = issue()
    ok = c.fund_wallet_ix(n)
    stranger, stranger_tok = c.wallet(c.usdc, 0)
    # someone else's money; another order's or a made-up token account; a repository id of 0; a bad workflow commit
    assert not c.send([swap(c.fund_wallet_ix(n, funder=stranger), 3, c.funder_tok)], stranger)
    assert not c.send([swap(ok, 2, pay.ov_pda(Keypair().pubkey()))], c.funder) and code(c) == 80
    assert not c.send([swap(ok, 1, pay.order_pda(pay.scope_of(REPO, n), c.funder.pubkey(), 9))], c.funder) and code(c) == 101
    assert not c.send([swap(ok, 5, Keypair().pubkey())], c.funder) and code(c) == 80
    assert not c.send([swap(ok, 8, Keypair().pubkey())], c.funder) and code(c) == 80
    assert not c.send([c.fund_wallet_ix(n, repo=0)], c.funder) and code(c) == 81
    assert not c.send([pay.fund_order_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, 20 * USDC, WF_REPO, "g" * 40, TERMS)], c.funder) and code(c) == 81
    assert not c.send([c.fund_wallet_ix(n, terms=b"")], c.funder) and code(c) == 81
    # options outside their limits, a flag only the program sets, a standing order without a rate
    for bad in (pay.opts(holdback_bps=5001, warranty_days=30), pay.opts(warranty_days=91), pay.opts(kill_bps=2001), pay.opts(holdback_bps=100),
                pay.opts(pay.F_FAUCET), pay.opts(pay.F_TOKEN2022), pay.opts(pay.F_STANDING), pay.opts(rate=5), pay.opts(pay.F_STANDING, rate=21 * USDC),
                pay.opts(pay.F_PRIVATE), pay.opts(salted=True), pay.opts(32), pay.opts()[:47] + b"\x01"):
        assert not c.send([c.fund_wallet_ix(n, options=bad)], c.funder) and code(c) == 81, bad.hex()
    # while the guardian's pause lasts nothing new is funded
    from _pay2 import GUARDIAN
    assert c.send([pay.pause_ix(GUARDIAN.pubkey(), c.payer.pubkey(), 3600)], signers=[GUARDIAN]), c.err
    assert not c.send([ok], c.funder) and code(c) == 96
    tok = c.fund_token(n)
    assert not c.send([c.fund_balance_ix(tok, n)]) and code(c) == 96
    assert c.send([pay.pause_ix(GUARDIAN.pubkey(), c.payer.pubkey(), 0)], signers=[GUARDIAN]), c.err
    assert c.send([ok], c.funder), c.err


def test_a_private_order_stores_no_repository_no_issue_and_a_hash_of_its_terms(chain):
    c = chain
    salt, n = bytes(range(32)), issue()
    scope = pay.scope_of(REPO, n, salt)
    options = pay.opts(pay.F_PRIVATE, judge_repo_id=4242, salted=True)
    ix = pay.fund_order_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, 0, 0, 20 * USDC, WF_REPO, WF_SHA, TH, options=options, scope=scope)
    assert c.send([ix], c.funder), c.err
    order = pay.order_pda(scope, c.funder.pubkey())
    o = c.order(order)
    assert (o.repo_id, o.issue, o.scope, o.terms, o.flags, o.judge_repo_id) == (0, 0, scope, TH, pay.F_PRIVATE, 4242)
    assert c.said("knos3:terms") == [] and bytes(salt) not in bytes(c.data(order))
    # a repository or an issue in the clear is refused with the flag, and a Balance cannot fund one yet
    named = pay.fund_order_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, 20 * USDC, WF_REPO, WF_SHA, TH, options=options, scope=scope, seq=1)
    assert not c.send([named], c.funder) and code(c) == 81
    tok = c.fund_token(n, options=options)
    assert not c.send([c.fund_balance_ix(tok, n)]) and code(c) == 81


def test_a_comment_funds_an_order_from_a_balance_once(chain):
    c = chain
    n, before = issue(), c.balance(pay.baltok_pda(c.bal))
    spent = pay.read_balance(c.data(c.bal)).spent
    tok = c.fund_token(n, 40 * USDC, options=NEUTRAL, seq=2, work=3600)
    ix = c.fund_balance_ix(tok, n, seq=2)
    assert c.send([ix], tag="fund_order_balance"), c.err
    order = pay.order_pda(pay.scope_of(REPO, n), c.bal, 2)
    o = c.order(order)
    assert (o.state, o.from_balance, o.flags, o.amount, o.fee, o.seq) == ("open", True, pay.F_NEUTRAL, 40 * USDC, USDC, 2)
    assert (o.funder_id, o.owner_id, o.source, o.refund_to, o.rent_to, o.not_before) == (MAINT, OWNER, c.bal, pay.baltok_pda(c.bal), c.payer.pubkey(), c.now())
    assert c.held(order) == 41 * USDC == before - c.balance(pay.baltok_pda(c.bal)) and pay.read_balance(c.data(c.bal)).spent == spent + 41 * USDC
    assert c.data(pay.used_pda(c.data(tok)))[:1] == b"\x01"
    # the same token again: the order exists; and once the order is gone, the token is still used up
    assert not c.send([ix]) and code(c) == 91
    c.warp(3601)            # past the order's deadline, inside the token's own time
    assert c.refund(order), c.err
    assert c.balance(pay.baltok_pda(c.bal)) == before and c.data(order) is None
    assert not c.send([ix]) and code(c) == 91


def test_what_a_fund_token_cannot_do(chain):
    c = chain
    n = issue()
    tok = c.fund_token(n, 20 * USDC)
    ok = c.fund_balance_ix(tok, n)
    # another Balance than the one it names; other terms; another seq; another marker; a job's instruction
    w, wtok = c.wallet(c.usdc, 100 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, c.usdc, spenders=[MAINT])], w), c.err
    other = pay.balance_pda(OWNER, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(other), 100 * USDC, w)
    assert not c.send([c.fund_balance_ix(tok, n, other)]) and code(c) == 87
    assert not c.send([c.fund_balance_ix(tok, n, terms=TERMS + b" ")]) and code(c) == 81
    assert not c.send([c.fund_balance_ix(tok, n, seq=1)]) and code(c) == 101
    assert not c.send([swap(ok, 9, pay.used_pda(bytes(32)))]) and code(c) == 80
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)]) and code(c) == 87    # knos3 is not knos2
    # a commenter the Balance does not list; a repository of another owner; a re-run; another workflow file; a job's token
    for over, want in ((dict(actor=user()), 92), (dict(repository_owner_id=user()), 92), (dict(run_attempt=2), 85), (dict(file="prove.yml"), 86),
                       (dict(event_name="pull_request_target"), 85)):
        t = c.fund_token(n, 20 * USDC, **over)
        assert not c.send([c.fund_balance_ix(t, n)]) and code(c) == want, over
    c.warp(1)
    old = c.gh(pay.fund_audience(n, 20 * USDC, pay.MERGE, TH, c.bal), file="fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=REPO,
               repository_owner_id=OWNER)
    assert not c.send([c.fund_balance_ix(old, n)]) and code(c) == 87
    # over the Balance's cap for one order; more than it holds
    assert c.send([pay.set_balance_ix(c.owner.pubkey(), c.bal, cap=30 * USDC, spenders=[MAINT])], c.owner), c.err
    t = c.fund_token(n, 31 * USDC)
    assert not c.send([c.fund_balance_ix(t, n)]) and code(c) == 93
    assert c.send([pay.set_balance_ix(c.owner.pubkey(), c.bal, spenders=[MAINT])], c.owner), c.err
    t = c.fund_token(n, 99 * USDC + 1, balance=other)
    assert not c.send([c.fund_balance_ix(t, n, other)]) and code(c) == 94      # 99.000001 and its fee are more than 100
    assert c.send([ok]), c.err


# == 4. paying an order ===============================================================================================
def test_the_orders_repository_pays_one_payee_in_full_and_the_fee_is_split():
    c = OrderChain()
    order, payee, wallet = c.fund_wallet(amount=100 * USDC), user(), Keypair().pubkey()
    o = c.order(order)
    rent = c.lamports(c.funder.pubkey())
    locked = c.lamports(order) + c.lamports(pay.ov_pda(order))
    assert c.pay(order, [(payee, 10_000, wallet)]), c.err
    # the payee receives the posted amount, whole; this transaction created the payee's token account, so the tip is 0.30
    assert c.balance(pay.ata(wallet, c.usdc)) == 100 * USDC
    assert (c.balance(c.tip), c.balance(c.fee)) == (300_000, 2_200_000)
    assert c.data(order) is None and c.data(pay.ov_pda(order)) is None and c.lamports(c.funder.pubkey()) == rent + locked
    r = pay.read_rep(c.data(pay.rep_pda(payee)))
    assert (r.paid, r.total, r.funders, r.first) == (1, 100 * USDC, 1, c.now()) and c.data(pay.pair_pda(payee, c.funder.pubkey())) == b"\x01"
    assert c.said("knos3:paid") == [f"knos3:paid order={order} pr=7 payee={payee} amount=100000000 to={wallet}"]
    assert c.said("knos3:settled") == [f"knos3:settled order={order} paid=100000000 of=100000000 fee=2200000 tip=300000 judge=0"]
    # a payee whose token account exists: the tip is 0.05
    order = c.fund_wallet(amount=100 * USDC)
    assert c.pay(order, [(payee, 10_000, wallet)]), c.err
    assert (c.balance(pay.ata(wallet, c.usdc)), c.balance(c.tip), c.balance(c.fee)) == (200 * USDC, 350_000, 2_200_000 + 2_450_000)
    # the token is of no use afterwards: the order is gone; funded again under the same address, the old proof is too old
    tok = c.pay_token(order, [(payee, 10_000, wallet)], o=o)
    assert not c.send([c.pay_ix(order, tok, [(payee, 10_000, wallet)], o=o)]) and code(c) == 101
    again = c.fund_wallet(o.issue, 100 * USDC)
    old = c.pay_token(again, [(payee, 10_000, wallet)], iat=c.now() - 60)
    assert again != order and not c.send([c.pay_ix(again, old, [(payee, 10_000, wallet)])]) and code(c) == 83


def test_up_to_four_payees_share_an_order_and_every_unit_is_paid(chain):
    c = chain
    order = c.fund_balance(amount=100 * USDC + 3)
    ids = [user() for _ in range(4)]
    wallets = [Keypair().pubkey() for _ in range(4)]
    assert c.bind(ids[1], wallets[1]) and c.bind(ids[3], wallets[3]), c.err
    c.token_account(wallets[1], c.usdc)
    # two named in the token, two paid at their bound wallets; one token account exists, three are created here
    payees = [(ids[0], 5000, wallets[0]), (ids[1], 2500, None), (ids[2], 1667, wallets[2]), (ids[3], 833, None)]
    fee, tip = c.balance(c.fee), c.balance(c.tip)
    assert c.pay(order, payees, tag="pay_order_4"), c.err
    got = [c.balance(pay.ata(w, c.usdc)) for w in wallets]
    assert got == [50_000_001, 25_000_000, 16_670_000, 100 * USDC + 3 - 50_000_001 - 25_000_000 - 16_670_000] and sum(got) == 100 * USDC + 3
    assert (c.balance(c.tip) - tip, c.balance(c.fee) - fee) == (300_000, 2_500_000 - 300_000) and c.data(order) is None
    for i in ids:
        r = pay.read_rep(c.data(pay.rep_pda(i)))
        assert (r.paid, r.funders) == (1, 1) and c.data(pay.pair_pda(i, OWNER)) == b"\x01"
    assert len(c.said("knos3:paid")) == 4
    # the address in the token wins over the bound wallet
    order, named = c.fund_wallet(), Keypair().pubkey()
    assert c.pay(order, [(ids[1], 10_000, named)]), c.err
    assert c.balance(pay.ata(named, c.usdc)) == 20 * USDC and c.balance(pay.ata(wallets[1], c.usdc)) == 25_000_000


def test_an_order_is_held_for_one_payee_without_a_wallet_and_settled_when_he_binds_one(chain):
    c = chain
    order, payee = c.fund_wallet(amount=50 * USDC), user()
    assert c.pay(order, [(payee, 10_000, None)]), c.err
    o = c.order(order)
    assert (o.state, o.payee_id, o.hold_until, o.paid) == ("held", payee, c.now() + pay.HOLD, 0) and c.held(order) == 50 * USDC + o.fee
    assert c.said("knos3:held") == [f"knos3:held order={order} pr=7 payee={payee} until={c.now() + pay.HOLD}"]
    # held: no second proof, no refund before the hold ends, no settlement before the payee has a wallet
    assert not c.pay(order, [(user(), 10_000, Keypair().pubkey())]) and code(c) == 83
    assert not c.refund(order) and code(c) == 83
    wallet = Keypair().pubkey()
    assert not c.settle(order, wallet) and code(c) == 88
    assert c.bind(payee, wallet), c.err
    thief = Keypair().pubkey()
    c.token_account(thief, c.usdc)
    assert not c.settle(order, thief) and code(c) == 88
    assert not c.send([swap(pay.settle_order_ix(c.payer.pubkey(), order, o, wallet), 11, pay.bind_pda(user()))]) and code(c) == 88
    tip, fee = c.balance(c.tip), c.balance(c.fee)
    assert c.settle(order, wallet), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == 50 * USDC and (c.balance(c.tip) - tip, c.balance(c.fee) - fee) == (300_000, 950_000)
    assert c.data(order) is None and c.data(pay.ov_pda(order)) is None
    assert c.said("knos3:settled")[0].endswith("judge=9")
    # a split is never held: with one payee who cannot be paid nothing moves
    order, other = c.fund_wallet(), user()
    payees = [(payee, 5000, None), (other, 5000, None)]
    assert not c.pay(order, payees) and code(c) == 88 and c.order(order).state == "open"


def test_what_a_pay_token_and_its_relayer_cannot_do(chain):
    c = chain
    order, other = c.fund_wallet(amount=30 * USDC), c.fund_wallet(amount=30 * USDC)
    payee, wallet = user(), Keypair().pubkey()
    payees = [(payee, 10_000, wallet)]
    c.token_account(wallet, c.usdc)
    tok = c.pay_token(order, payees)
    ok = c.pay_ix(order, tok, payees)
    state = lambda: (c.held(order), c.held(other), c.balance(pay.ata(wallet, c.usdc)), c.balance(c.fee), c.balance(c.tip))  # noqa: E731
    before = state()
    thief, thief_tok = c.wallet(c.usdc, 0)
    # another order's token; the order's token on another order
    assert not c.send([c.pay_ix(other, tok, payees)]) and code(c) == 87
    # accounts that are not the order's: its token account, its rent, its mint, the token program, the signer of ["auth"]
    wrong = {OV: (pay.ov_pda(other), 80), RENT_TO: (thief.pubkey(), 80), MINT: (c.new_mint(), 80), TOKEN_PROGRAM: (pay.TOKEN_2022, 95),
             AUTH: (thief.pubkey(), 80), ORDER: (pay.ov_pda(order), 101),
             # the fee and the tip: not FEE_OWNER's account, not the relayer's; the fee account as the tip account
             FEE_TOKEN: (thief_tok, 88), TIP_TOKEN: (thief_tok, 88),
             # the payee: another wallet, another wallet's token account, a hidden or foreign Bind, the order's own account
             WALLET: (thief.pubkey(), 88), DEST: (thief_tok, 88), BIND: (pay.bind_pda(user()), 88), REP: (pay.rep_pda(user()), 88),
             PAIR: (pay.pair_pda(user(), c.funder.pubkey()), 88)}
    for index, (key, want) in wrong.items():
        assert not c.send([swap(ok, index, key)]) and code(c) == want, index
    assert not c.send([swap(swap(ok, FEE_TOKEN, c.tip), TIP_TOKEN, c.fee)]) and code(c) == 88
    assert not c.send([swap(ok, DEST, pay.ov_pda(other))]) and code(c) == 88
    # the relayer's signature is needed, and its own tip account: a relayer cannot take the tip of another's transaction
    mine = pay.pay_order_ix(thief.pubkey(), tok, c.key, order, c.order(order), c.wallets(payees), tip_token=c.tip)
    assert not c.send([mine], thief) and code(c) == 88
    # claims: another repository; another workflow file, repository or commit; a re-run; before the funding; a job's audience
    o = c.order(order)
    for over, want in ((dict(repository_id=REPO + 1), 85), (dict(file="fund.yml"), 86), (dict(wf_repo="evil/Knos"), 86), (dict(wf_sha="d" * 40), 86),
                       (dict(run_attempt=2), 85), (dict(iat=o.not_before - 1), 83), (dict(terms=bytes(32)), 87), (dict(mode=1), 87),
                       (dict(runner_environment="self-hosted"), 85)):
        t = c.pay_token(order, payees, **over)
        assert not c.send([c.pay_ix(order, t, payees)]) and code(c) == want, over
    job_aud = c.gh(pay.pay_audience(REPO, o.issue, payee, HEAD, o.terms, o.mode, wallet), repository_id=REPO)
    assert not c.send([c.pay_ix(order, job_aud, payees)]) and code(c) == 87
    # payees the audience does not allow: shares that are not the whole, a payee twice, five payees, the id 0
    for bad in ([(payee, 9_999, wallet)], [(payee, 5_000, wallet), (payee, 5_000, wallet)], [(user(), 2_000, wallet)] * 5, [(0, 10_000, wallet)],
                [(payee, 10_000, wallet), (user(), 0, wallet)]):
        t = c.pay_token(order, bad)
        assert not c.send([c.pay_ix(order, t, bad)]) and code(c) == 87, bad
    # fewer payee accounts than the token names payees
    two = [(payee, 5_000, wallet), (user(), 5_000, wallet)]
    assert not c.send([c.pay_ix(order, c.pay_token(order, two), payees)]) and "NotEnoughAccountKeys" in c.err
    # a standing order that also has a holdback waits until this program can pay it correctly (tests/test_order_terms.py
    # has the standing order and the holdback, each on its own)
    later = c.fund_wallet(options=pay.opts(pay.F_STANDING, rate=10 * USDC, holdback_bps=1000, warranty_days=30))
    assert not c.pay(later, payees) and code(c) == 103
    assert state() == before
    # past the deadline nothing is paid
    short = c.fund_wallet(work_s=3600)
    c.warp(3601)
    assert not c.send([c.pay_ix(short, c.pay_token(short, payees), payees)]) and code(c) == 83
    assert c.send([ok]), c.err
    assert state() == (0, 30 * USDC + 750_000, 30 * USDC, before[3] + 700_000, before[4] + 50_000)


def test_tokens_sent_to_an_orders_account_cannot_stop_it_from_closing(chain):
    c = chain
    order, payee, wallet = c.fund_wallet(), user(), Keypair().pubkey()
    transfer(c, c.owner_tok, pay.ov_pda(order), 7, c.owner)
    fee = c.balance(c.fee)
    assert c.pay(order, [(payee, 10_000, wallet)]), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == 20 * USDC and c.balance(c.fee) - fee == 500_000 - 300_000 + 7 and c.data(pay.ov_pda(order)) is None


def test_an_order_in_a_token_2022_mint_and_in_a_mint_of_nine_decimals(chain):
    c = chain
    for mint, unit in ((c.new_mint22(close_authority=True), USDC), (c.new_mint(decimals=9), 10 ** 9)):
        w, wtok = c.wallet(mint, 1_000 * unit)
        c.token_account(pay.FEE_OWNER, mint); tip = c.token_account(c.payer.pubkey(), mint)
        assert not c.send([c.fund_wallet_ix(issue(), 5 * unit - 1, w, wtok, mint)], w) and code(c) == 81
        ix = c.fund_wallet_ix(issue(), 10 * unit, w, wtok, mint)
        assert c.send([ix], w), c.err
        order = ix.accounts[1].pubkey
        o = c.order(order)
        assert (o.fee, o.decimals, o.token_program) == (unit * 4 // 10, c.data(mint)[44], c.token_program(mint)) and c.held(order) == 10 * unit + o.fee
        payee, wallet = user(), Keypair().pubkey()
        assert c.pay(order, [(payee, 10_000, wallet)]), c.err
        tp = c.token_program(mint)
        assert (c.balance(pay.ata(wallet, mint, tp)), c.balance(tip), c.balance(pay.ata(pay.FEE_OWNER, mint, tp))) == (10 * unit, unit * 3 // 10, unit // 10)
        # anybody's mint: counted as a test payment
        r = pay.read_rep(c.data(pay.rep_pda(payee)))
        assert (r.paid, r.total, r.test_paid, r.test_total) == (0, 0, 1, 0)


# == 5. RefundOrder, TopUp ============================================================================================
def test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before():
    c = OrderChain()
    order, other = c.fund_wallet(amount=60 * USDC, work_s=DAY), c.fund_wallet()
    before, rent = c.balance(c.funder_tok), c.lamports(c.funder.pubkey())
    locked = c.lamports(order) + c.lamports(pay.ov_pda(order))
    assert not c.refund(order) and code(c) == 83
    c.warp(DAY + 1)
    thief, thief_tok = c.wallet(c.usdc, 0)
    assert not c.refund(order, thief_tok) and code(c) == 88
    ok = pay.refund_order_ix(c.payer.pubkey(), order, c.order(order))
    for index, key, want in ((2, pay.ov_pda(other), 80), (5, thief.pubkey(), 80), (6, c.new_mint(), 80), (4, thief.pubkey(), 80)):
        assert not c.send([swap(ok, index, key)]) and code(c) == want, index
    assert c.send([ok], tag="refund_order"), c.err         # no token: it works whatever happens to GitHub or to Knos
    assert c.balance(c.funder_tok) == before + 60 * USDC + 1_500_000 and c.lamports(c.funder.pubkey()) == rent + locked
    assert c.data(order) is None and c.data(pay.ov_pda(order)) is None and c.said("knos3:refunded") == [f"knos3:refunded order={order} amount=61500000"]
    assert not c.send([ok]) and code(c) == 101
    assert not c.refund(other) and code(c) == 83            # its deadline has not passed
    # a held order goes back when its hold ends, not when its deadline does
    assert c.pay(other, [(user(), 10_000, None)]) and c.order(other).state == "held", c.err
    c.warp(14 * DAY)
    assert not c.refund(other) and code(c) == 83
    c.warp(pay.HOLD)
    assert c.refund(other) and c.balance(c.funder_tok) == before + 60 * USDC + 1_500_000 + 20 * USDC + 500_000, c.err


def test_top_up_adds_to_the_amount_and_the_fee_from_where_the_money_came(chain):
    c = chain
    order = c.fund_wallet(amount=10 * USDC)
    assert c.order(order).fee == 400_000
    before = c.balance(c.funder_tok)
    top = lambda add, signer=None, **kw: c.send([pay.top_up_ix((signer or c.funder).pubkey(), order, c.order(order), add, **kw)], signer or c.funder)  # noqa: E731
    assert top(4 * USDC), c.err                     # 14: the fee stays at its floor
    assert (c.order(order).amount, c.order(order).fee, c.held(order)) == (14 * USDC, 400_000, 14_400_000)
    assert top(86 * USDC), c.err                    # 100: 2.5% is 2.50
    assert (c.order(order).amount, c.order(order).fee, c.held(order)) == (100 * USDC, 2_500_000, 102_500_000)
    assert before - c.balance(c.funder_tok) == 90 * USDC + 2_100_000
    assert c.said("knos3:topup") == [f"knos3:topup order={order} add=86000000 amount=100000000 fee=2500000"]
    # nothing, over 500 in all, someone else, someone else's money
    stranger, stranger_tok = c.wallet(c.usdc, 100 * USDC)
    assert not top(0) and code(c) == 81
    assert not top(400 * USDC + 1) and code(c) == 81
    assert not top(USDC, stranger, from_token=stranger_tok) and code(c) == 80
    assert not top(USDC, from_token=stranger_tok)
    # a Balance's order: the wallet that opened the Balance signs, and the Balance pays
    of_balance = c.fund_balance(amount=10 * USDC)
    b = c.balance(pay.baltok_pda(c.bal))
    ix = pay.top_up_ix(c.owner.pubkey(), of_balance, c.order(of_balance), 10 * USDC)
    assert not c.send([swap(ix, 0, stranger.pubkey())], stranger) and code(c) == 98
    assert not c.send([swap(ix, 3, c.owner_tok)], c.owner) and code(c) == 98
    assert c.send([ix], c.owner), c.err
    assert (c.order(of_balance).amount, c.order(of_balance).fee, b - c.balance(pay.baltok_pda(c.bal))) == (20 * USDC, 500_000, 10 * USDC + 100_000)
    # the payees then receive the whole new amount; after the deadline nothing is added
    payee, wallet = user(), Keypair().pubkey()
    assert c.pay(order, [(payee, 10_000, wallet)]) and c.balance(pay.ata(wallet, c.usdc)) == 100 * USDC, c.err
    short = c.fund_wallet(work_s=3600)
    c.warp(3601)
    assert not c.send([pay.top_up_ix(c.funder.pubkey(), short, c.order(short), USDC)], c.funder) and code(c) == 83


# == what entered an order equals what left it plus what it holds =====================================================
def test_a_random_walk_conserves_every_orders_money():
    c, rng = OrderChain(), random.Random(WALK_SEED)
    people = [(user(), Keypair().pubkey()) for _ in range(6)]
    for who, wallet in people[:3]:
        assert c.bind(who, wallet), c.err
    watched = [c.funder_tok, pay.baltok_pda(c.bal), c.fee, c.tip, c.owner_tok, *(pay.ata(w, c.usdc) for _, w in people)]
    orders: dict[Pubkey, dict] = {}     # order -> entered, left
    total = lambda: sum(c.balance(a) for a in watched)  # noqa: E731

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

    done = dict(funded=0, paid=0, held=0, settled=0, refunded=0, topped=0, dust=0, refused=0)
    for _ in range(WALK_N):
        live = [k for k in orders if c.data(k) is not None]
        kind = rng.choice(["fund", "fund", "pay", "pay", "pay", "top", "dust", "refund", "settle", "warp"])
        if kind == "fund" or not live:
            amount, n = rng.randrange(5 * USDC, 120 * USDC), issue()
            if rng.random() < 0.5:
                ix = c.fund_wallet_ix(n, amount, work_s=rng.choice([DAY, 3 * DAY]))
                done["funded"] += step(ix.accounts[1].pubkey, lambda: c.send([ix], c.funder))
            else:
                tok = c.fund_token(n, amount, work=rng.choice([DAY, 3 * DAY]))
                ix = c.fund_balance_ix(tok, n)
                done["funded"] += step(ix.accounts[7].pubkey, lambda: c.send([ix]))
            continue
        order = rng.choice(live)
        o = c.order(order)
        if kind == "pay":
            chosen = rng.sample(people, rng.randrange(1, 5))
            cuts = sorted(rng.sample(range(1, 10_000), len(chosen) - 1))
            shares = [b - a for a, b in zip([0, *cuts], [*cuts, 10_000])]
            payees = [(who, bps, wallet if rng.random() < 0.5 else None) for (who, wallet), bps in zip(chosen, shares)]
            ok = step(order, lambda: c.pay(order, payees, tag=None))
            if ok and c.data(order) is not None:
                done["held"] += 1
                assert c.order(order).state == "held"
            else:
                done["paid" if ok else "refused"] += 1
        elif kind == "top":
            add = rng.randrange(1, 50 * USDC)
            signer = c.owner if o.from_balance else c.funder
            done["topped"] += step(order, lambda: c.send([pay.top_up_ix(signer.pubkey(), order, o, add)], signer))
        elif kind == "dust":
            done["dust"] += step(order, lambda: (transfer(c, c.owner_tok, pay.ov_pda(order), rng.randrange(1, 1000), c.owner), True)[1])
        elif kind == "refund":
            ok = step(order, lambda: c.refund(order))
            done["refunded" if ok else "refused"] += 1
        elif kind == "settle":
            if o.state == "held":
                who = o.payee_id
                wallet = next(w for i, w in people if i == who)
                if pay.read_bind(c.data(pay.bind_pda(who))) is None and rng.random() < 0.5:
                    assert c.bind(who, wallet), c.err
                done["settled"] += step(order, lambda: c.settle(order, wallet))
        else:
            c.warp(rng.choice([3600, DAY]))
        # every order: what entered it is what left it plus what it holds; a closed order holds nothing
        for k, book in orders.items():
            holds = c.held(k) if c.data(k) is not None else 0
            assert book["entered"] == book["left"] + holds, (k, book, holds)
            if c.data(k) is None:
                assert c.data(pay.ov_pda(k)) is None
            else:
                live_o = c.order(k)
                assert holds >= live_o.amount - live_o.paid + live_o.fee
    assert done["funded"] > 5 and done["paid"] > 3 and done["refunded"] > 0, done


def test_on_devnet_the_faucet_mints_an_orders_amount_and_the_fee_on_top():
    c = OrderChain()
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    test_usdc = pay.faucet_mint()
    org, repo, n = user(), user(), issue()
    bal = pay.faucet_balance_pda(org)
    tok = c.fund_token(n, 20 * USDC, balance=bal, repository_owner_id=org, repository_id=repo, actor=user())
    assert c.send([pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo)]), c.err
    assert c.balance(pay.baltok_pda(bal)) == 20 * USDC + 500_000
    ix = pay.fund_order_balance_ix(c.payer.pubkey(), tok, c.key, bal, test_usdc, org, repo, n, TERMS, c.data(tok))
    assert c.send([ix]), c.err
    order = ix.accounts[7].pubkey
    o = c.order(order)
    assert o.faucet and (o.amount, o.fee, o.repo_id, c.balance(pay.baltok_pda(bal)), c.held(order)) == (20 * USDC, 500_000, repo, 0, 20 * USDC + 500_000)
    # over the faucet's cap of 100, and under an order's minimum of 5, nothing is minted
    for amount in (100 * USDC + 1, 5 * USDC - 1):
        c.warp(61)
        t = c.fund_token(n, amount, balance=bal, repository_owner_id=org, repository_id=repo, actor=user())
        assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), t, c.key, org, repo)]) and code(c) == 81
    # paid in test money: the record says so
    c.token_account(pay.FEE_OWNER, test_usdc); c.token_account(c.payer.pubkey(), test_usdc)
    payee, wallet = user(), Keypair().pubkey()
    assert c.pay(order, [(payee, 10_000, wallet)]), c.err
    r = pay.read_rep(c.data(pay.rep_pda(payee)))
    assert (r.paid, r.test_paid, r.test_total) == (0, 1, 20 * USDC)


def test_compute_units_and_sizes_of_the_order_instructions_are_recorded(chain):
    """Not a limit of the program: what its instructions cost in this run. A payment to four payees whose token
    accounts are created in it is the largest; it needs more than one legacy transaction's 1232 bytes."""
    c = chain
    sizes = {}
    for count in (1, 4):
        order = c.fund_wallet(amount=100 * USDC)
        payees = [(user(), 10_000 // count, Keypair().pubkey()) for _ in range(count)]
        assert c.pay(order, payees, tag=f"pay_order, {count} new payee(s)"), c.err
        sizes[count] = c.size
    top = {k: max(v) for k, v in sorted(c.cu.items())}
    print("\nCU of the order instructions, highest seen:", top, "bytes of a PayOrder transaction by payees:", sizes)
    assert all(v < 400_000 for v in top.values()) and sizes[1] <= 1232
