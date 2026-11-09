"""The x402 endpoint (knos.money.x402) on LiteSVM: /fees and /pool are free; /preorder answers 402 with a knos-order
requirement a wallet can fund, and 200 "held" once the chain shows that order in the claim's pool; /checks sells
a pack of paid checks, each call signed by the funding wallet, replays and strangers refused. And the agent tools."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import REPO, TERMS, USDC, OrderChain, issue, user  # noqa: E402
from _pay2 import WF_REPO, WF_SHA, ChainLedger  # noqa: E402

from knos import graduation, record_api as ra  # noqa: E402
from knos.money import agent, fees_config, x402  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

JUDGE = 27_182_818
PASSED = {"passed": True, "spec_hash": "cd" * 32}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    c = OrderChain()
    ids = [user() for _ in range(2)]
    p = graduation.plan(PASSED, claim_id="x402-claim", repo_id=JUDGE, amount=10 * USDC, wf_sha=WF_SHA,
                        contributors=[{"role": "researcher", "github_id": ids[0]}, {"role": "agent", "github_id": ids[1]}])
    seller = Keypair().pubkey()
    n = issue()
    off = ra.offer(str(seller), 4242, str(c.usdc), REPO, n, WF_REPO, WF_SHA, TERMS.decode())
    led = ChainLedger(c)
    state = tmp_path_factory.mktemp("x402") / "checks.json"
    c.state, c.off = state, off
    return c, p, led, x402.Server({"x402-claim": p}, led, str(c.usdc), off, state=state), n


def test_free_routes_and_refusals(world):
    c, p, led, s, _ = world
    st, _, body = s.handle("/fees", {})
    assert st == 200 and body["revenue_today"] == "0" and body["fees"]["bounty"]["rate_bps"] == pay.FEE_BPS
    st, _, body = s.handle("/pool/x402-claim", {})
    assert st == 200 and body["pool"]["locked"] == 0
    assert s.handle("/pool/nobody", {})[0] == 404
    assert s.handle("/fees", {}, method="POST")[0] == 405
    assert s.handle("/nothing", {})[0] == 404
    assert s.handle("/pool/" + "%00", {})[0] == 400


def test_a_preorder_is_402_then_escrowed_on_chain(world):
    c, p, led, s, _ = world
    buyer, tok = c.wallet(c.usdc, 100 * USDC)
    st, h, body = s.handle("/preorder/x402-claim", {"Attested-Payer": str(buyer.pubkey())})
    assert st == 402 and ra.decode(h["payment-required"]) == body
    req = body["accepts"][0]
    assert req["scheme"] == "knos-order" and req["asset"] == str(c.usdc) and req["extra"]["private"] is True
    assert req["extra"]["fee"] == str(fees_config.load().fee("payout", pay.ORDER_MIN_AMOUNT))
    order = req["extra"]["order"]
    assert order == str(graduation.address(p, "pool", buyer.pubkey()))
    pay_hdr = {"PAYMENT-SIGNATURE": ra.encode({"x402Version": 2, "accepted": req, "payload": {"order": order}})}
    st, _, body = s.handle("/preorder/x402-claim", pay_hdr)
    assert st == 402 and "fund it first" in body["error"]
    assert c.send([graduation.preorder_ix(p, buyer.pubkey(), tok, c.usdc, int(req["amount"]))], buyer), c.err
    st, h, body = s.handle("/preorder/x402-claim", pay_hdr)
    assert st == 200 and body["escrowed"] and ra.decode(h["payment-response"])["status"] == "escrowed"
    assert s.handle("/pool/x402-claim", {})[2]["pool"]["buyers"] == 1
    # an order of another pool is not this pool's
    other = graduation.plan(PASSED, claim_id="another", repo_id=JUDGE, amount=10 * USDC, wf_sha=WF_SHA, contributors=[{"role": "researcher", "github_id": 9}])
    assert c.send([graduation.preorder_ix(other, buyer.pubkey(), tok, c.usdc, 5 * USDC)], buyer), c.err
    wrong = str(graduation.address(other, "pool", buyer.pubkey()))
    st, _, body = s.handle("/preorder/x402-claim", {"PAYMENT-SIGNATURE": ra.encode({"x402Version": 2, "accepted": req, "payload": {"order": wrong}})})
    assert st == 402 and "not in this claim's pre-order pool" in body["error"]
    # finding 25: in the pool's scope but pinned to other workflows: refused
    pinned = dict(p, wf_sha="e" * 40)
    assert c.send([graduation.preorder_ix(pinned, buyer.pubkey(), tok, c.usdc, 5 * USDC, seq=1)], buyer), c.err
    other_pin = str(graduation.address(p, "pool", buyer.pubkey(), 1))
    st, _, body = s.handle("/preorder/x402-claim", {"PAYMENT-SIGNATURE": ra.encode({"x402Version": 2, "accepted": req, "payload": {"order": other_pin}})})
    assert st == 402 and "other pinned workflows" in body["error"]
    assert s.handle("/preorder/x402-claim", {"PAYMENT-SIGNATURE": "not base64"})[0] == 400


def test_paid_checks_are_a_pack_each_call_signed_by_the_funder(world):
    c, p, led, s, n = world
    count, price = x402.pack(fees_config.load())
    assert price >= pay.ORDER_MIN_AMOUNT and count * fees_config.micro(fees_config.load().doc["fees"]["x402_check"]["usd_each"]) == price
    st, _, body = s.handle("/checks", {})
    assert st == 402 and body["accepts"][0]["amount"] == str(price) and body["accepts"][0]["extra"]["checks"]["count"] == count
    buyer, tok = c.wallet(c.usdc, 100 * USDC)
    ix = pay.fund_order_wallet_ix(buyer.pubkey(), tok, c.usdc, REPO, n, price, WF_REPO, WF_SHA, TERMS, work_s=7 * 86_400 + 7200)
    assert c.send([ix], buyer), c.err
    order = str(ix.accounts[1].pubkey)

    def call(k: int, signer: Keypair = buyer):
        sig = str(signer.sign_message(x402.check_message(order, k)))
        return s.handle("/checks", {"PAYMENT-SIGNATURE": ra.encode({"x402Version": 2, "accepted": {}, "payload": {"order": order, "n": k, "signature": sig}})})

    st, h, body = call(0)
    assert st == 200 and body["left"] == count - 1 and ra.decode(h["payment-response"])["status"] == "escrowed"
    assert call(0)[0] == 409                    # a replay
    assert call(1, Keypair())[0] == 401         # a stranger names a public order
    assert call(1)[0] == 200
    # finding 26: a restart keeps the count; the calls already sold are replays, the next one goes on
    again = x402.Server({"x402-claim": p}, led, str(c.usdc), c.off, state=c.state)
    s.handle, keep = again.handle, s.handle
    try:
        assert call(1)[0] == 409 and call(0)[0] == 409 and call(2)[0] == 200
    finally:
        s.handle = keep
    with pytest.raises(ValueError):
        x402.Server({}, led, str(c.usdc), c.off)          # paid checks without a state file are refused


def test_the_agent_tools_quote_and_plan_and_never_sign(world):
    c, p, led, _, _ = world
    assert [t["name"] for t in agent.TOOLS] == ["knos_fees", "knos_graduate", "knos_preorder"]
    assert all(t["annotations"]["readOnlyHint"] and t["inputSchema"]["additionalProperties"] is False for t in agent.TOOLS)
    assert agent.call("knos_fees", {"kind": "bounty", "amount": 20 * USDC})["fee"] == 60_000
    assert agent.call("knos_fees", {})["revenue_today"] == "0"
    funder, ftok = c.wallet(c.usdc, 100 * USDC)
    got = agent.call("knos_graduate", {"verdict": PASSED, "claim_id": "agent-claim", "repo_id": JUDGE, "amount": 10 * USDC,
                                       "contributors": [{"role": "researcher", "github_id": 5}], "funder": str(funder.pubkey()),
                                       "funder_token": str(ftok), "mint": str(c.usdc)})
    ixj = got["instruction"]
    ix = Instruction(Pubkey.from_string(ixj["program_id"]), __import__("base64").b64decode(ixj["data"]),
                     [AccountMeta(Pubkey.from_string(a["pubkey"]), a["is_signer"], a["is_writable"]) for a in ixj["accounts"]])
    assert c.send([ix], funder), c.err                # the wallet signs what the tool returned, and the vault opens
    assert graduation.escrow(led, got["plan"], str(c.usdc))["locked"] == 10 * USDC
    pre = agent.call("knos_preorder", {"plan": got["plan"], "buyer": str(funder.pubkey()), "buyer_token": str(ftok), "mint": str(c.usdc),
                                       "amount": 5 * USDC}, ledger=led)
    assert pre["buyer_pays"] == 5 * USDC + pay.FEE_MIN and pre["pool"]["locked"] == 0 and pre["pool"]["mint"] == str(c.usdc)
    for name, args in (("knos_graduate", {"verdict": {"passed": False, "spec_hash": "x"}, "claim_id": "c", "repo_id": 1, "amount": 10 * USDC,
                                         "contributors": [{"role": "researcher", "github_id": 5}]}),
                       ("knos_fees", {"kind": "nope"}), ("knos_preorder", {"plan": {}}), ("nope", {})):
        with pytest.raises(agent.Refused):
            agent.call(name, args)
