"""The relay kind `/knos passkey-fund <base64url>` inside LiteSVM, beside the test build of knos_pay and the real
knos_passkey: a comment is parsed (knos.commands), the intent is read (passkey_fund.read_intent), and the relay sends
Open, the rent of the order, the secp256r1 check and Fund in one transaction it pays for. The funder is the software
passkey of tests/test_passkey_chain.py and holds no SOL. Every refusal is known before anything is sent, and is a
plain reply.
"""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from _order import REPO, TH, USDC, issue  # noqa: E402
from _pay2 import ChainLedger  # noqa: E402
from _pay21 import each_build, pay21_build  # noqa: E402, F401 - the fixtures `build` and `pay21`: every test here runs on knos_pay 2.2 and on the live 2.1
from test_passkey_chain import Passkey  # noqa: E402
from test_passkey_fund import World  # noqa: E402

from knos import commands  # noqa: E402
from knos.settle.v2 import passkey as pk  # noqa: E402
from knos.settle.v2 import passkey_fund as pf  # noqa: E402
from knos.settle.v2 import pay, relay  # noqa: E402


class Counted(ChainLedger):
    """The harness's ledger, counting what was sent."""
    def send(self, ixs, payer, signers=None) -> str:
        self.sent = getattr(self, "sent", 0) + 1
        return super().send(ixs, payer, signers)


@pytest.fixture()
def w(build) -> World:
    """The passkey's world on the knos_pay build under test: the relay decides by the Version it answers. (The 2.1
    build replaces the tree's at the same address before any order exists.)"""
    world = World()
    if not build.new:
        world.svm.add_program_from_file(pay.PAY_ID, build.build)
    world.build = build
    return world


def comment(w: World, n: int, *, amount: int = 20 * USDC, p: Passkey | None = None, nonce: int | None = None, expiry: int | None = None, signed: dict | None = None,
            **kw) -> str:
    """What the Buy page shows after the passkey signed: the one line to post on the issue."""
    p = p or w.p
    data = w.data_of(n, amount, p=p, **kw)
    expiry = w.slot() + 150 if expiry is None else expiry
    nonce = w.nonce(p) + 1 if nonce is None else nonce
    auth, cdj, sig = p.get(pf.fund_challenge(**(dict(mint=w.usdc, data=data, expiry_slot=expiry, nonce=nonce) | (signed or {}))))
    return pf.intent_comment(pf.Intent(p.key, w.usdc, pay.TOKEN, data, expiry, nonce, auth, cdj, pk.raw_signature(sig)))


def test_a_comment_funds_the_order_and_the_same_comment_again_is_refused(w: World):
    net, n = Counted(w), issue()
    line = comment(w, n)
    cmd = commands.parse(f"Funding this from the Buy page.\n\n{line}\n", on_pull=False)
    assert isinstance(cmd, commands.PasskeyFund) and f"{pf.COMMENT} {cmd.intent}" == line
    relay_sol, wallet_sol, had = w.lamports(w.payer.pubkey()), w.lamports(w.p.wallet), w.balance(w.source)
    r = relay.passkey_fund(net, w.payer, cmd.intent, REPO, n)
    order = pf.order_of(w.p.wallet, w.data_of(n))
    o = w.order(order)
    assert r == {"ok": True, "kind": "passkey-fund", "sigs": r["sigs"], "wallet": str(w.p.wallet), "order": str(order), "mint": str(w.usdc), "repo_id": REPO,
                 "issue": n, "amount": 20 * USDC, "nonce": 1, "fee": o.fee, "deadline": o.deadline}, r
    assert (o.amount, o.repo_id, o.issue, o.terms, o.source, o.refund_to) == (20 * USDC, REPO, n, TH, w.p.wallet, w.p.wallet)
    # the fee the live build escrows on 20.00: 0.50 under 2.1 (2.5%), 0.06 under 2.2 (0.30%)
    assert relay.version(net, w.payer) == w.build.pick(1, 2) and o.fee == w.build.pick(500_000, 60_000)
    assert w.held(order) == 20 * USDC + o.fee == had - w.balance(w.source) and w.nonce() == 1
    # one transaction; the funder spent no SOL, the relay paid the rent of the order and of its token account
    assert net.sent == 1 and w.lamports(w.p.wallet) == wallet_sol and relay_sol - w.lamports(w.payer.pubkey()) >= sum(w.rent)
    assert (relay._rent(pf.ORDER_LEN), relay._rent(165)) == w.rent
    said = relay.passkey_fund_reply(r)
    assert said.startswith(f"Knos: funded from a passkey wallet. {20 * USDC} units of the test token {w.usdc} is in escrow for issue #{n}") and f"`{order}`" in said
    devnet = relay.passkey_fund_reply(r | {"mint": str(pay.USDC_DEVNET)})   # Circle's devnet USDC, as the site funds: said as money
    assert devnet.startswith(f"Knos: funded from a passkey wallet. 20.00 test USDC is in escrow for issue #{n}, and the wallet paid {w.build.pick('0.50', '0.06')} test USDC fee on top. ")
    assert "anyone can send it back to the wallet" in devnet and "The funder paid no SOL" in devnet
    # the same comment again (a replay, by anyone): refused from a read, nothing sent, nothing moved
    before = (w.balance(w.source), w.lamports(w.payer.pubkey()))
    again = relay.passkey_fund(net, w.payer, line, REPO, n)
    assert not again["ok"] and "this funding was sent already" in again["why"] and net.sent == 1
    assert (w.balance(w.source), w.lamports(w.payer.pubkey())) == before and w.nonce() == 1
    assert relay.passkey_fund_reply(again).startswith("Knos: nothing was funded and nothing left the passkey wallet: the nonce is not the wallet's nonce plus one")


def test_the_wallet_must_hold_the_fee_the_live_build_takes_on_top(w: World):
    """The wallet holds 1,000.00. An order of 990.00 costs 24.75 on top under 2.1 (2.5%), which the wallet does not
    hold: refused from a read, with what it needs. Under 2.2 it costs 2.97 (0.30%), and the same line funds."""
    net, n = Counted(w), issue()
    had = w.balance(w.source)
    r = relay.passkey_fund(net, w.payer, comment(w, n, amount=990 * USDC), REPO, n)
    if w.build.new:
        assert r["ok"] and r["fee"] == 2_970_000 and had - w.balance(w.source) == 992_970_000 and net.sent == 1, r
    else:
        assert not r["ok"] and "the order's amount and its fee (1014750000 of its smallest units)" in r["why"], r
        assert w.balance(w.source) == had == 1_000 * USDC and getattr(net, "sent", 0) == 0


def test_a_wallet_that_was_never_opened_is_opened_in_the_same_transaction(w: World):
    net, other, n = Counted(w), Passkey(13), issue()
    w.mint_to(w.usdc, w.token_account(other.wallet, w.usdc), 100 * USDC)
    assert w.data(other.wallet) is None
    r = relay.passkey_fund(net, w.payer, comment(w, n, p=other), REPO, n)
    assert r["ok"] and net.sent == 1 and w.nonce(other) == 1 and w.order(pf.order_of(other.wallet, w.data_of(n, p=other))).source == other.wallet


def test_every_refusal_is_a_plain_reply_and_costs_nothing(w: World):
    net, n = Counted(w), issue()
    good = comment(w, n)
    other = Passkey(12)
    expired = comment(w, n, expiry=w.slot() + 5)
    cut = good[:len(good) // 2]
    forged = pf.intent(pf.read_intent(good)) | {"key": other.key.hex(), "wallet": str(other.wallet),
                                               "order": str(pf.order_of(other.wallet, pf.read_intent(good).data))}
    cases = [(good, (REPO, n + 1), "this comment is on another issue"),
             (good, (REPO + 1, n), "this comment is on another issue"),
             (comment(w, n, nonce=2), (REPO, n), "the nonce is not the wallet's nonce plus one"),
             (comment(w, n, amount=5_000 * USDC), (REPO, n), "the wallet holds less of this mint than the order's amount and its fee"),
             (comment(w, n, signed=dict(nonce=7)), (REPO, n), "the passkey signed for another funding"),
             (comment(w, n, signed=dict(data=w.data_of(n, 21 * USDC))), (REPO, n), "the passkey signed for another funding"),
             (forged, (REPO, n), "the passkey's signature does not verify"),      # another key in the line: its wallet is not open and holds nothing
             (cut, (REPO, n), "not a passkey funding intent"),
             (f"{pf.COMMENT} {'A' * 400}", (REPO, n), "not a passkey funding intent"),
             ("%%%", (REPO, n), "not a passkey funding intent")]
    w.mint_to(w.usdc, w.token_account(other.wallet, w.usdc), 100 * USDC)
    before = (w.balance(w.source), w.lamports(w.payer.pubkey()), w.nonce())
    for line, (repo, number), want in cases:
        r = relay.passkey_fund(net, w.payer, line, repo, number)
        assert not r["ok"] and r["kind"] == "passkey-fund" and want in r["why"], (want, r)
        assert relay.passkey_fund_reply(r).startswith("Knos: nothing was funded and nothing left the passkey wallet: ")
    w.svm.warp_to_slot(w.slot() + 6)                                      # past the slot the passkey signed for
    r = relay.passkey_fund(net, w.payer, expired, REPO, n)
    assert not r["ok"] and r["why"] == f"{pf.ERRORS[123]} (error 123)", r
    assert getattr(net, "sent", 0) == 0 and (w.balance(w.source), w.lamports(w.payer.pubkey()), w.nonce()) == before
    # a ledger that cannot simulate sends nothing
    blind = Counted(w)
    blind.simulate = None
    assert relay.passkey_fund(blind, w.payer, good, REPO, n)["why"] == "this relay's ledger cannot simulate, and a passkey's funding is never sent unchecked"
    # and the good line, untouched by all of that, still funds what it says; a second order of the issue is then its own
    assert relay.passkey_fund(net, w.payer, good, REPO, n)["ok"] and net.sent == 1
    r = relay.passkey_fund(net, w.payer, comment(w, n), REPO, n)
    assert not r["ok"] and "there is an order at that address already" in r["why"]
    assert relay.passkey_fund(net, w.payer, comment(w, n, seq=1), REPO, n)["ok"] and w.nonce() == 2


def test_the_comment_is_parsed_only_whole_and_only_on_an_issue(w: World):
    line = comment(w, issue())
    assert isinstance(commands.parse(line), commands.PasskeyFund) and isinstance(commands.parse(line.replace("/knos passkey-fund", "/KNOS Passkey-Fund")), commands.PasskeyFund)
    assert len(line) > 1000                                               # longer than any typed command may be
    for bad in ("/knos passkey-fund", "/knos passkey-fund abc", line + " and thanks", line.replace("passkey-fund ", "passkey-fund  x ")):
        got = commands.parse(bad)
        assert isinstance(got, commands.Error) and got.kind == "malformed" and got.command == "passkey-fund" and "Sign again on the Buy page" in got.reply, bad
    got = commands.parse(line, on_pull=True)
    assert isinstance(got, commands.Error) and got.kind == "misplaced" and got.reply == "Knos: `/knos passkey-fund` belongs on the issue, not on a pull request. Comment it there."
    assert isinstance(commands.parse("/knos passkey-funds 1"), commands.Error) and commands.parse("/knos passkey-funds 1").kind == "unknown"
    assert "passkey-fund" not in commands.FORMS                           # not a command to type: `/knos help` does not list it
