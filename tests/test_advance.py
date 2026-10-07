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
