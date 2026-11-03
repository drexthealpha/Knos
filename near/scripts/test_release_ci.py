"""release_ci.py's signer: RFC 8032's first test vector, agreement with `cryptography` on random keys, and a
transaction whose bytes and signature match what a NEAR key would sign.

    python near/scripts/test_release_ci.py
"""
from __future__ import annotations

import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_ci as rc  # noqa: E402


def test_rfc8032_vector_1() -> None:
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert rc.public_key(seed).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert rc.sign(seed, b"").hex() == ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                                        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")


def test_agrees_with_cryptography() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    for i in range(5):
        seed = hashlib.sha256(b"knos %d" % i).digest()
        k = Ed25519PrivateKey.from_private_bytes(seed)
        msg = os.urandom(32 + i)
        assert rc.public_key(seed) == k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        assert rc.sign(seed, msg) == k.sign(msg)


def test_transaction_bytes() -> None:
    seed = hashlib.sha256(b"tx").digest()
    pub = rc.public_key(seed)
    tx = rc.transaction("a.testnet", pub, 7, "c.testnet", b"\x01" * 32, "release", {"id": "m"})
    want = (struct.pack("<I", 9) + b"a.testnet" + b"\x00" + pub + struct.pack("<Q", 7) + struct.pack("<I", 9) + b"c.testnet"
            + b"\x01" * 32 + struct.pack("<I", 1) + b"\x02" + struct.pack("<I", 7) + b"release" + struct.pack("<I", 10)
            + b'{"id":"m"}' + struct.pack("<Q", rc.GAS) + b"\x00" * 16)
    assert tx == want
    st = rc.signed(tx, seed)
    assert st[:len(tx)] == tx and st[len(tx)] == 0 and st[len(tx) + 1:] == rc.sign(seed, hashlib.sha256(tx).digest())
    assert rc.b58d(rc.b58e(b"\x00\x00" + pub)) == b"\x00\x00" + pub


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)
