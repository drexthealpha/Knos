"""Durable nonces (knos.platform.nonce) and the measured blockhash window (knos.platform.blockhash). No network: the
ledger and the RPC are stand-ins; every key is made in the test (synthetic)."""
from __future__ import annotations

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV1
from solders.pubkey import Pubkey

from knos.platform import blockhash, nonce

MEMO = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")


def nonce_bytes(authority: Pubkey, value: Hash, version: int = 1, state: int = 1) -> bytes:
    return version.to_bytes(4, "little") + state.to_bytes(4, "little") + bytes(authority) + bytes(value) + (5000).to_bytes(8, "little")


def memo(signer: Pubkey) -> Instruction:
    return Instruction(MEMO, b"fund (synthetic)", [AccountMeta(signer, True, False)])


def test_a_nonce_account_is_read_and_anything_else_is_not():
    a, v = Keypair().pubkey(), Hash.new_unique()
    got = nonce.read(nonce_bytes(a, v))
    assert got.authority == a and got.value == v and got.lamports_per_signature == 5000
    assert nonce.read(nonce_bytes(a, v, state=0)) is None and nonce.read(b"\x00" * 79) is None and nonce.read(None) is None


def test_the_message_advances_the_nonce_first_and_names_its_value_as_the_blockhash():
    payer, funder, nk = Keypair(), Keypair(), Keypair()
    value = Hash.new_unique()
    m = nonce.message([memo(funder.pubkey())], payer.pubkey(), nk.pubkey(), funder.pubkey(), value)
    assert isinstance(m, MessageV1) and m.recent_blockhash == value
    first = m.instructions[0]
    assert m.account_keys[first.program_id_index] == nonce.SYSTEM and bytes(first.data)[:4] == (4).to_bytes(4, "little")
    legacy = nonce.message([memo(funder.pubkey())], payer.pubkey(), nk.pubkey(), funder.pubkey(), value, v1=False)
    assert legacy.recent_blockhash == value


def test_two_parties_sign_the_same_bytes_at_different_times():
    payer, funder, nk = Keypair(), Keypair(), Keypair()
    m = nonce.message([memo(funder.pubkey())], payer.pubkey(), nk.pubkey(), funder.pubkey(), Hash.new_unique())
    part = nonce.sign_part(m, [funder])
    assert nonce.missing(part) == [payer.pubkey()]
    moved = nonce.decode(nonce.encode(part))                 # the file passed between machines
    full = nonce.add(moved, payer)
    assert nonce.missing(full) == [] and full.uses_durable_nonce()
    with pytest.raises(ValueError, match="not a signer"):
        nonce.add(full, Keypair())
    with pytest.raises(ValueError, match="not a signer"):
        nonce.sign_part(m, [Keypair()])


class Ledger:
    url, commitment = "http://stand-in", "confirmed"

    def __init__(self, data=None):
        self.sent, self.data = [], data

    def _submit(self, tx):
        self.sent.append(tx)
        return "sig"

    def account(self, _k):
        return self.data


def test_send_refuses_a_transaction_that_is_unsigned_or_has_no_nonce(monkeypatch):
    payer, funder, nk = Keypair(), Keypair(), Keypair()
    value = Hash.new_unique()
    m = nonce.message([memo(funder.pubkey())], payer.pubkey(), nk.pubkey(), funder.pubkey(), value)
    with pytest.raises(ValueError, match="unsigned"):
        nonce.send(Ledger(), nonce.sign_part(m, [funder]))
    from knos import chain
    monkeypatch.setattr(chain, "wait", lambda *a, **k: {})
    led = Ledger(nonce_bytes(funder.pubkey(), value))
    full = nonce.sign_part(m, [payer, funder])
    assert nonce.still_good(led, full) and nonce.send(led, full) == "sig" and led.sent
    led.data = nonce_bytes(funder.pubkey(), Hash.new_unique())  # the nonce moved on: these bytes can never land again
    assert not nonce.still_good(led, full)
    from solders.message import TransactionConfig
    from solders.transaction import VersionedTransaction
    plain = MessageV1.try_compile(payer.pubkey(), [memo(funder.pubkey())], value,
                                  TransactionConfig(compute_unit_limit=200_000, loaded_accounts_data_size_limit=1 << 20, priority_fee=None))
    with pytest.raises(ValueError, match="does not advance a nonce"):
        nonce.send(Ledger(), VersionedTransaction(plain, [payer, funder]))


def test_the_window_is_measured_not_assumed():
    heights = iter([1000, 1043, 1086, 1129])
    t = iter([0.0, 10.0, 20.0, 30.0])

    def call(method, _params):
        if method == "getLatestBlockhash":
            return {"value": {"lastValidBlockHeight": 1000 + 150}}   # issued with the first height and stays fixed
        return next(heights)
    got = blockhash.life(call, samples=4, gap_s=0, sleep=lambda _s: None, clock=lambda: next(t))
    assert round(got.blocks_per_s, 2) == 4.3 and got.samples == 4 and got.seconds < 60
    assert blockhash.expired(lambda m, p: 1151, 1150) and not blockhash.expired(lambda m, p: 1150, 1150)
    with pytest.raises(ValueError):
        blockhash.life(call, samples=1)


def test_the_measured_devnet_figure_is_the_one_recorded():
    assert 25 < blockhash.MEASURED_DEVNET_S < 40 and blockhash.MAX_AGE_BLOCKS == 150
