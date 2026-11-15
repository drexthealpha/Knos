"""The round `passkey-payee`: a payee is paid to a passkey wallet before any account exists there, and one transaction
opens the wallet and withdraws, signed by the passkey. Own wallets only: the funder sends the smallest amount, and the
withdrawal goes back to the funder.

    python scripts/exercise_public.py run --only passkey-payee --rpc URL --keys DIR

The passkey is a P-256 key this round holds in software, derived from the relayer's key (nothing is stored): the
program checks the WebAuthn assertion's challenge, its "user present" flag and the P-256 signature through the
secp256r1 precompile, so a software key exercises the same instruction a platform authenticator does, and the
record says it was one. Nothing to simulate: the simulator's chain does not load knos_passkey (tests/test_passkey_chain.py
holds the same steps on its own simulator). `xp` is scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

ROUND = {"name": "passkey-payee", "needs": ("knos_passkey",), "caps": ("passkey_payee_wallet",), "phase": "any"}
PAID = 100_000                  # 0.10 test USDC
ORIGIN, RP_ID = "https://drexthealpha.github.io", "drexthealpha.github.io"
UP, UV = 0x01, 0x04


def _xp() -> Any:
    return globals()["xp"]


class SoftPasskey:
    """A P-256 key that answers navigator.credentials.get as an authenticator would, for ORIGIN."""

    def __init__(self, seed: bytes):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from knos.settle.v2 import passkey as pk
        self.sk = ec.derive_private_key(int.from_bytes(hashlib.sha256(seed).digest(), "big") % (pk.N - 1) + 1, ec.SECP256R1())
        pub = self.sk.public_key()
        self.point = pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.key = pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)

    def get(self, challenge: bytes, count: int) -> tuple[bytes, bytes, bytes]:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from knos.settle.v2 import passkey as pk
        auth = hashlib.sha256(RP_ID.encode()).digest() + bytes([UP | UV]) + count.to_bytes(4, "big")
        cdj = json.dumps({"type": "webauthn.get", "challenge": pk.b64url(challenge), "origin": ORIGIN, "crossOrigin": False}, separators=(",", ":")).encode()
        return auth, cdj, self.sk.sign(auth + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))


def run(book, st: dict) -> None:
    """A payee is paid to a passkey wallet that does not exist yet; one transaction opens it and withdraws, and only the
    passkey's signature moves the money."""
    from knos.advance import transfer_ix
    from knos.settle.v2 import passkey as pk
    x, w = _xp(), book.w
    if "withdrawn" in st:
        return
    key = SoftPasskey(b"knos exercise: passkey payee wallet" + bytes(w.relayer))
    wallet = pk.wallet(key.key)
    held = x.pay.ata(wallet, w.mint)
    if "paid" not in st:
        x._check(w.account(wallet) is None, f"the passkey wallet {wallet} is open already: a payment before it exists cannot be shown with it")
        sig = w.send([x.pay.create_ata_ix(w.funder.pubkey(), wallet, w.mint), transfer_ix(w.funder_token, w.mint, held, w.funder.pubkey(), PAID)],
                     w.funder, [w.funder])
        x._check(w.account(wallet) is None and w.tokens(held) >= PAID, "the payment did not reach the wallet's token account, or the wallet exists")
        st["paid"] = {"signature": sig, "wallet": str(wallet), "held": str(held), "amount": PAID}
        book.tx(st, f"{x.money(PAID)} test USDC is paid to the passkey wallet {wallet}, which has no account yet", sig, "spl-token")
    amount = w.tokens(held)
    before = pk.read_wallet(w.account(wallet))
    nonce = (before.nonce if before else 0) + 1
    to = w.funder_token
    auth, cdj, signature = key.get(pk.challenge(wallet, w.mint, to, amount, nonce), nonce)
    sig = w.send([pk.open_ix(w.relayer.pubkey(), key.key), *pk.withdraw_ixs(key.point, w.mint, to, amount, nonce, auth, cdj, signature)])
    after = pk.read_wallet(w.account(wallet))
    x._check(after is not None and after.key == key.key and after.nonce == nonce, "the wallet is not open under the passkey, or its nonce did not move")
    x._check(w.tokens(held) == 0, "the withdrawal left money in the wallet")
    st["withdrawn"] = {"signature": sig, "amount": amount, "nonce": nonce}
    book.tx(st, "one transaction opens the wallet and withdraws, signed by the passkey", sig, "knos_passkey")
    book.done(st, "passkey_payee_wallet", "knos_passkey", sig,
              [f"{x.money(PAID)} test USDC reached the wallet's address {wallet} before any account existed there",
               f"one transaction opened the wallet and withdrew {x.money(amount)}, verified by the secp256r1 precompile (withdrawal number {nonce})",
               "the passkey was a P-256 key the round held in software, not a platform authenticator"])
