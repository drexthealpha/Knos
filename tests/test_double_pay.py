"""One token, one use (knos_pay 2.1). A pay token that paid an order must not pay the order a later funding put at
the same address, and no instruction takes any token a second time, whatever state the accounts are in by then.
Runs the test build in LiteSVM."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from _order import AUTHOR, USDC, OrderChain, code, issue  # noqa: E402

from knos.settle.v2 import pay  # noqa: E402


def test_a_pay_token_does_not_pay_the_order_a_second_funding_puts_at_the_same_address():
    c = OrderChain()
    n, baltok = issue(), pay.baltok_pda(c.bal)
    wallet, dest = c.wallet(c.usdc)
    payees = [(AUTHOR, 10_000, wallet.pubkey())]
    start, fee = c.balance(baltok), pay.order_fee(100 * USDC)
    # two fund comments for one issue: GitHub signs two fund tokens for the same order address
    first, second = c.fund_token(n, 100 * USDC), c.fund_token(n, 100 * USDC)
    ix = c.fund_balance_ix(first, n)
    order = ix.accounts[7].pubkey
    assert c.send([ix]), c.err
    c.warp(5)
    proof = c.pay_token(order, payees)
    assert c.send([c.pay_ix(order, proof, payees)]), c.err
    assert c.balance(dest) == 100 * USDC and c.order(order) is None
    # the second fund token is as good as the first: it funds a new order at the address the paid one left
    again = c.fund_balance_ix(second, n)
    assert again.accounts[7].pubkey == order and c.send([again]), c.err
    o = c.order(order)
    assert o is not None and c.held(order) == 100 * USDC + fee
    # the proof of the first order is not a proof of the second: refused, and nothing moves
    assert not c.send([c.pay_ix(order, proof, payees, o)]), "one pay token paid two orders"
    assert code(c) == 91
    assert c.balance(dest) == 100 * USDC and c.held(order) == 100 * USDC + fee
    # the second order goes back whole at its deadline: the Balance is down one amount and one fee
    c.warp(o.deadline - c.now() + 1)
    assert c.refund(order), c.err
    assert c.balance(dest) == 100 * USDC and start - c.balance(baltok) == 100 * USDC + fee


# == every instruction that takes a token takes it once ================================================================
from _order import DAY, HEAD, MAINT, OWNER, REPO, TERMS, TH, user  # noqa: E402
from _pay2 import TEST_CLAIM_SHA  # noqa: E402

CLAIM = dict(file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA, event_name="workflow_dispatch")


def money(c: OrderChain) -> dict:
    """What every SPL token account on the chain holds: the escrow's, the payees', the funders', FEE_OWNER's, the relayer's."""
    return {str(a): int.from_bytes(bytes(acc.data)[64:72], "little") for a, acc in c.svm.get_program_accounts(pay.TOKEN) if len(bytes(acc.data)) == 165}


def twice(c: OrderChain, name: str, make, again, codes=(91,)) -> None:
    """`make()` builds the instruction of a token the chain has just accepted. Sent again as the accounts stand it is
    refused; `again()` then puts the accounts back as they were when the token was good (the order funded anew at the
    same address, the job open again, ...), and it is refused still, with the token's marker as the reason (91; the
    faucet's own rule answers 90 first). No token account anywhere changes."""
    before = money(c)
    assert not c.send([make()]), f"{name}: accepted twice, with its accounts as it left them"
    assert money(c) == before, name
    again()
    before = money(c)
    assert not c.send([make()]), f"{name}: accepted twice, once its accounts were made again"
    assert code(c) in codes and money(c) == before, (name, c.err)


def _order_twice(c: OrderChain, **options):
    """Two fund tokens for one order address (two comments on one issue), the first relayed. Returns the order, the
    order as it stands, and a function that relays the second (once the first order is gone)."""
    n = issue()
    opts = pay.opts(**options) if options else None
    first, second = c.fund_token(n, 100 * USDC, options=opts), c.fund_token(n, 100 * USDC, options=opts)
    ix = c.fund_balance_ix(first, n)
    order = ix.accounts[7].pubkey
    assert c.send([ix]), c.err

    def refund() -> None:
        assert c.send([c.fund_balance_ix(second, n)]) and c.order(order) is not None, c.err
    return order, c.order(order), refund


def _fund_balance(c: OrderChain):      # 3 FundBalance: a job (2.0) from a Balance
    n, (w, _) = issue(), c.wallet(c.usdc)
    c.warp(1)
    tok = c.gh(pay.fund_audience(n, 5 * USDC, pay.MERGE, TH, c.bal), file="fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=REPO,
               repository_owner_id=OWNER)
    make = lambda: pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)  # noqa: E731
    assert c.send([make()]), c.err
    job = pay.job_pda(REPO, n, c.bal)

    def again() -> None:        # the job is paid: its address is free for a funding once more
        proof = c.gh(pay.pay_audience(REPO, n, AUTHOR, HEAD, TH, pay.MERGE, w.pubkey()), repository_id=REPO)
        assert c.send([pay.pay_ix(c.payer.pubkey(), proof, c.key, job, pay.read_job(c.data(job)), AUTHOR, w.pubkey(), used=c.data(proof))]), c.err
    return make, again


def _pay(c: OrderChain):               # 5 Pay: a job funded twice, as the order of the first test is
    n, (w, _) = issue(), c.wallet(c.usdc)
    toks = []
    for _ in range(2):
        c.warp(1)
        toks.append(c.gh(pay.fund_audience(n, 5 * USDC, pay.MERGE, TH, c.bal), file="fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=REPO,
                         repository_owner_id=OWNER))
    fund = lambda t: pay.fund_balance_ix(c.payer.pubkey(), t, c.key, c.bal, c.usdc, REPO, n, TERMS)  # noqa: E731
    assert c.send([fund(toks[0])]), c.err
    job = pay.job_pda(REPO, n, c.bal)
    j = pay.read_job(c.data(job))
    proof = c.gh(pay.pay_audience(REPO, n, AUTHOR, HEAD, TH, pay.MERGE, w.pubkey()), repository_id=REPO)
    make = lambda: pay.pay_ix(c.payer.pubkey(), proof, c.key, job, j, AUTHOR, w.pubkey(), used=c.data(proof))  # noqa: E731
    assert c.send([make()]), c.err
    return make, lambda: c.send([fund(toks[1])]) or pytest.fail(c.err)


def _bind(c: OrderChain, org: bool):   # 8 Bind, 25 BindOrg
    who, member, (w1, _), (w2, _) = user(), user(), c.wallet(c.usdc), c.wallet(c.usdc)
    actor = member if org else who

    def token(wallet):
        c.warp(1)
        return c.gh((pay.org_bind_audience if org else pay.bind_audience)(wallet), **CLAIM, actor_id=actor, repository_owner_id=who,
                    repository=f"u{who}/knos-claim", repository_id=70_000_000 + who % 1_000_000)
    ix = pay.bind_org_ix if org else pay.bind_ix
    tok = token(w1.pubkey())
    make = lambda: ix(c.payer.pubkey(), tok, c.key, who)  # noqa: E731
    assert c.send([make()]), c.err

    def again() -> None:        # a later token binds another wallet: the first token must not bind the first one back
        assert c.send([ix(c.payer.pubkey(), token(w2.pubkey()), c.key, who)]), c.err
    return make, again


def _faucet(c: OrderChain):            # 11 FaucetOpen: mints once, then funds once
    n, org, repo = issue(), user(), user()
    fbal = pay.faucet_balance_pda(org)
    tok = c.fund_token(n, 20 * USDC, balance=fbal, repository_owner_id=org, repository_id=repo)
    make = lambda: pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo)  # noqa: E731
    assert c.send([make()]), c.err
    assert c.balance(pay.baltok_pda(fbal)) == 20 * USDC + pay.order_fee(20 * USDC) and c.data(pay.used_pda(c.data(tok)))[0] == pay.MINTED

    def again() -> None:        # the faucet's minute is over, and the token has funded what it was minted for
        assert c.send([c.fund_balance_ix(tok, n, balance=fbal, repo=repo)]), c.err
        assert c.balance(pay.baltok_pda(fbal)) == 0 and pay.spent(c.data(pay.used_pda(c.data(tok))))
        c.warp(pay.FUND_PERIOD + 1)
    return make, again


def _fund_order(c: OrderChain):        # 16 FundOrderBalance
    n, (w, _) = issue(), c.wallet(c.usdc)
    tok = c.fund_token(n, 100 * USDC)
    make = lambda: c.fund_balance_ix(tok, n)  # noqa: E731
    assert c.send([make()]), c.err
    order = make().accounts[7].pubkey
    return make, lambda: c.pay(order, [(AUTHOR, 10_000, w.pubkey())]) or pytest.fail(c.err)


def _pay_order(c: OrderChain, held: bool):     # 17 PayOrder: paying, and holding for a payee who has no wallet yet
    order, o, refund = _order_twice(c)
    who, (w, _) = user(), c.wallet(c.usdc)
    payees = [(who, 10_000, None if held else w.pubkey())]
    proof = c.pay_token(order, payees)
    make = lambda: pay.pay_order_ix(c.payer.pubkey(), proof, c.key, order, o, c.wallets(payees))  # noqa: E731
    assert c.send([make()]), c.err
    if not held:
        return make, refund

    def again() -> None:        # the payee binds a wallet, the held order is settled, and the address is funded anew
        assert c.bind(who, w.pubkey()) and c.settle(order, w.pubkey()), c.err
        refund()
    return make, again


def _command(c: OrderChain, what: str):        # 20 Reserve, 21 Cancel: the order is paid and funded anew at its address
    order, o, refund = _order_twice(c, reserve_days=2)
    taker, (w, _) = user(), c.wallet(c.usdc)
    if what == "reserve":
        tok = c.gh(pay.take_audience(order, taker, 2), repository_id=REPO, actor_id=taker)
        make = lambda: pay.reserve_ix(c.payer.pubkey(), tok, c.key, order)  # noqa: E731
    else:
        tok = c.gh(pay.cancel_audience(order), repository_id=REPO, actor_id=MAINT)
        make = lambda: pay.cancel_ix(c.payer.pubkey(), order, tok, c.key)  # noqa: E731
    assert c.send([make()]), c.err

    def again() -> None:
        assert c.pay(order, [(taker, 10_000, w.pubkey())]), c.err
        refund()
        after = c.order(order)
        assert (after.reserved_by, after.cancel_at) == (0, 0)
    return make, again


def _revert(c: OrderChain):            # 19 Revert: the holdback of the second order is not the first one's to take back
    order, o, refund = _order_twice(c, holdback_bps=2000, warranty_days=30)
    (w, _) = c.wallet(c.usdc)
    payees = [(AUTHOR, 10_000, w.pubkey())]
    proofs = [c.pay_token(order, payees, o, pr=k) for k in (7, 8)]
    pay_with = lambda p: c.send([pay.pay_order_ix(c.payer.pubkey(), p, c.key, order, c.order(order), c.wallets(payees))])  # noqa: E731
    assert pay_with(proofs[0]) and c.order(order).state == "warranty", c.err
    tok = c.gh(pay.revert_audience(order, HEAD), repository_id=REPO)
    rent_to, hb = o.rent_to, pay.read_holdback(c.data(pay.hb_pda(order)))
    make = lambda: pay.revert_ix(c.payer.pubkey(), tok, c.key, order, o, hb)  # noqa: E731
    assert c.send([make()]) and c.order(order) is None, c.err

    def again() -> None:        # funded and paid again in the same second: the second holdback waits in the order
        refund()
        assert pay_with(proofs[1]) and c.order(order).state == "warranty", c.err
        assert c.order(order).rent_to == rent_to and c.held(order) > 20 * USDC
    return make, again


def test_no_instruction_takes_a_token_twice_and_a_second_try_never_moves_money():
    c = OrderChain()
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    cases = {
        "FundBalance": lambda: _fund_balance(c), "Pay": lambda: _pay(c), "Bind": lambda: _bind(c, False), "BindOrg": lambda: _bind(c, True),
        "FaucetOpen": lambda: _faucet(c), "FundOrderBalance": lambda: _fund_order(c), "PayOrder": lambda: _pay_order(c, False),
        "PayOrder (held)": lambda: _pay_order(c, True), "Revert": lambda: _revert(c), "Reserve": lambda: _command(c, "reserve"),
        "Cancel": lambda: _command(c, "cancel"),
    }
    assert {pay.TOKEN_AT[t] for t in pay.TOKEN_AT} == {1, 2} and len(pay.TOKEN_AT) == 10       # every instruction that takes a token is a case above
    for name, case in cases.items():
        make, again = case()
        twice(c, name, make, again, codes=(90,) if name == "FaucetOpen" else (91,))
        # the accepted token left a marker that says who paid its rent and when it may be closed
        tok = make().accounts[pay.TOKEN_AT[make().data[0]]].pubkey
        payer, after = pay.read_marker(c.data(pay.used_pda(c.data(tok))))
        assert payer == c.payer.pubkey() and after >= c.now() - 2 * DAY, name


def test_a_marker_gives_its_rent_back_once_no_instruction_could_take_the_token():
    c = OrderChain()
    order = c.fund_balance(amount=100 * USDC, options=pay.opts(reserve_days=2))
    taker = user()
    tok = c.gh(pay.take_audience(order, taker, 2), repository_id=REPO, actor_id=taker)
    marker = pay.used_pda(c.data(tok))
    assert c.send([pay.reserve_ix(c.payer.pubkey(), tok, c.key, order)]) and c.data(marker) is not None, c.err
    close = pay.close_marker_ix(marker, c.payer.pubkey())
    assert not c.send([close]) and code(c) == 83
    c.warp(pay.USED_KEEP + 1)
    lamports = c.lamports(marker)
    before = c.lamports(c.payer.pubkey())
    assert c.send([close]) and c.data(marker) is None, c.err
    assert c.lamports(c.payer.pubkey()) - before == lamports - 5000        # the rent, less the transaction's fee
