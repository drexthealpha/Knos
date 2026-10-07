"""examples/cpi_fund: another Solana program funds a Knos work order by CPI (LiteSVM, beside the test builds of
knos_pay and knos-oidc). A treasury that is a PDA of the example, with no private key, funds an order through
crates/knos-pay-interface: the order exists and says what was asked, the treasury was debited the amount plus the
fee, a top-up by CPI charges the fee on the new amount, a merged change is paid out of it, and an order nobody
delivered returns everything to the treasury after its deadline, by anyone's hand."""
from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("solders.litesvm")

from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.system_program import TransferParams, transfer  # noqa: E402

from _order import AUTHOR, DAY, REPO, TERMS, TH, USDC, OrderChain, code  # noqa: E402
from _pay2 import FIX, WF_REPO, WF_SHA  # noqa: E402

from knos.settle.v2 import pay  # noqa: E402

DAO = Pubkey.from_bytes(hashlib.sha256(b"cpi_fund example program").digest())
CONFIG = Pubkey.find_program_address([b"config"], DAO)[0]
TREASURY = Pubkey.find_program_address([b"treasury"], DAO)[0]


class Dao(OrderChain):
    """The chain of tests/_order.py with the example beside it: its admin, and a treasury holding 1,000 USDC and 1 SOL."""
    def __init__(self):
        super().__init__()
        self.svm.add_program_from_file(DAO, str(FIX / "cpi_fund_v2_real.so"))
        self.admin = self.fund()
        assert self.send([Instruction(DAO, b"\x00", [AccountMeta(self.admin.pubkey(), True, True), AccountMeta(CONFIG, False, True),
                                                     AccountMeta(pay.SYSTEM, False, False)])], self.admin), self.err
        assert self.send([transfer(TransferParams(from_pubkey=self.payer.pubkey(), to_pubkey=TREASURY, lamports=10 ** 9))]), self.err
        self.vault = self.token_account(TREASURY, self.usdc)
        self.mint_to(self.usdc, self.vault, 1_000 * USDC)

    def _ix(self, tag: int, data: bytes, order: Pubkey, admin: Keypair | None, system: bool) -> Instruction:
        a = (admin or self.admin).pubkey()
        tail = ([AccountMeta(pay.SYSTEM, False, False)] if system else []) + [AccountMeta(pay.pause_pda(), False, False), AccountMeta(pay.PAY_ID, False, False)]
        return Instruction(DAO, bytes([tag]) + data, [
            AccountMeta(a, True, False), AccountMeta(CONFIG, False, False), AccountMeta(TREASURY, False, True), AccountMeta(order, False, True),
            AccountMeta(pay.ov_pda(order), False, True), AccountMeta(self.vault, False, True), AccountMeta(self.usdc, False, False),
            AccountMeta(pay.auth_pda(), False, False), AccountMeta(pay.TOKEN, False, False), *tail])

    def dao_fund(self, issue: int, amount: int, seq: int = 0, admin: Keypair | None = None, terms: bytes = TERMS) -> tuple[bool, Pubkey]:
        order = pay.order_pda(pay.scope_of(REPO, issue), TREASURY, seq)
        data = REPO.to_bytes(8, "little") + issue.to_bytes(8, "little") + amount.to_bytes(8, "little") \
            + seq.to_bytes(4, "little") + pay.wf_repo_hash(WF_REPO) + WF_SHA.encode() + terms
        return self.send([self._ix(1, data, order, admin, True)], admin or self.admin, tag="cpi_fund"), order

    def dao_top_up(self, order: Pubkey, add: int, admin: Keypair | None = None) -> bool:
        return self.send([self._ix(2, add.to_bytes(8, "little"), order, admin, False)], admin or self.admin, tag="cpi_top_up")


def test_a_treasury_funds_an_order_by_cpi_and_gets_it_back_when_nobody_delivers():
    c = Dao()
    sol = c.lamports(TREASURY)
    ok, order = c.dao_fund(41, 20 * USDC)
    assert ok, c.err
    # the order exists and is what the treasury asked for; knos_pay holds amount + fee in the order's own account
    o = c.order(order)
    fee = pay.order_fee(20 * USDC)
    assert o is not None and (o.state, o.repo_id, o.issue, o.amount, o.fee, o.mode, o.from_balance) == ("open", REPO, 41, 20 * USDC, fee, pay.MERGE, False)
    assert (o.source, o.refund_to, o.rent_to, o.mint, o.terms, o.deadline) == (TREASURY, TREASURY, TREASURY, c.usdc, TH, c.now() + 14 * DAY)
    assert fee == 60_000 and c.held(order) == 20 * USDC + fee
    assert c.balance(c.vault) == 1_000 * USDC - 20 * USDC - fee                         # debited the amount plus the fee
    rent = sol - c.lamports(TREASURY)
    assert rent == c.lamports(order) + c.lamports(pay.ov_pda(order)) == 6_493_680       # the rent of the two accounts, and no more
    assert any(line.startswith(f"cpi_fund: order {order} for issue 41") for line in c.said("cpi_fund:"))
    print("\nCU of FundOrderWallet inside the example's CPI:", c.cu["cpi_fund"][-1])
    # only the admin spends the treasury; the same order cannot be funded twice; knos_pay's bounds hold through the CPI
    stranger = c.fund()
    assert not c.dao_fund(42, 20 * USDC, admin=stranger)[0]
    assert not c.dao_fund(41, 20 * USDC)[0] and code(c) == 101
    assert not c.dao_fund(43, 4 * USDC)[0] and code(c) == 81
    # a top-up by CPI: the treasury signs as the order's source, and pays the fee on the new amount less what it paid
    assert c.dao_top_up(order, 60 * USDC), c.err
    o = c.order(order)
    assert (o.amount, o.fee) == (80 * USDC, pay.order_fee(80 * USDC)) and c.held(order) == 80_240_000
    assert c.balance(c.vault) == 1_000 * USDC - 80_240_000
    assert not c.dao_top_up(order, USDC, admin=stranger)
    # nobody delivers. Before the deadline nothing comes back; after it anyone sends knos_pay's RefundOrder, and
    # the treasury has every token and every lamport it had
    assert not c.refund(order) and code(c) == 83
    c.warp(14 * DAY + 1)
    assert c.refund(order), c.err
    assert c.order(order) is None and c.data(pay.ov_pda(order)) is None
    assert c.balance(c.vault) == 1_000 * USDC and c.lamports(TREASURY) == sol


def test_an_order_the_treasury_funded_pays_the_author_of_the_merged_change():
    c = Dao()
    ok, order = c.dao_fund(51, 100 * USDC, seq=2)
    assert ok, c.err
    author, _ = c.wallet(c.usdc)
    payees = [(AUTHOR, 10_000, author.pubkey())]
    assert c.pay(order, payees), c.err                    # GitHub signed that the pinned prove.yml saw the terms met
    assert c.balance(pay.ata(author.pubkey(), c.usdc)) == 100 * USDC      # the author receives the amount whole
    assert c.balance(c.fee) + c.balance(c.tip) == pay.order_fee(100 * USDC) == 300_000
    assert c.balance(c.vault) == 1_000 * USDC - 100_300_000 and c.order(order) is None
    assert c.lamports(TREASURY) == 10 ** 9                # the rent of the closed order came back to the treasury
