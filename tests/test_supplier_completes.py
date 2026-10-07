"""A supplier completes when the buyer goes quiet: the path that exists, walked on the simulator (LiteSVM, the second
deployment's knos_pay test build). The buyer funds and then does nothing more. The supplier's own wallet sends the
proof the forge signed and is paid; the buyer cannot take the money back before the deadline; a rejection is appealed
while the money stays where it is; and with no proof by the deadline the money goes back to the funder and nobody else.
docs/FINANCE.md, "When the buyer goes quiet", is this test in words."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

import test_pay2_chain as P  # noqa: E402
from _pay2 import WF_REPO, WF_SHA, Chain  # noqa: E402

from knos import appeal, ids  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
USDC, DAY, SUPPLIER = P.USDC, P.DAY, 6_100_001          # the supplier's GitHub id: nobody else in the suite uses it
NOW = 1_790_000_000.0


def test_the_supplier_is_paid_on_the_forges_signature_while_the_buyer_does_nothing():
    c = P.setup(Chain())
    buyer, buyer_tok = c.funder, c.funder_tok
    supplier, _ = c.wallet(c.usdc)                             # the supplier's own wallet: it pays its own transaction fees
    paid_to = supplier.pubkey()
    c.token_account(paid_to, c.usdc)
    vault, start = pay.vault_pda(c.usdc), c.balance(buyer_tok)

    # 1. The buyer funds 100.00 for 14 days. That is the last thing the buyer signs.
    n = P.issue()
    assert c.send([pay.fund_wallet_ix(buyer.pubkey(), buyer_tok, c.usdc, P.REPO, n, 100 * USDC, WF_REPO, WF_SHA, P.TERMS, mode=pay.TESTS, work_s=14 * DAY)], buyer), c.err
    job = pay.job_pda(P.REPO, n, buyer.pubkey())
    j = pay.read_job(c.data(job))
    assert (j.state, j.amount, j.deadline, j.refund_to) == ("open", 100 * USDC, c.now() + 14 * DAY, buyer.pubkey())
    assert c.balance(vault) == 100 * USDC and c.balance(buyer_tok) == start - 100 * USDC

    # 2. The buyer changes its mind and wants the money back. Before the deadline nobody can take it out, the buyer included.
    back = pay.refund_ix(buyer.pubkey(), job, j)
    assert not c.send([back], buyer) and P.code(c) == 83
    c.warp(13 * DAY)
    assert not c.send([back], buyer) and P.code(c) == 83 and c.balance(vault) == 100 * USDC

    # 3. A rejection is appealed: the verdict is disputed, the appeal costs the supplier nothing, and the money does not move.
    a = appeal.open_(repo="acme/app", pull=41, supplier="dana", by="dana", reason="the suite's fixture is stale", at=NOW, scope=str(job), key=n,
                     artifact=P.HEAD, evaluator="knos", run=7, terms_hash=j.terms.hex(), mode="tests", order_state="open")
    assert (a["verdict"], a["was"], a["state"], a["cost"]["supplier"]) == ("disputed", "rejected", "open", 0) and a["verdict"] in ids.VERDICTS
    assert "stays in escrow" in a["money"] and "before the order's deadline" in a["money"] and c.balance(vault) == 100 * USDC
    assert not c.send([back], buyer) and P.code(c) == 83                       # an open appeal gives the buyer no way out either
    with pytest.raises(appeal.Refused):                                          # only the supplier appeals its own rejection
        appeal.open_(repo="acme/app", pull=41, supplier="dana", by="the-buyer", reason="no", at=NOW, scope=str(job), key=n, terms_hash=j.terms.hex())
    won = appeal.resolve(appeal.asked(a, NOW + 60, "https://github.com/judge/knos/actions/runs/9"), NOW + 120,
                         rerun={"v": 1, "reexecuted": True, "passed": True, "repository": "acme/app", "pull": 41, "reasons": []})
    assert (won["state"], won["verdict"]) == ("accepted", "accepted")           # the neutral judge ran the suite itself: the rejection is overturned

    # 4. The supplier settles itself. The proof is the forge's signature over the pinned workflow's run; the supplier's
    #    wallet sends it and pays the fee. No signature of the buyer is in the transaction.
    tok = P.pay_token(c, job, SUPPLIER, paid_to)
    ix = P.pay_ix(c, supplier.pubkey(), tok, c.key, job, j, SUPPLIER, paid_to)
    assert buyer.pubkey() not in [m.pubkey for m in ix.accounts if m.is_signer]
    assert c.send([ix], supplier), c.err
    fee = pay.fee_of(100 * USDC)
    assert c.balance(pay.ata(paid_to, c.usdc)) == 100 * USDC - fee and c.balance(vault) == 0 and c.data(job) is None
    assert c.said("knos2:")[0].startswith(f"knos2:paid repo={P.REPO} issue={n} payee={SUPPLIER} amount={100 * USDC - fee} fee={fee}")

    # 5. The deadline passes. There is nothing left for the buyer to take back, and the proof pays nothing twice.
    c.warp(2 * DAY)
    assert not c.send([back], buyer) and c.balance(buyer_tok) == start - 100 * USDC
    assert not c.send([P.pay_ix(c, supplier.pubkey(), P.pay_token_for(c, j, SUPPLIER, paid_to), c.key, job, j, SUPPLIER, paid_to)], supplier) and P.code(c) == 82


def test_with_no_accepted_work_by_the_deadline_the_money_goes_back_to_the_funder_and_to_nobody_else():
    c = P.setup(Chain())
    buyer_tok = c.funder_tok
    supplier, supplier_tok = c.wallet(c.usdc)
    start = c.balance(buyer_tok)
    job = P.fund_wallet(c, amount=40 * USDC, work_s=600)
    j = pay.read_job(c.data(job))
    c.warp(601)
    # after the deadline a proof pays nothing: the supplier's side of the bargain has a clock too
    assert not c.send([P.pay_ix(c, supplier.pubkey(), P.pay_token(c, job, SUPPLIER, supplier.pubkey()), c.key, job, j, SUPPLIER, supplier.pubkey())], supplier) and P.code(c) == 83
    # anyone may send the refund, the supplier too; it lands in the funder's own account whoever sends it
    assert not c.send([pay.refund_ix(supplier.pubkey(), job, j, supplier_tok)], supplier) and P.code(c) == 88
    assert c.send([pay.refund_ix(supplier.pubkey(), job, j)], supplier), c.err
    assert c.balance(buyer_tok) == start and c.balance(supplier_tok) == 0 and c.data(job) is None
    assert "went back to its funder" in appeal.money("refunded")                 # and an appeal after that says where the money went


def test_the_document_walks_the_same_path():
    doc = (ROOT / "docs" / "FINANCE.md").read_text(encoding="utf-8")
    at = doc.index("When the buyer goes quiet")
    part = doc[at:doc.index("\n## ", at + 5)] if "\n## " in doc[at + 5:] else doc[at:]
    for said in ("tests/test_supplier_completes.py", "/knos appeal", "before the deadline", "supplier's own wallet", "refund", "simulator",
                 "DISPUTES.md", "not exercised on the public program ids"):
        assert said in part, said
