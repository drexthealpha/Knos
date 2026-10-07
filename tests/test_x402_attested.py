"""examples/x402_attested and docs/X402.md: the proposed x402 "knos-order" scheme. The chain the example replays is what
the test build of knos_pay does now (the fixture is current), the example's own tests pass (a server and a client over
HTTP), the page states plainly that it is a proposal, and the messages it prints are the example's."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "examples" / "x402_attested"


def test_the_replayed_chain_is_what_knos_pay_does():
    pytest.importorskip("solders.litesvm")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "x402_fixture.py"), "--check"], capture_output=True, text=True, check=False,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert r.returncode == 0, r.stderr or r.stdout
    from knos import fees
    from knos.settle.v2 import pay
    fx = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
    o = pay.read_order(bytes.fromhex(fx["order"]["data"]))
    assert (str(o.address()), o.amount, o.fee, str(o.source), o.state) == (fx["order"]["address"], fx["amount"], fx["fee"], fx["buyer"], "open")
    # the fee is the one of the build the fixture was recorded on (knos.fees: 2 is knos_pay 2.2 and the 0.3.18 fee)
    assert fx["fee"] == fees.rule(fx["fee_version"]).order(fx["amount"]) and fx["paid"]["received"] == fx["amount"]   # the seller receives the amount whole
    assert fx["refunded"]["logs"] == [f"knos3:refunded order={fx['order']['address']} amount={fx['amount'] + fx['fee']}"]


def test_the_page_says_it_is_a_proposal_and_prints_the_examples_messages():
    page = (ROOT / "docs" / "X402.md").read_text(encoding="utf-8")
    assert "**This is a proposal. It is not part of x402**" in page.split("##")[0]
    blocks = {m.group(1): json.loads(m.group(2)) for m in re.finditer(r"<!-- message: (\w+) -->\s*```json\n(.*?)\n```", page, re.S)}
    assert blocks == json.loads((HERE / "messages.json").read_text(encoding="utf-8")) and len(blocks) == 5
    req = blocks["paymentRequired"]["accepts"][0]
    assert req["scheme"] == "knos-order" and set(req) == {"scheme", "network", "amount", "asset", "payTo", "maxTimeoutSeconds", "extra"}
    assert {"program", "order", "termsHash"} <= set(req["extra"]) and blocks["paymentPayload"]["payload"]["order"] == req["extra"]["order"]
    # node and sdk/settle only: no package of its own
    assert not (HERE / "package.json").exists()
    imports = {m for f in HERE.glob("*.mjs") for m in re.findall(r'from "([^"]+)"', f.read_text(encoding="utf-8"))}
    assert all(i.startswith(("node:", "./")) or i == "../../sdk/settle/index.js" for i in imports), imports


def test_the_example_runs_a_server_and_a_client():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: install Node 20 or later")
    done = subprocess.run([node, "--test", "--test-reporter=tap", "examples/x402_attested/test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and re.search(r"^# pass 5$", done.stdout, re.M) and re.search(r"^# fail 0$", done.stdout, re.M), done.stdout[-3000:]


def test_the_offer_a_seller_copies_and_the_pages_messages_carry_terms_a_judge_can_read():
    # rehearsed on devnet (0.3.14): offer.devnet.json carried terms knos.terms.parse refuses, so the judge could never
    # pass an order funded with them and it could only go back at its deadline
    from knos import terms
    offer = json.loads((HERE / "offer.devnet.json").read_text(encoding="utf-8"))
    assert terms.parse(offer["terms"]) == json.loads(offer["terms"])
    fx = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
    req = json.loads((HERE / "messages.json").read_text(encoding="utf-8"))["paymentRequired"]["accepts"][0]
    assert fx["terms"] == req["extra"]["terms"] == offer["terms"] and req["extra"]["termsHash"] == terms.terms_hash(offer["terms"].encode())


# ---- the live path: the same server and client over an RPC URL, here LiteSVM behind tests/_rpc_shim.py -----------------
def _live(tmp_path, issue: int):
    """A chain, an RPC endpoint in front of it, a buyer with 100 test USDC, and an offer for `issue`. Returns what a test needs."""
    sys.path.insert(0, str(ROOT / "tests"))
    from _order import REPO, OrderChain
    from _pay2 import WF_REPO, WF_SHA
    from _rpc_shim import RpcShim
    from solders.keypair import Keypair
    from knos.settle.v2 import pay
    c = OrderChain()
    buyer, seller = Keypair.from_seed(bytes([41]) * 32), Keypair.from_seed(bytes([42]) * 32)
    c.svm.airdrop(buyer.pubkey(), 10 ** 9)
    tok = c.token_account(buyer.pubkey(), c.usdc)
    c.mint_to(c.usdc, tok, 100 * 10 ** 6)
    shim = RpcShim(c)
    (tmp_path / "buyer.json").write_text(json.dumps(list(bytes(buyer))), encoding="utf-8")
    offer = {"url": f"https://seller.example/work/{issue}", "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", "program": str(pay.PAY_ID), "mint": str(c.usdc),
             "amount": 20_000_000, "workSeconds": 7 * 86_400, "repoId": str(REPO), "issue": str(issue), "seq": 0, "mode": pay.MERGE, "terms": json.loads((HERE / "offer.devnet.json").read_text(encoding="utf-8"))["terms"],
             "wfRepo": WF_REPO, "wfSha": WF_SHA, "seller": {"githubId": "5550123", "wallet": str(seller.pubkey())}, "delivery": "https://github.com/octo/widgets/pull/12"}
    (tmp_path / "offer.json").write_text(json.dumps(offer), encoding="utf-8")

    def live(*args, ok=True):
        done = shim.run([shutil.which("node"), "examples/x402_attested/live.mjs", *args, "--rpc", shim.url], cwd=ROOT)
        assert (done.returncode == 0) == ok, done.stderr or done.stdout
        return json.loads(done.stdout) if ok else done.stderr
    return c, shim, live, buyer, seller, tok, offer


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed: install Node 20 or later")
def test_live_the_client_funds_a_real_order_over_rpc_is_served_and_the_seller_is_paid_on_acceptance(tmp_path):
    pytest.importorskip("solders.litesvm")
    from solders.pubkey import Pubkey
    from knos import fees
    from knos.settle.v2 import pay
    c, shim, live, buyer, seller, tok, offer = _live(tmp_path, 77)
    from _pay2 import ChainLedger
    try:
        got = live("run", "--key", str(tmp_path / "buyer.json"), "--offer", str(tmp_path / "offer.json"))
        order = Pubkey.from_string(got["order"])
        # the program ran: the order exists with the 402's terms, and the buyer's money (the amount and the fee) is in it
        o = c.order(order)
        fee = fees.live(ChainLedger(c)).order(offer["amount"])       # the fee of the build under test: the 402 and the program agree on it
        assert (got["status"], o.state, o.amount, o.fee, o.source, o.terms) == (200, "open", offer["amount"], fee, buyer.pubkey(), pay.terms_hash(offer["terms"].encode()))
        assert c.held(order) == offer["amount"] + fee and c.balance(tok) == 100 * 10 ** 6 - offer["amount"] - fee
        assert got["transaction"] in shim.txs and "sendTransaction" in shim.calls        # a transaction this process signed, verified by the chain
        assert got["delivery"]["delivered"] == offer["delivery"] and got["state"] == {"order": got["order"], "state": "escrowed", "deadline": o.deadline}
        assert got["settlement"]["extensions"]["knos-order"]["info"]["state"] == "escrowed" and got["settlement"]["payer"] == str(buyer.pubkey())
        # the acceptance: a token GitHub would sign from the order's pinned workflow pays the seller the amount whole
        c.warp(3600)
        shim.harness_version = 1            # a relay carries PayOrder in a version 1 transaction: the status reads it as one
        assert c.pay(order, [(5550123, 10_000, seller.pubkey())], pr=12), c.err
        assert c.balance(pay.ata(seller.pubkey(), c.usdc)) == offer["amount"] and c.order(order) is None
        assert live("status", "--order", got["order"], "--program", offer["program"]) == {
            "order": got["order"], "state": "paid", "payments": [{"payee": "5550123", "amount": str(offer["amount"]), "to": str(seller.pubkey()), "pr": "12"}]}
        # a client whose limit is under the price signs nothing, and says why
        sent = shim.calls.count("sendTransaction")
        over = live("run", "--key", str(tmp_path / "buyer.json"), "--offer", str(tmp_path / "offer.json"), "--max", "1000000", ok=False)
        assert "over this client's limit" in over and shim.calls.count("sendTransaction") == sent
    finally:
        shim.close()


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed: install Node 20 or later")
def test_live_an_order_nobody_accepted_is_refunded_over_rpc_after_its_deadline(tmp_path):
    pytest.importorskip("solders.litesvm")
    c, shim, live, buyer, _, tok, offer = _live(tmp_path, 78)
    try:
        got = live("run", "--key", str(tmp_path / "buyer.json"), "--offer", str(tmp_path / "offer.json"))
        early = live("refund", "--key", str(tmp_path / "buyer.json"), "--order", got["order"], ok=False)       # before the deadline the program refuses
        assert "live.mjs:" in early and c.balance(tok) < 100 * 10 ** 6
        c.warp(offer["workSeconds"] + 1)
        back = live("refund", "--key", str(tmp_path / "buyer.json"), "--order", got["order"])
        assert back["state"] == "refunded" and c.balance(tok) == 100 * 10 ** 6                                 # the amount and the fee
        assert live("status", "--order", got["order"], "--program", offer["program"])["state"] == "refunded"
    finally:
        shim.close()
