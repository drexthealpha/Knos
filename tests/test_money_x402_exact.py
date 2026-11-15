"""x402 v2 `exact` on Solana for one paid check (knos.money.x402_exact + the /checks route of knos.money.x402), with
a stand-in facilitator; the Bazaar discovery extension on every 402. The same payment settled through the public
testnet facilitator on devnet is in docs/reference/X402.md ("exact")."""
from __future__ import annotations

import base64
import json

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import to_bytes_versioned
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from knos import record_api as ra
from knos.money import fees_config, x402, x402_exact as X
from knos.settle.v2 import pay

MINT, PAY_TO, FEE_PAYER = str(Keypair().pubkey()), str(Keypair().pubkey()), str(Keypair().pubkey())
SUPPORTED = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": "eip155:84532"},
                       {"x402Version": 2, "scheme": "exact", "network": X.DEVNET, "extra": {"feePayer": FEE_PAYER}}]}


class Fac(X.Facilitator):
    def __init__(self, valid=True, settle=None):
        self.calls = []

        def post(path, body):
            self.calls.append((path, body))
            if path == "/verify":
                return {"isValid": valid, "payer": "P", **({} if valid else {"invalidReason": "invalid_exact_svm_payload_transaction_amount_mismatch"})}
            return settle or {"success": True, "transaction": "SIG1", "network": X.DEVNET, "payer": "P"}
        super().__init__("https://facilitator.invalid", post=post, get=lambda path: SUPPORTED)


def test_the_payment_is_a_v0_transfer_the_payer_signed_and_the_fee_payer_did_not():
    payer = Keypair()
    req = X.requirement(20_000, MINT, PAY_TO, FEE_PAYER)
    assert req == {"scheme": "exact", "network": X.DEVNET, "amount": "20000", "asset": MINT, "payTo": PAY_TO,
                   "maxTimeoutSeconds": 60, "extra": {"feePayer": FEE_PAYER}}
    p = X.payment(req, payer, Hash.default(), decimals=6, nonce="ab" * 16)
    assert p["x402Version"] == 2 and p["accepted"] == req
    tx = VersionedTransaction.from_bytes(base64.b64decode(p["payload"]["transaction"]))
    msg = tx.message
    keys = list(msg.account_keys)
    assert str(keys[0]) == FEE_PAYER and msg.header.num_required_signatures == 2
    progs = [str(keys[ix.program_id_index]) for ix in msg.instructions]
    assert progs == ["ComputeBudget111111111111111111111111111111", "ComputeBudget111111111111111111111111111111", str(pay.TOKEN), X.MEMO]
    transfer = msg.instructions[2]
    assert bytes(transfer.data) == bytes([12]) + (20_000).to_bytes(8, "little") + bytes([6])
    accts = [str(keys[i]) for i in transfer.accounts]
    m, me = Pubkey.from_string(MINT), payer.pubkey()
    assert accts == [str(pay.ata(me, m)), MINT, str(pay.ata(Pubkey.from_string(PAY_TO), m)), str(me)]
    assert FEE_PAYER not in accts                                                  # the fee payer moves nothing
    assert bytes(msg.instructions[3].data) == b"ab" * 16 and not msg.instructions[3].accounts
    sigs = list(tx.signatures)
    assert sigs[0] == tx.signatures[0].default() and sigs[1].verify(me, to_bytes_versioned(msg))
    price = msg.instructions[1]
    assert int.from_bytes(bytes(price.data)[1:9], "little") <= 5_000_000           # at most 5 lamports a unit


def test_a_memo_the_server_asks_for_is_the_memo_and_each_payment_has_its_own_nonce():
    req = X.requirement(1, MINT, PAY_TO, FEE_PAYER, memo="order-7")
    tx = VersionedTransaction.from_bytes(base64.b64decode(X.payment(req, Keypair(), Hash.default(), decimals=6)["payload"]["transaction"]))
    assert bytes(tx.message.instructions[3].data) == b"order-7"
    a, b = (X.payment(X.requirement(1, MINT, PAY_TO, FEE_PAYER), Keypair(), Hash.default(), decimals=6) for _ in range(2))
    assert a["payload"] != b["payload"]


def test_the_facilitator_names_its_fee_payer_and_settles_after_it_verifies():
    f = Fac()
    assert f.fee_payer() == FEE_PAYER and f.fee_payer("solana:mainnet") is None
    req = X.requirement(1, MINT, PAY_TO, FEE_PAYER)
    assert f.verify_and_settle({"payload": {}}, req)["transaction"] == "SIG1"
    assert [c[0] for c in f.calls] == ["/verify", "/settle"]
    assert f.calls[0][1] == {"x402Version": 2, "paymentPayload": {"payload": {}}, "paymentRequirements": req}
    bad = Fac(valid=False)
    with pytest.raises(X.Refused, match="amount_mismatch"):
        bad.verify_and_settle({}, req)
    assert [c[0] for c in bad.calls] == ["/verify"]                                # nothing is settled that did not verify


def test_a_pending_settlement_is_decided_by_the_chain():
    pending = {"success": False, "errorReason": "settlement_pending", "transaction": "SIG2", "network": X.DEVNET, "payer": "P"}
    seen = []
    got = Fac(settle=pending).verify_and_settle({}, X.requirement(1, MINT, PAY_TO, FEE_PAYER), confirm=seen.append)
    assert got["success"] and got["transaction"] == "SIG2" and got["confirmedBy"] == "chain" and seen == ["SIG2"]

    def lost(sig):
        raise TimeoutError("not confirmed")
    with pytest.raises(X.Refused, match="did not land"):
        Fac(settle=pending).verify_and_settle({}, X.requirement(1, MINT, PAY_TO, FEE_PAYER), confirm=lost)
    with pytest.raises(X.Refused, match="did not settle"):
        Fac(settle=pending).verify_and_settle({}, X.requirement(1, MINT, PAY_TO, FEE_PAYER))


def server(tmp_path, fac=None):
    return x402.Server({}, None, MINT, None, state=tmp_path / "s.json",
                       exact={"asset": MINT, "pay_to": PAY_TO, "decimals": 6, "facilitator": fac or Fac()})


def test_checks_answers_402_with_an_exact_requirement_at_the_decided_price_and_the_bazaar_extension(tmp_path):
    st, h, body = server(tmp_path).handle("/checks", {})
    assert st == 402 and ra.decode(h["payment-required"]) == body
    (req,) = body["accepts"]
    each = fees_config.micro(fees_config.load().doc["fees"]["x402_check"]["usd_each"])
    assert req == X.requirement(each, MINT, PAY_TO, FEE_PAYER) and each == 20_000          # 0.02, config/fees.yaml fees.x402_check, decided 14 Oct 2026
    baz = body["extensions"]["bazaar"]
    assert baz["info"]["input"] == {"type": "http", "method": "GET"} and baz["schema"]["$schema"].endswith("2020-12/schema")
    assert "exact" in body["resource"]["description"]


def test_an_exact_payment_buys_one_check_once(tmp_path):
    fac = Fac()
    s = server(tmp_path, fac)
    req = s.exact_requirement()
    pay_ = X.payment(req, Keypair(), Hash.default(), decimals=6)
    st, h, body = s.handle("/checks", {"PAYMENT-SIGNATURE": ra.encode(pay_)})
    assert st == 200 and body["paid"] and body["scheme"] == "exact" and body["transaction"] == "SIG1"
    assert ra.decode(h["payment-response"])["status"] == "settled"
    assert json.loads((tmp_path / "s.json").read_text()) == {"exact:SIG1": 1}                 # kept before the answer
    assert s.handle("/checks", {"PAYMENT-SIGNATURE": ra.encode(pay_)})[0] == 409               # the same settlement twice
    again = server(tmp_path, Fac())                                                             # and after a restart
    assert again.handle("/checks", {"PAYMENT-SIGNATURE": ra.encode(pay_)})[0] == 409


def test_a_payment_for_another_requirement_or_one_the_facilitator_refuses_buys_nothing(tmp_path):
    s = server(tmp_path, Fac(valid=False))
    cheap = X.requirement(1, MINT, PAY_TO, FEE_PAYER)
    st, _, body = s.handle("/checks", {"PAYMENT-SIGNATURE": ra.encode(X.payment(cheap, Keypair(), Hash.default(), decimals=6))})
    assert st == 402 and body["accepts"] == [s.exact_requirement()]
    st, _, body = s.handle("/checks", {"PAYMENT-SIGNATURE": ra.encode(X.payment(s.exact_requirement(), Keypair(), Hash.default(), decimals=6))})
    assert st == 402 and "refused" in body["error"]
    assert not (tmp_path / "s.json").exists()
