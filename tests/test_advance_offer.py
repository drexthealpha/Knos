"""`knos advance` (src/knos/advance.py, docs/ADVANCE.md) in the Solana runtime (LiteSVM): a third party advances a
supplier the payment of a funded order. One transaction pays the supplier and assigns the order; after that the order
ends one of three ways and each pays one party once. Knos lends nothing and charges nothing."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402

from _order import DAY, USDC, OrderChain, code, user  # noqa: E402
from _pay2 import WF_REPO, WF_SHA, ChainLedger  # noqa: E402

from knos import advance  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

AMOUNT, RATE = 100 * USDC, 200          # an order of 100 test USDC; the advancer's discount in this example is 2%
NOW = AMOUNT - AMOUNT * RATE // 10_000


def setup(float_=1_000 * USDC, **options):
    """A funded order, a supplier with a bound wallet, an advancer with test USDC and an offer."""
    c = OrderChain()
    supplier, supplier_key = user(), c.fund()
    advancer, advancer_tok = c.wallet(c.usdc, float_)
    assert c.bind(supplier, supplier_key.pubkey()), c.err
    order = c.fund_wallet(amount=AMOUNT, **({"options": pay.opts(**options)} if options else {}))
    doc = advance.offer(str(advancer.pubkey()), str(c.usdc), RATE, 500 * USDC, evaluators=[f"{WF_REPO}@{WF_SHA}"])
    return c, order, supplier, supplier_key, advancer, advancer_tok, doc


def quote(c, doc, order, supplier, **kw):
    o = c.order(order)
    return advance.quote(doc, o, now=c.now(), assigned=pay.read_assign(c.data(pay.assign_pda(order, supplier)), o) if o else None, wf_repo=WF_REPO, **kw)


def take(c, doc, order, supplier, supplier_key, advancer, signers=None, **kw) -> bool:
    q = quote(c, doc, order, supplier)
    ixs = advance.take_ixs(doc, q, order, c.order(order), supplier, supplier_key.pubkey(), advancer_token=kw.get("advancer_tok"))
    return c.send(ixs, advancer, signers=[supplier_key] if signers is None else signers)


def accept(c, order, supplier, **over) -> bool:
    """The order's judge accepts the supplier's pull request: PayOrder, to wherever the program routes the supplier."""
    o = c.order(order)
    to = [(supplier, pay.payee_wallet(c.data(pay.assign_pda(order, supplier)), o, pay.read_bind(c.data(pay.bind_pda(supplier))), None))]
    return c.send([pay.pay_order_ix(c.payer.pubkey(), over.get("token") or c.pay_token(order, [(supplier, 10_000, None)]), c.key, order, o, to, pr=7)])


def test_paid_one_transaction_pays_the_supplier_now_and_acceptance_pays_the_advancer_once():
    c, order, supplier, supplier_key, advancer, advancer_tok, doc = setup()
    supplier_tok = pay.ata(supplier_key.pubkey(), c.usdc)
    q = quote(c, doc, order, supplier)
    assert (q["ok"], q["pays_now"], q["discount"], q["collects"], q["knos_fee"]) == (True, NOW, 2 * USDC, AMOUNT, 0)
    ledger = ChainLedger(c)
    assert advance.status(ledger, order, supplier)["state"] == "not assigned"
    held = c.held(order)
    ledger.send(advance.take_ixs(doc, q, order, c.order(order), supplier, supplier_key.pubkey(), advancer_token=advancer_tok), advancer, [supplier_key])
    # the supplier is paid now, by the advancer; the order's money did not move and Knos took nothing
    assert c.balance(supplier_tok) == NOW and c.balance(advancer_tok) == 1_000 * USDC - NOW and c.held(order) == held
    st = advance.status(ledger, order, supplier)
    assert (st["state"], st["assignee"]) == ("assigned: waits for an acceptance", str(advancer.pubkey()))
    # a second advance against the same order is refused before anything is signed, and by the program if it is tried
    again = quote(c, doc, order, supplier)
    assert not again["ok"] and "already assigned" in again["why"][0]
    assert not c.send([pay.assign_ix(supplier_key.pubkey(), order, supplier, Keypair().pubkey())], signers=[supplier_key]) and code(c) == 80
    fee = c.balance(c.fee)
    assert ledger.send([c.marked(pay.pay_order_ix(c.payer.pubkey(), c.pay_token(order, [(supplier, 10_000, None)]), c.key, order, c.order(order),
                                                  [(supplier, advancer.pubkey())], pr=7))], c.payer)
    assert c.balance(advancer_tok) == 1_000 * USDC + AMOUNT - NOW and c.balance(supplier_tok) == NOW and c.data(order) is None
    assert c.balance(c.fee) - fee <= pay.order_fee(AMOUNT)             # the order's own fee, which its funder paid: nothing for the advance
    st = advance.status(ledger, order, supplier)
    assert (st["state"], st["advancer_collected"], st["paid_to"]) == ("paid", True, str(advancer.pubkey()))


def test_nothing_pays_both_the_supplier_cannot_be_paid_by_the_order_after_the_advance():
    c, order, supplier, supplier_key, advancer, advancer_tok, doc = setup()
    assert take(c, doc, order, supplier, supplier_key, advancer, advancer_tok=advancer_tok), c.err
    o = c.order(order)
    # a relayer that names the supplier's own wallet, the token's address, is refused: the assignment cannot be left out
    tok = c.pay_token(order, [(supplier, 10_000, supplier_key.pubkey())])
    assert not c.send([pay.pay_order_ix(c.payer.pubkey(), tok, c.key, order, o, [(supplier, supplier_key.pubkey())], pr=7)])
    assert c.balance(pay.ata(supplier_key.pubkey(), c.usdc)) == NOW and c.order(order).state == "open"
    assert accept(c, order, supplier, token=tok), c.err                      # the same acceptance, routed as the program routes it
    assert c.balance(advancer_tok) == 1_000 * USDC + AMOUNT - NOW and c.balance(pay.ata(supplier_key.pubkey(), c.usdc)) == NOW
    assert not c.send([pay.refund_order_ix(c.payer.pubkey(), order, o)])     # and nothing is left to refund


def test_the_take_is_whole_or_nothing_no_assignment_without_the_payment_and_no_payment_without_the_assignment():
    c, order, supplier, supplier_key, advancer, advancer_tok, doc = setup(float_=50 * USDC)      # an advancer who cannot pay 98
    assert not take(c, doc, order, supplier, supplier_key, advancer, advancer_tok=advancer_tok)
    assert c.data(pay.assign_pda(order, supplier)) is None and c.balance(advancer_tok) == 50 * USDC
    c2, order2, supplier2, key2, advancer2, tok2, doc2 = setup()
    stranger = c2.fund()                                                     # not the supplier's bound wallet
    q = quote(c2, doc2, order2, supplier2)
    ixs = advance.take_ixs(doc2, q, order2, c2.order(order2), supplier2, stranger.pubkey(), advancer_token=tok2)
    assert not c2.send(ixs, advancer2, signers=[stranger]) and code(c2) == 80
    assert c2.balance(tok2) == 1_000 * USDC and c2.data(pay.assign_pda(order2, supplier2)) is None


def test_rejected_the_funder_gives_notice_and_is_refunded_the_advancers_loss_is_its_own():
    c, order, supplier, supplier_key, advancer, advancer_tok, doc = setup()
    assert take(c, doc, order, supplier, supplier_key, advancer, advancer_tok=advancer_tok), c.err
    funder = c.balance(c.funder_tok)
    assert c.send([pay.cancel_ix(c.funder.pubkey(), order)], signers=[c.funder]), c.err      # the work was rejected: no acceptance is signed
    ledger = ChainLedger(c)
    assert advance.status(ledger, order, supplier)["notice"] is True
    assert not quote(c, doc, order, supplier)["ok"]
    assert not c.refund(order)                                                # not before the notice ends
    c.warp(pay.NOTICE + 1)
    o = c.order(order)
    ledger.send([pay.refund_order_ix(c.payer.pubkey(), order, o)], c.payer)
    assert c.balance(c.funder_tok) == funder + AMOUNT + o.fee and c.data(order) is None
    assert c.balance(advancer_tok) == 1_000 * USDC - NOW and c.balance(pay.ata(supplier_key.pubkey(), c.usdc)) == NOW
    st = advance.status(ledger, order, supplier)
    assert st["state"].startswith("refunded to the funder") and st["advancer_collected"] is False
    # a late acceptance pays nobody: the order is gone
    assert not c.send([pay.pay_order_ix(c.payer.pubkey(), c.pay_token(order, [(supplier, 10_000, None)], o=o), c.key, order, o, [(supplier, advancer.pubkey())], pr=7)])
    assert c.balance(advancer_tok) == 1_000 * USDC - NOW


def test_expired_the_deadline_passes_and_the_funder_is_refunded_the_advancer_collects_nothing():
    c, order, supplier, supplier_key, advancer, advancer_tok, doc = setup()
    assert take(c, doc, order, supplier, supplier_key, advancer, advancer_tok=advancer_tok), c.err
    funder, o = c.balance(c.funder_tok), c.order(order)
    c.warp(o.deadline - c.now() + 1)
    assert advance.status(ChainLedger(c), order, supplier)["state"] == "expired: anyone can refund the funder"
    assert c.refund(order), c.err
    assert c.balance(c.funder_tok) == funder + AMOUNT + o.fee
    assert c.balance(advancer_tok) == 1_000 * USDC - NOW and c.balance(pay.ata(supplier_key.pubkey(), c.usdc)) == NOW


def test_an_acceptance_already_signed_is_advanced_against_and_the_same_token_then_pays_the_advancer():
    c, order, supplier, supplier_key, advancer, advancer_tok, doc = setup()
    tok = c.pay_token(order, [(supplier, 10_000, None)])                      # the judge has signed; nobody has carried it yet
    assert quote(c, doc, order, supplier, assurance="hermetic")["ok"]
    assert take(c, doc, order, supplier, supplier_key, advancer, advancer_tok=advancer_tok), c.err
    assert accept(c, order, supplier, token=tok), c.err
    assert c.balance(advancer_tok) == 1_000 * USDC + AMOUNT - NOW and c.balance(pay.ata(supplier_key.pubkey(), c.usdc)) == NOW


def test_the_offer_refuses_what_it_did_not_offer_and_says_why():
    c, order, supplier, supplier_key, advancer, _tok, doc = setup()
    o = c.order(order)
    assert advance.check(doc) is None and advance.check({**doc, "rate_bps": 1}) == "the file does not hash to the sha256 it states"
    small = advance.offer(doc["advancer"], doc["mint"], RATE, 50 * USDC)
    assert "cap" in advance.quote(small, o, now=c.now())["why"][0]
    other = advance.offer(doc["advancer"], doc["mint"], RATE, 500 * USDC, evaluators=["someone/else@" + "a" * 40])
    assert "does not accept" in advance.quote(other, o, now=c.now(), wf_repo=WF_REPO)["why"][0]
    assert "--workflows" in advance.quote(other, o, now=c.now())["why"][0]
    assert "black-box" in advance.quote(advance.offer(doc["advancer"], doc["mint"], RATE, 500 * USDC, assurances=["hermetic"]), o, now=c.now(), assurance="black-box")["why"][0]
    assert "deadline" in advance.quote(doc, o, now=o.deadline - 60, wf_repo=WF_REPO)["why"][0]
    assert not advance.quote(doc, None, now=c.now())["ok"]
    held = c.fund_wallet(amount=AMOUNT, options=pay.opts(holdback_bps=2000, warranty_days=30))
    assert "warranty" in advance.quote(doc, c.order(held), now=c.now(), wf_repo=WF_REPO)["why"][0]
    with_hb = advance.offer(doc["advancer"], doc["mint"], RATE, 500 * USDC, holdback=True)
    q = advance.quote(with_hb, c.order(held), now=c.now())
    assert (q["at_acceptance"], q["after_warranty"]) == (80 * USDC, 20 * USDC)
    for bad in (dict(rate_bps=0), dict(rate_bps=6000), dict(cap=0), dict(evaluators=["x"]), dict(assurances=["blessed"])):
        with pytest.raises(ValueError):
            advance.offer(**{"advancer": doc["advancer"], "mint": doc["mint"], "rate_bps": RATE, "cap": 1, **bad})
    assert advance.discount(1, 200) == 1 and DAY == 86_400                    # the discount rounds up: never more advanced than stated
    assert any("Knos charges nothing" in line for line in advance.lines(advance.quote(doc, o, now=c.now(), wf_repo=WF_REPO)))


def test_the_command_writes_an_offer_that_checks_and_says_knos_is_not_the_lender(tmp_path):
    import json

    import typer
    from typer.testing import CliRunner
    app, helped = typer.Typer(), []
    advance.register(app, helped)

    @app.command("other")
    def other() -> None:          # a second command, so `advance` stays a group
        pass
    out = tmp_path / "offer.json"
    wallet = str(Keypair.from_seed(bytes([9]) * 32).pubkey())
    done = CliRunner().invoke(app, ["advance", "offer", wallet, "--rate", "2", "--cap", "500", "--out", str(out)])
    assert done.exit_code == 0, done.output
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert advance.check(doc) is None and (doc["rate_bps"], doc["cap"], doc["advancer"]) == (200, 500 * USDC, wallet)
    assert doc["not_knos"] == advance.NOT_KNOS and doc["recourse"].startswith("none on chain") and helped[0][0] == "advance"
    assert {"offer", "take", "status"} <= set(CliRunner().invoke(app, ["advance", "--help"]).output.split())
