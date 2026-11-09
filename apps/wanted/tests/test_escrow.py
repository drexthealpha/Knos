"""The pre-order vault is built by Knos's own graduation code. Needs the optional `knos` package; no network."""
import base64
import json

import pytest

from knos_wanted import escrow

knos_mod = pytest.importorskip("knos.graduation")
from knos.settle.v2 import pay  # noqa: E402
from solders.hash import Hash  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.message import Message  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.system_program import TransferParams, transfer  # noqa: E402
from solders.transaction import Transaction  # noqa: E402

H = "ab" * 32


def test_plan_is_a_graduation_pool_for_the_report():
    g = knos_mod
    p = escrow.plan(H)
    cid = escrow.claim_id(H)
    assert p["claim_id"] == cid and p["spec_hash"] == H
    assert p["pool"]["scope"] == g.scope(cid, p["repo_id"], g.POOL_ISSUE).hex()
    assert p["options"] == g.options(p["repo_id"]).hex()
    terms = json.loads(p["pool"]["terms"])
    assert terms["kind"] == "preorder" and terms["spec_hash"] == H and terms["claim"] == cid
    assert p["pool"]["terms_hash"] == pay.terms_hash(p["pool"]["terms"].encode()).hex()
    assert pay.MIN_WORK <= p["pool"]["work_s"] <= pay.MAX_WORK


def test_preorder_ix_is_knos_fund_order_wallet():
    p = escrow.plan(H)
    buyer, mint = Keypair().pubkey(), Keypair().pubkey()
    ix = knos_mod.preorder_ix(p, buyer, pay.ata(buyer, mint), mint, 5_000_000)
    assert ix.program_id == pay.PAY_ID and ix.data[0] == 0x0F
    assert ix.accounts[0].pubkey == buyer and ix.accounts[0].is_signer
    assert ix.accounts[1].pubkey == knos_mod.address(p, "pool", buyer)


def test_bad_hash_and_amount_refused():
    with pytest.raises(ValueError):
        escrow.plan("not-a-hash")
    with pytest.raises(ValueError):
        escrow._amount(1)
    with pytest.raises(ValueError):
        escrow._amount(10_000)
    assert escrow._amount(5) == 5_000_000


def test_submit_relays_only_knos_preorders(monkeypatch):
    k = Keypair()
    msg = Message.new_with_blockhash([transfer(TransferParams(from_pubkey=k.pubkey(), to_pubkey=Keypair().pubkey(), lamports=1))],
                                     k.pubkey(), Hash.default())
    tx = Transaction([k], msg, Hash.default())
    raw = base64.b64encode(bytes(tx)).decode()
    with pytest.raises(ValueError, match="only a knos_pay pre-order"):
        escrow.submit(raw, str(k.pubkey()))
    with pytest.raises(ValueError, match="fee payer"):
        escrow.submit(raw, str(Keypair().pubkey()))


def test_demo_needs_a_test_wallet():
    with pytest.raises(escrow.EscrowUnavailable):
        escrow.demo_key()


def test_keypair_from_env_text(monkeypatch):
    k = Keypair()
    monkeypatch.setenv("KNOS_WANTED_DEVNET_KEYPAIR", json.dumps(list(bytes(k))))
    assert escrow.demo_key().pubkey() == k.pubkey()
    assert isinstance(Pubkey.from_string(str(k.pubkey())), Pubkey)
