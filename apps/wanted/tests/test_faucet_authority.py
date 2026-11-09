"""The faucet mints with the TEST MINT'S AUTHORITY (`escrow`.demo_key, which made the mint), not the relayer: on the live
server the two are different keys, and a MintTo signed by the relayer fails ("owner does not match", token error 0x4)."""
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from knos_wanted import escrow, wallets


def test_the_faucet_is_signed_by_the_mint_authority_even_when_the_relayer_is_another_key(monkeypatch):
    authority, relayer = Keypair(), Keypair()
    monkeypatch.setattr(escrow, "demo_key", lambda: authority)
    monkeypatch.setattr(wallets, "relayer", lambda: relayer)
    tok, mint = Keypair().pubkey(), Keypair().pubkey()
    monkeypatch.setattr(wallets, "ensure", lambda led, h, rp: {"mint": mint, "token_account": tok, "vault": Pubkey.default()})
    sent = []

    class Led:
        def send(self, ixs, payer, extra=None):
            sent.append((ixs, payer))
            return "5" * 88
    got = wallets.faucet(Led(), {"sub": "pk:x"}, "knos.example")
    (ixs, payer), = sent
    assert payer is authority and ixs[0].accounts[2].pubkey == authority.pubkey() and ixs[0].accounts[2].is_signer
    assert got["units"] == wallets.FAUCET_UNITS
