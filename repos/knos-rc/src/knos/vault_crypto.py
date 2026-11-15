"""The three primitives the vault is made of, from the standard library alone.

    X25519                RFC 7748, section 5 (the Montgomery ladder on curve25519)
    HKDF-SHA256           RFC 5869
    ChaCha20-Poly1305     RFC 8439, section 2.8 (the AEAD construction)

Knos has no runtime dependency for cryptography (`cryptography` is installed only with the `dev` extra, for the tests),
so each primitive is written out here and checked against its RFC's test vectors in tests/test_vault.py. When the
`cryptography` package can be imported it is used instead, and the same test holds the two to the same bytes.

A limit, said plainly: the code below is not constant-time. Python's integers are not, and nothing written in Python
can be. Sealing and opening are done by a person at a command line on a machine they control, not by a server that
answers strangers, so there is no remote timing to measure; on a shared machine install `cryptography`
(`pip install cryptography`) and the constant-time implementation is used with no other change.
"""
from __future__ import annotations

import hashlib
import hmac
import struct

P = 2**255 - 19
BASE = (9).to_bytes(32, "little")
_MASK = 0xFFFFFFFF


def _native():
    """The `cryptography` package's two classes, or None when it is not installed."""
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    except Exception:  # noqa: BLE001 - not installed, or built without the backend: the code below is the same function
        return None
    return X25519PrivateKey, X25519PublicKey, ChaCha20Poly1305


# ---- X25519 --------------------------------------------------------------------------------------------------------------
def _ladder(k: bytes, u: bytes) -> bytes:
    scalar = int.from_bytes(k, "little")
    scalar = (scalar & ~7 & ~(128 << 248)) | (64 << 248)
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in range(254, -1, -1):
        bit = (scalar >> t) & 1
        if swap ^ bit:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a, b = (x2 + z2) % P, (x2 - z2) % P
        aa, bb = a * a % P, b * b % P
        e = (aa - bb) % P
        da, cb = (x3 - z3) * a % P, (x3 + z3) * b % P
        x3, z3 = (da + cb) ** 2 % P, x1 * (da - cb) ** 2 % P
        x2, z2 = aa * bb % P, e * (aa + 121665 * e) % P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, P - 2, P) % P).to_bytes(32, "little")


def x25519(private: bytes, public: bytes, pure: bool = False) -> bytes:
    """The shared secret of a 32-byte private key and a 32-byte public key. Raises ValueError for a public key that
    gives the all-zero secret (a point of small order: whoever sent it would know the secret without any key)."""
    if len(private) != 32 or len(public) != 32:
        raise ValueError("an X25519 key is 32 bytes")
    native = None if pure else _native()
    if native is not None:
        try:
            out = native[0].from_private_bytes(private).exchange(native[1].from_public_bytes(public))
        except ValueError:
            out = bytes(32)
    else:
        out = _ladder(private, public)
    if out == bytes(32):
        raise ValueError("that public key is a point of small order: no secret can be shared with it")
    return out


def public_of(private: bytes, pure: bool = False) -> bytes:
    return x25519(private, BASE, pure)


# ---- HKDF-SHA256 ---------------------------------------------------------------------------------------------------------
def hkdf(secret: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    prk = hmac.new(salt or bytes(32), secret, hashlib.sha256).digest()
    out, block = b"", b""
    for i in range(1, -(-length // 32) + 1):
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
    return out[:length]


# ---- ChaCha20-Poly1305 ---------------------------------------------------------------------------------------------------
def _block(key_words: tuple, counter: int, nonce_words: tuple) -> bytes:
    s = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574, *key_words, counter & _MASK, *nonce_words]
    x = list(s)
    for _ in range(10):
        for a, b, c, d in ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14), (3, 7, 11, 15), (0, 5, 10, 15), (1, 6, 11, 12), (2, 7, 8, 13), (3, 4, 9, 14)):
            xa, xb, xc, xd = x[a], x[b], x[c], x[d]
            xa = (xa + xb) & _MASK
            xd ^= xa
            xd = ((xd << 16) | (xd >> 16)) & _MASK
            xc = (xc + xd) & _MASK
            xb ^= xc
            xb = ((xb << 12) | (xb >> 20)) & _MASK
            xa = (xa + xb) & _MASK
            xd ^= xa
            xd = ((xd << 8) | (xd >> 24)) & _MASK
            xc = (xc + xd) & _MASK
            xb ^= xc
            xb = ((xb << 7) | (xb >> 25)) & _MASK
            x[a], x[b], x[c], x[d] = xa, xb, xc, xd
    return struct.pack("<16I", *((x[i] + s[i]) & _MASK for i in range(16)))


def chacha20(key: bytes, counter: int, nonce: bytes, data: bytes) -> bytes:
    kw, nw = struct.unpack("<8I", key), struct.unpack("<3I", nonce)
    stream = b"".join(_block(kw, counter + i, nw) for i in range(-(-len(data) // 64)))
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream[:len(data)], "little")).to_bytes(len(data), "little")


def poly1305(key: bytes, message: bytes) -> bytes:
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s, acc, p = int.from_bytes(key[16:32], "little"), 0, (1 << 130) - 5
    for i in range(0, len(message), 16):
        acc = (acc + int.from_bytes(message[i:i + 16] + b"\x01", "little")) * r % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _tag(key: bytes, nonce: bytes, aad: bytes, sealed: bytes) -> bytes:
    pad = lambda b: bytes(-len(b) % 16)  # noqa: E731
    one_time = _block(struct.unpack("<8I", key), 0, struct.unpack("<3I", nonce))[:32]
    return poly1305(one_time, aad + pad(aad) + sealed + pad(sealed) + struct.pack("<QQ", len(aad), len(sealed)))


def aead_seal(key: bytes, nonce: bytes, plain: bytes, aad: bytes, pure: bool = False) -> bytes:
    """The ciphertext with its 16-byte tag at the end."""
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("ChaCha20-Poly1305 takes a 32-byte key and a 12-byte nonce")
    native = None if pure else _native()
    if native is not None:
        return native[2](key).encrypt(nonce, plain, aad)
    sealed = chacha20(key, 1, nonce, plain)
    return sealed + _tag(key, nonce, aad, sealed)


def aead_open(key: bytes, nonce: bytes, sealed: bytes, aad: bytes, pure: bool = False) -> bytes:
    """The plaintext. Raises ValueError when the tag does not hold: a wrong key, or one changed byte anywhere."""
    if len(key) != 32 or len(nonce) != 12 or len(sealed) < 16:
        raise ValueError("ChaCha20-Poly1305 takes a 32-byte key, a 12-byte nonce and at least the 16-byte tag")
    native = None if pure else _native()
    if native is not None:
        try:
            return native[2](key).decrypt(nonce, sealed, aad)
        except Exception:  # noqa: BLE001 - InvalidTag: one sentence either way
            raise ValueError("the authentication tag does not match: the sealed data was changed, or the key is wrong") from None
    body, tag = sealed[:-16], sealed[-16:]
    if not hmac.compare_digest(tag, _tag(key, nonce, aad, body)):
        raise ValueError("the authentication tag does not match: the sealed data was changed, or the key is wrong")
    return chacha20(key, 1, nonce, body)
