"""Advance, with what knos_pay 2.1 has today (Assign, instruction 24; examples/advance/README.md), in the Solana runtime
(LiteSVM): a seller assigns an order's payment to a financier, who pays the seller off the order and collects from it.

What Assign does, and so what these tests hold it to: it routes every payment of the order to the assignee from the
moment it is made. A holdback is recorded with the wallets of the payment that created it, so an assignment made
BEFORE the order is paid moves both the part paid at acceptance and the holdback at release to the financier; one made
AFTER the payment (inside the warranty) is recorded and moves nothing. The financier's risk is a revert inside the
warranty: the holdback goes back to the funder."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import DAY, HEAD, REPO, USDC, OrderChain, code, transfer, user  # noqa: E402

from knos.settle.v2 import pay  # noqa: E402

AMOUNT, HOLDBACK, WARRANTY = 100 * USDC, 2000, 30          # an order of 100 test USDC, a fifth held back for 30 days
NOW, LATER = AMOUNT * (10_000 - HOLDBACK) // 10_000, AMOUNT * HOLDBACK // 10_000
PRICE = AMOUNT * 200 // 10_000                             # the financier's price in this example: 2% (the financier sets it, not Knos)


def assign(c: OrderChain, signer: Keypair, order: Pubkey, who: int, to: Pubkey) -> bool:
    return c.send([pay.assign_ix(signer.pubkey(), order, who, to)], signers=[signer])


def accept(c: OrderChain, order: Pubkey, seller: int) -> bool:
    """The order's judge accepts pull request 7 of the seller's: PayOrder, to wherever the program routes the seller."""
    o = c.order(order)
    payees = [(seller, 10_000, None)]
    to = [(seller, pay.payee_wallet(c.data(pay.assign_pda(order, seller)), o, pay.read_bind(c.data(pay.bind_pda(seller))), None))]
    return c.send([pay.pay_order_ix(c.payer.pubkey(), c.pay_token(order, payees), c.key, order, o, to, pr=7)])


def held_back(c: OrderChain, order: Pubkey) -> pay.Holdback | None:
    return pay.read_holdback(c.data(pay.hb_pda(order)))


def release(c: OrderChain, order: Pubkey) -> bool:
    return c.send([pay.release_ix(c.payer.pubkey(), order, c.order(order), held_back(c, order))])


def setup() -> tuple:
    """An open order with a holdback, a seller with a bound wallet, and a financier who holds test USDC."""
    c = OrderChain()
    seller, seller_key = user(), c.fund()
    financier, financier_tok = c.wallet(c.usdc, 1_000 * USDC)
    assert c.bind(seller, seller_key.pubkey()), c.err
    order = c.fund_wallet(amount=AMOUNT, options=pay.opts(holdback_bps=HOLDBACK, warranty_days=WARRANTY))
    return c, order, seller, seller_key, financier, financier_tok


def test_an_assignment_before_acceptance_pays_the_financier_at_acceptance_and_at_release_and_never_the_seller():
    c, order, seller, seller_key, financier, financier_tok = setup()
    seller_tok = c.token_account(seller_key.pubkey(), c.usdc)
    assert assign(c, seller_key, order, seller, financier.pubkey()), c.err
    assert c.said("knos3:assigned") == [f"knos3:assigned order={order} payee={seller} to={financier.pubkey()}"]
    # the old payee cannot assign it a second time, to himself or to another financier: only the assignee can pass it on
    assert not assign(c, seller_key, order, seller, seller_key.pubkey()) and code(c) == 80
    assert not assign(c, seller_key, order, seller, Keypair().pubkey()) and code(c) == 80
    before = c.balance(financier_tok)
    assert accept(c, order, seller), c.err
    # acceptance: the financier's wallet receives the part paid now, and the holdback is recorded for that wallet
    assert c.balance(financier_tok) == before + NOW and c.balance(seller_tok) == 0
    assert held_back(c, order).payees == [(seller, financier.pubkey(), LATER)] and c.order(order).state == "warranty"
    # the advance itself is off the order: the financier pays the seller now, less its price (a plain transfer)
    transfer(c, financier_tok, seller_tok, AMOUNT - PRICE, financier)
    assert c.balance(seller_tok) == AMOUNT - PRICE and c.balance(financier_tok) == before + NOW - (AMOUNT - PRICE)       # out LATER - PRICE until release
    assert not release(c, order) and code(c) == 83                      # nothing is released inside the warranty
    c.warp(WARRANTY * DAY + 1)
    assert release(c, order), c.err
    assert c.said("knos3:released") == [f"knos3:released order={order} payee={seller} amount={LATER} to={financier.pubkey()}"]
    assert c.balance(financier_tok) == before + PRICE and c.balance(seller_tok) == AMOUNT - PRICE and c.data(order) is None


def test_an_assignment_after_acceptance_is_recorded_and_moves_nothing_the_holdback_goes_to_the_wallet_the_payment_recorded():
    c, order, seller, seller_key, financier, financier_tok = setup()
    seller_tok = pay.ata(seller_key.pubkey(), c.usdc)
    assert accept(c, order, seller), c.err
    assert c.balance(seller_tok) == NOW and held_back(c, order).payees == [(seller, seller_key.pubkey(), LATER)]
    before = c.balance(financier_tok)
    assert assign(c, seller_key, order, seller, financier.pubkey()), c.err         # the program takes it: the order still exists
    assert held_back(c, order).payees == [(seller, seller_key.pubkey(), LATER)]
    c.warp(WARRANTY * DAY + 1)
    ix = pay.release_ix(c.payer.pubkey(), order, c.order(order), held_back(c, order))
    hb = held_back(c, order)
    to_financier = pay.release_ix(c.payer.pubkey(), order, c.order(order), pay.Holdback(hb.payer, hb.until, [(seller, financier.pubkey(), LATER)]))
    assert not c.send([to_financier]) and code(c) == 88                             # Release pays the recorded wallet and no other
    assert c.send([ix]), c.err
    assert c.balance(seller_tok) == AMOUNT and c.balance(financier_tok) == before


def test_a_revert_inside_the_warranty_is_the_financiers_loss_the_holdback_goes_back_to_the_funder():
    c, order, seller, seller_key, financier, financier_tok = setup()
    seller_tok = c.token_account(seller_key.pubkey(), c.usdc)
    assert assign(c, seller_key, order, seller, financier.pubkey()) and accept(c, order, seller), c.err
    transfer(c, financier_tok, seller_tok, AMOUNT - PRICE, financier)
    before, funder = c.balance(financier_tok), c.balance(c.funder_tok)
    c.warp(DAY)
    tok = c.gh(pay.revert_audience(order, HEAD), repository_id=REPO)
    assert c.send([pay.revert_ix(c.payer.pubkey(), tok, c.key, order, c.order(order), held_back(c, order))]), c.err
    fee = pay.order_fee(AMOUNT)
    assert c.balance(c.funder_tok) == funder + LATER + fee * HOLDBACK // 10_000      # the holdback and the fee on it
    assert c.balance(financier_tok) == before and c.balance(seller_tok) == AMOUNT - PRICE and c.data(order) is None
    # the financier advanced 98 and collected 80: it is out 18 test USDC, and nothing on chain makes the seller repay it
    assert (AMOUNT - PRICE) - NOW == 18 * USDC


# -- a reserved netting period sold as a receivable ---------------------------------------------------------------------
def test_a_closed_reserved_period_is_sold_once_the_draws_pay_the_financier_and_an_unsigned_draw_is_the_financiers_loss():
    import hashlib

    from _order import OWNER
    from _reserve import draw, locked

    from knos import advance, netting

    c = OrderChain()
    seller, seller_key = user(), c.fund()
    financier, financier_tok = c.wallet(c.usdc, 1_000 * USDC)
    seller_tok = c.token_account(seller_key.pubkey(), c.usdc)
    assert c.bind(seller, seller_key.pubkey()), c.err
    order, _f = locked(c, seller, "100", "20")
    doc = advance.offer(str(financier.pubkey()), str(c.usdc), 200, 500 * USDC)
    sha = lambda *a: hashlib.sha256(":".join(map(str, a)).encode()).hexdigest()         # noqa: E731

    def book(reserve: dict | None, lines: int, shut: bool = True, who: int = seller) -> netting.Book:
        text = netting.open_line(netting.Book(), OWNER, who, 202610, "500", reserve=reserve) + "\n"
        got, refused = netting.add(netting.read(text), [{"order": "a1" * 32, "milestone": i, "artifact": sha("a", i)[:40], "policy": "b2" * 32, "amount": "9.5",
                                                         "evidence": sha("e", i)} for i in range(lines)])
        text += "".join(line + "\n" for line in got)
        assert not refused
        return netting.read(text + (netting.close(netting.read(text))[1] + "\n" if shut else ""))

    facts = netting.reserve_of(c.order(order), order, OWNER, seller, c.now())
    quote = lambda b, **kw: advance.period_quote(doc, b, c.order(order), now=c.now(),                               # noqa: E731
                                                 assigned=pay.read_assign(c.data(pay.assign_pda(order, seller)), c.order(order)), **kw)
    # what is not sold: an open period, an unsecured one, one under a tranche, one past the offer's cap
    assert "no such closed period" in quote(book(facts, 5, shut=False))["why"][0]
    assert "is unsecured: no order holds its money" in quote(book(None, 5))["why"][0]
    assert "draws nothing" in quote(book(facts, 2))["why"][0]
    small = advance.offer(str(financier.pubkey()), str(c.usdc), 200, 30 * USDC)
    assert "the offer's cap" in advance.period_quote(small, book(facts, 5), c.order(order), now=c.now())["why"][0]

    # five outcomes of 9.50: 47.50 accepted, two draws of 20.00 are the receivable, 7.50 stays the supplier's and is not sold
    b = book(facts, 5)
    q = quote(b)
    assert q["ok"] and (q["share"], q["draws"], q["undrawn_not_sold"], q["discount"], q["pays_now"], q["collects"]) == (40 * USDC, 2, 7_500_000, 800_000, 39_200_000, 40 * USDC)
    assert q["knos_fee"] == 0 and [r["who"] for r in q["who_carries"]] == ["buyer", "supplier", "financier", "Knos"]
    assert "pays the supplier 39.20 test USDC now for period 202610.0" in advance.lines(q)[0]
    before = c.balance(financier_tok)
    assert c.send(advance.take_ixs(doc, q, order, c.order(order), seller, seller_key.pubkey(), advancer_token=financier_tok), signers=[financier, seller_key]), c.err
    assert c.balance(seller_tok) == 39_200_000 and "already assigned" in quote(b)["why"][0]         # sold once
    # each draw the judge signs now pays the financier, whatever wallet the token names; the supplier gets no second payment
    for d in netting.draws(b.periods[0], seller_key.pubkey()):
        assert draw(c, order, d, seller, seller_key.pubkey()), c.err
    assert c.balance(financier_tok) == before - 39_200_000 + 40 * USDC and c.balance(seller_tok) == 39_200_000
    assert c.order(order).amount == 60 * USDC                                                       # the buyer's money: locked until the deadline

    # the other end: a second period is sold and its draws are never signed. At the deadline the buyer has the money
    # back and the financier, who paid, collects nothing: the credit exposure was the financier's, never the supplier's
    order2, _f = locked(c, seller + 1, "100", "20")
    seller2_key = c.fund()
    assert c.bind(seller + 1, seller2_key.pubkey()), c.err
    b2 = book(netting.reserve_of(c.order(order2), order2, OWNER, seller + 1, c.now()), 5, who=seller + 1)
    q2 = advance.period_quote(doc, b2, c.order(order2), now=c.now())
    paid_out = c.balance(financier_tok)
    assert q2["ok"] and c.send(advance.take_ixs(doc, q2, order2, c.order(order2), seller + 1, seller2_key.pubkey(), advancer_token=financier_tok),
                               signers=[financier, seller2_key]), c.err
    bal = c.balance(pay.baltok_pda(c.bal))
    c.warp(14 * DAY + 1)
    assert "past its deadline" in advance.period_quote(doc, b2, c.order(order2), now=c.now())["why"][0]
    assert c.refund(order2) and c.balance(pay.baltok_pda(c.bal)) == bal + 100 * USDC + pay.order_fee(100 * USDC)
    assert c.balance(financier_tok) == paid_out - 39_200_000 and c.balance(pay.ata(seller2_key.pubkey(), c.usdc)) == 39_200_000


def test_the_documents_say_who_carries_which_risk_and_how_a_reserve_returns_word_for_word():
    from pathlib import Path

    from knos import advance, netting

    docs = Path(__file__).resolve().parent.parent / "docs"
    said = " ".join((docs / "ADVANCE.md").read_text(encoding="utf-8").split())
    assert [w for w, _t in advance.WHO_CARRIES] == ["buyer", "supplier", "financier", "Knos"]
    for who, what in advance.WHO_CARRIES:
        assert f"| {who} | {what} |" in said
    net = " ".join((docs / "NETTING.md").read_text(encoding="utf-8").split())
    for words in ("`RefundOrder` (knos_pay instruction 22)", "`Cancel` (instruction 21)", "`Withdraw`, instruction 2", "funded = brought + consumed + free"):
        assert words in net
    assert "RefundOrder (knos_pay instruction 22)" in netting.REFUND and "Cancel (instruction 21)" in netting.REFUND and "Withdraw, instruction 2" in netting.NOT_LOCKED
