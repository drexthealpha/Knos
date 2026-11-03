"""H2: x402.settle serves the report only for a confirmed transaction that moved exactly the order's amount, in its mint,
into its payTo account. Wrong amount, wrong payee, a failed transaction or a changed requirement are refused. No chain:
the RPC answers are recorded shapes of getTransaction (jsonParsed)."""
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from knos_wanted import escrow, x402

MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")
KEY = Keypair.from_seed(bytes([7]) * 32)
PAYER = "Pay3r111111111111111111111111111111111111111"
OTHER = "0ther11111111111111111111111111111111111111"


@pytest.fixture
def order(monkeypatch):
    monkeypatch.setattr(escrow, "ledger", lambda: type("L", (), {"url": "https://api.devnet.solana.com"})())
    monkeypatch.setattr(escrow, "mint", lambda led, create=True: MINT)
    monkeypatch.setattr(escrow, "demo_key", lambda: KEY)
    acc = x402.challenge("a" * 64, "https://knos.example")["accepts"][0]
    return acc


def chain_that_moved(monkeypatch, to: str, amount: int, err=None) -> list:
    """sendTransaction and confirmation succeed; getTransaction shows `amount` base units of the mint moved into `to`."""
    from knos import chain
    calls = []
    tx = {"meta": {"err": err,
                   "preTokenBalances": [{"accountIndex": 1, "mint": str(MINT), "uiTokenAmount": {"amount": "0"}}],
                   "postTokenBalances": [{"accountIndex": 1, "mint": str(MINT), "uiTokenAmount": {"amount": str(amount)}}]},
          "transaction": {"message": {"accountKeys": [{"pubkey": PAYER}, {"pubkey": to}]}}}

    def fake(url, method, params, timeout=10):
        calls.append(method)
        return {"sendTransaction": "5" * 64, "getSignatureStatuses": {"value": [{"confirmationStatus": "confirmed"}]},
                "getTransaction": tx}[method]
    monkeypatch.setattr(chain, "call", fake)
    return calls


def pay(acc: dict) -> str:
    return x402.header({"x402Version": 2, "accepted": acc, "payload": {"transaction": "T" * 200}})


def test_the_exact_payment_is_served(order, monkeypatch):
    chain_that_moved(monkeypatch, order["payTo"], int(order["amount"]))
    out = x402.settle(pay(order))
    assert out["success"] and out["payer"] == PAYER and out["amount"] == order["amount"]


def test_a_wrong_amount_is_refused(order, monkeypatch):
    chain_that_moved(monkeypatch, order["payTo"], int(order["amount"]) // 2)
    with pytest.raises(ValueError, match="not the 1000000 this order asks"):
        x402.settle(pay(order))


def test_a_wrong_payee_is_refused(order, monkeypatch):
    chain_that_moved(monkeypatch, OTHER, int(order["amount"]))
    with pytest.raises(ValueError, match="moved 0 base units"):
        x402.settle(pay(order))


def test_a_failed_transaction_is_refused(order, monkeypatch):
    chain_that_moved(monkeypatch, order["payTo"], int(order["amount"]), err={"InstructionError": [0, "Custom"]})
    with pytest.raises(ValueError, match="moved 0 base units"):
        x402.settle(pay(order))


def test_a_changed_requirement_is_refused_before_anything_is_sent(order, monkeypatch):
    calls = chain_that_moved(monkeypatch, OTHER, 1)
    for change in ({"amount": "1"}, {"payTo": OTHER}, {"asset": OTHER}):
        with pytest.raises(ValueError, match="not the requirement this server offers"):
            x402.settle(pay({**order, **change}))
    assert calls == []
