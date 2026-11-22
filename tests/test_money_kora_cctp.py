"""Kora (fee relayer) client and CCTP V2 design (knos.money.kora, knos.money.cctp). The Kora node and Circle's attestation service
are stand-ins whose answers are shaped from their published docs: synthetic fixtures, no network."""
from __future__ import annotations

import base64
import json

import pytest
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from knos.money import cctp, kora

MEMO = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
PAY = Pubkey.from_string("5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k")


def fake_node(signer: Keypair, allowed=(str(MEMO),), sign_on=True):
    """A synthetic Kora node: getConfig/getPayerSigner/getBlockhash/signAndSendTransaction, as the OpenAPI shapes them."""
    seen = []

    def post(_url, body, _headers):
        req = json.loads(body)
        seen.append(req)
        m = req["method"]
        if m == "getConfig":
            res = {"fee_payers": [str(signer.pubkey())], "validation_config": {"allowed_programs": list(allowed), "allowed_spl_paid_tokens": []},
                   "enabled_methods": {"sign_transaction": sign_on, "sign_and_send_transaction": sign_on}}
        elif m == "getPayerSigner":
            res = {"signer_address": str(signer.pubkey()), "payment_address": str(signer.pubkey())}
        elif m == "getBlockhash":
            res = {"blockhash": "11111111111111111111111111111111"}
        elif m == "signAndSendTransaction":
            tx = VersionedTransaction.from_bytes(base64.b64decode(req["params"]["transaction"]))
            ok = tx.verify_with_results()
            res = {"signature": "synthetic-signature", "signed_transaction": req["params"]["transaction"], "signer_pubkey": str(signer.pubkey()),
                   "_user_signed": ok[1:], "_fee_slot_blank": not ok[0]}
        else:
            return json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}).encode()
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": res}).encode()
    return post, seen


def test_a_researcher_with_no_sol_sends_through_kora_and_kora_is_the_fee_payer():
    node_key, user = Keypair(), Keypair()
    post, seen = fake_node(node_key)
    k = kora.Kora("http://kora.invalid")
    k.post = post
    ix = Instruction(MEMO, b"fund (synthetic)", [AccountMeta(user.pubkey(), True, False)])
    got = kora.send_gasless(k, [ix], [user], [MEMO])
    assert got["fee_payer"] == str(node_key.pubkey())
    sent = next(r for r in seen if r["method"] == "signAndSendTransaction")
    tx = VersionedTransaction.from_bytes(base64.b64decode(sent["params"]["transaction"]))
    assert tx.message.account_keys[0] == node_key.pubkey()                   # Kora pays the fee
    assert tx.verify_with_results() == [False, True]                          # the user signed; Kora's slot was left for Kora
    legacy = kora.message([ix], node_key.pubkey(), tx.message.recent_blockhash, v1=False)
    assert VersionedTransaction.from_bytes(base64.b64decode(kora.user_signed(legacy, [user]))).verify_with_results() == [False, True]


def test_the_nodes_policy_is_read_before_anyone_signs(monkeypatch):
    monkeypatch.delenv("KORA_RPC_URL", raising=False)
    post, seen = fake_node(Keypair(), allowed=("SomeOtherProgram1111111111111111111111111111",))
    k = kora.Kora("http://kora.invalid")
    k.post = post
    with pytest.raises(kora.KoraError, match="does not allow program"):
        kora.send_gasless(k, [], [Keypair()], [PAY])
    assert not any(r["method"].startswith("sign") for r in seen)
    assert kora.policy_problems({"enabled_methods": {}}, []) == ["the node has signing turned off"]
    with pytest.raises(kora.KoraError, match="KORA_RPC_URL"):
        kora.Kora.from_env()


def burn_message(recipient: Pubkey, amount: int, fee: int, hook: bytes, dest: int = 5) -> str:
    head = (1).to_bytes(4, "big") + (6).to_bytes(4, "big") + dest.to_bytes(4, "big") + bytes(32) * 4 + (2000).to_bytes(4, "big") + (2000).to_bytes(4, "big")
    body = ((1).to_bytes(4, "big") + bytes(32) + bytes(recipient) + amount.to_bytes(32, "big") + bytes(32) + fee.to_bytes(32, "big")
            + fee.to_bytes(32, "big") + (0).to_bytes(32, "big") + hook)
    return "0x" + (head + body).hex()


def test_a_cctp_burn_is_taken_as_an_orders_money_only_when_it_names_the_order():
    tok = Keypair().pubkey()
    scope, terms = b"\x01" * 32, b"\x02" * 32
    p = cctp.plan(tok, scope, terms, 5_000_000, max_fee=1_000)
    assert p.destination_domain == 5 and p.mint_recipient == "0x" + bytes(tok).hex() and p.amount == 5_001_000
    good = cctp.decode(burn_message(tok, 5_001_000, 1_000, cctp.hook_data(scope, terms)))
    assert good.source_domain == 6 and good.min_finality == cctp.STANDARD and cctp.check(good, p) == []
    assert cctp.check(cctp.decode(burn_message(Keypair().pubkey(), 5_001_000, 1_000, cctp.hook_data(scope, terms))), p)
    assert cctp.check(cctp.decode(burn_message(tok, 4_000_000, 1_000, cctp.hook_data(scope, terms))), p)
    assert cctp.check(cctp.decode(burn_message(tok, 5_001_000, 1_000, cctp.hook_data(b"\x09" * 32, terms))), p)
    assert cctp.check(cctp.decode(burn_message(tok, 5_001_000, 1_000, cctp.hook_data(scope, terms), dest=6)), p)


def test_attestation_answers_are_read_and_a_missing_message_is_none():
    assert cctp.attestation(6, "0xabc", fetch=lambda u: (404, b'{"error":"Message not found for provided parameters"}')) is None
    body = json.dumps({"messages": [{"message": "0x00", "attestation": "PENDING", "status": "pending_confirmations"}]}).encode()
    got = cctp.attestation(6, "0xabc", fetch=lambda u: (200, body))
    assert got["status"] == "pending_confirmations" and not cctp.ready(got)
    assert cctp.ready({"status": "complete", "attestation": "0xsig"})
    with pytest.raises(RuntimeError):
        cctp.attestation(6, "0xabc", fetch=lambda u: (500, b""))
