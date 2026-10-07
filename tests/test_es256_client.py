"""The ES256 client (src/knos/settle/v2/oidc.py) against the built program in the simulator: a wallet registers a
P-256 key for an issuer, a token that key signed is verified in ONE transaction (the secp256r1 precompile, then
VerifyEs256), and what the program refuses is refused. The keys and signatures are tests/_es256.py's: fixed secrets and
RFC 6979 nonces, so every run writes the same bytes. The program's own tests are
programs-v2/handlers/tests/knos_oidc_es256.rs; this file holds the Python client to the same program."""
from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("solders.litesvm")

import _es256 as m  # noqa: E402
from _oidc2 import Chain2  # noqa: E402
from _settle import NOW  # noqa: E402

from knos.settle.v2 import oidc  # noqa: E402

URL = m.ISSUER
A, B = m.public(m.KEY_A), m.public(m.KEY_B)


def token(payload: dict | None = None, secret: int = m.KEY_A, high: bool = False, header: dict | None = None, raw: bytes | None = None) -> str:
    """A compact ES256 token of the issuer, signed with a test key; `high`: the upper s, as some libraries write it."""
    signing = raw if raw is not None else m.signing_input(header or {"alg": "ES256", "typ": "JWT", "kid": "a"},
                                                         payload or {"iss": URL, "sub": "spiffe://issuer.example/workload", "aud": "knos-test", "exp": NOW + 300, "iat": NOW})
    return f"{signing.decode()}.{m.b64url(m.sign(secret, signing, high=high)).decode()}"


def code(c: Chain2) -> int | None:
    import re
    hit = re.search(r"Custom\((\d+)\)", str(c.err))
    return int(hit.group(1)) if hit else None


@pytest.fixture()
def chain() -> Chain2:
    return Chain2()


def register(c: Chain2, wallet, key: bytes = A, url: str = URL) -> bool:
    return c.send([oidc.register_private_es256_key_ix(wallet.pubkey(), url, key)], wallet)


def verify(c: Chain2, wallet, jwt: str, key: bytes = A, payer=None) -> bool:
    payer = payer or wallet
    return c.send(oidc.verify_es256_ixs(payer.pubkey(), oidc.ec_key_pda(URL, key, registrant=wallet.pubkey()), jwt, key), payer)


def test_the_clients_bytes_are_the_models_and_the_programs_addresses():
    jwt = token()
    message, signature = oidc.es256_parts(jwt)
    assert message == jwt.rsplit(".", 1)[0].encode() and signature == m.sign(m.KEY_A, message) and m.low_s(signature)
    ix = oidc.secp256r1_ix(A, signature, message)
    assert ix.program_id == oidc.SECP256R1_ID and bytes(ix.data) == m.precompile_data(A, signature, message) and list(ix.accounts) == []
    # an issuer's library may write the upper s: the client sends the lower one, and the signing input is untouched
    high = token(high=True)
    assert not m.low_s(m.sign(m.KEY_A, message, high=True)) and oidc.es256_parts(high) == (message, signature)
    assert oidc.es256_token_id(high) == oidc.es256_token_id(jwt) == hashlib.sha256(message).digest()
    # a key: the JWK's coordinates, numbers, or the 33 bytes; what is not a point of the curve is refused
    x, y = m.decompress(A)
    assert oidc.ec_key(x, y) == oidc.ec_key(A) == oidc.ec_key(A.hex()) == A == oidc.ec_key(m.b64url(x.to_bytes(32, "big")).decode(), m.b64url(y.to_bytes(32, "big")).decode())
    def off_curve(n: int) -> bool:
        try:
            m.decompress(bytes([2]) + n.to_bytes(32, "big"))
        except ValueError:
            return True
        return False
    off = next(n for n in range(1, 50) if off_curve(n))                 # an x with no point of the curve above it
    for bad in ((x, y + 1), (b"\x04" + A[1:],), (A[:-1],), (bytes([2]) + off.to_bytes(32, "big"),)):
        with pytest.raises(ValueError):
            oidc.ec_key(*bad)
    assert oidc.EC_ACCOUNT == 137 and oidc.MAX_ES256_INPUT == m.MAX_SIGNING_INPUT == 780
    for bad in ("a.b", "a.b.c.d", f"{message.decode()}.{m.b64url(signature[:-1]).decode()}", f"{message.decode()}.{m.b64url(bytes(64)).decode()}"):
        with pytest.raises(ValueError):
            oidc.es256_parts(bad)
    with pytest.raises(ValueError, match="starts with https://"):
        oidc.register_private_es256_key_ix(oidc.SYSTEM, "http://issuer.example", A)


def test_a_wallet_registers_a_p256_key_and_a_token_it_signed_is_verified_in_one_transaction(chain):
    c, wallet = chain, chain.fund()
    at = oidc.ec_key_pda(URL, A, registrant=wallet.pubkey())
    assert oidc.read_ec_key(c.data(at)) is None and not oidc.ec_key_usable(None, c.now())[0]
    assert register(c, wallet), c.err
    key = oidc.read_ec_key(c.data(at))
    assert key is not None and (key.key, key.issuer, key.private, key.registrant, key.revoked) == (A, oidc.PRIVATE, True, wallet.pubkey(), False)
    assert key.issuer_hash == oidc.issuer_hash(URL) and (key.active_at, key.expires_at) == (c.now(), c.now() + oidc.KEY_TTL)
    assert oidc.ec_key_usable(key, c.now()) == (True, "") and oidc.read_key(c.data(at)) is None      # never read as an RSA key
    jwt = token()
    assert verify(c, wallet, jwt), c.err
    tok = oidc.read_token(c.data(oidc.token_pda(wallet.pubkey(), oidc.es256_token_id(jwt))))
    assert tok is not None and tok.verified and tok.issuer == oidc.PRIVATE and tok.key == at
    assert tok.claims() == json.loads(m.base64.urlsafe_b64decode(jwt.split(".")[1] + "=" * (-len(jwt.split(".")[1]) % 4)))
    assert oidc.token_issuer(c.data(oidc.token_pda(wallet.pubkey(), oidc.es256_token_id(jwt)))) == (oidc.issuer_hash(URL), wallet.pubkey())
    assert c.data(oidc.token_pda(wallet.pubkey(), oidc.es256_token_id(jwt)))[-86:] == jwt.rsplit(".", 1)[1].encode()     # the signature the precompile verified, as JWS writes it
    assert not verify(c, wallet, jwt)                                    # one payer verifies one token into one account, once
    # the upper s of the same signature: the client sends the lower one, so it is the same token and the same account
    other = token({"iss": URL, "exp": NOW + 300, "sub": "second"}, high=True)
    assert verify(c, wallet, other), c.err
    low = m.b64url(m.normalise(m.sign(m.KEY_A, other.rsplit(".", 1)[0].encode(), high=True)))
    assert c.data(oidc.token_pda(wallet.pubkey(), oidc.es256_token_id(other)))[-86:] == low != other.rsplit(".", 1)[1].encode()
    # the largest signing input one transaction carries, and one byte more
    largest = m.padded(oidc.MAX_ES256_INPUT)
    assert verify(c, wallet, token(raw=largest)), c.err
    with pytest.raises(ValueError, match="carries at most 780"):
        oidc.es256_parts(token(raw=m.padded(oidc.MAX_ES256_INPUT + 1)))


def test_what_the_program_refuses_of_an_es256_token(chain):
    c, wallet, stranger = chain, chain.fund(), chain.fund()
    assert register(c, wallet), c.err
    good = token()
    message, signature = oidc.es256_parts(good)
    key_at = oidc.ec_key_pda(URL, A, registrant=wallet.pubkey())
    pre, ver = oidc.verify_es256_ixs(wallet.pubkey(), key_at, good, A)
    # VerifyEs256 alone, or with anything but the precompile right before it: 80
    assert not c.send([ver], wallet) and code(c) == 80
    # a signature another key made: the precompile verifies it for that key, and the program holds the key account's: 82
    forged = token(secret=m.KEY_B)
    theirs = oidc.verify_es256_ixs(wallet.pubkey(), key_at, forged, B)
    assert not c.send(theirs, wallet) and code(c) == 82
    # a signature that is not this message's: the precompile fails and the transaction does not run
    wrong = oidc.verify_es256_ixs(wallet.pubkey(), key_at, good.rsplit(".", 1)[0] + "." + m.b64url(m.sign(m.KEY_A, b"another message")).decode(), A)
    assert not c.send(wrong, wallet) and "InstructionError((1," in str(c.err) and code(c) not in range(60, 84)      # the precompile's own refusal (instruction 1, after the compute budget's), not the program's
    # the upper s handed to the precompile as it is (not through the client): the precompile refuses it
    high = oidc.secp256r1_ix(A, m.sign(m.KEY_A, message, high=True), message)
    assert not c.send([high, ver], wallet)
    # a header that says RS256, an issuer that is not the key's, an expiry too far ahead, a member named twice
    for payload, header, want in (({"iss": URL, "exp": NOW + 300}, {"alg": "RS256", "typ": "JWT", "kid": "a"}, 71),
                                  ({"iss": "https://other.example", "exp": NOW + 300}, None, 72),
                                  ({"iss": URL, "exp": NOW + 86_401}, None, 63)):
        bad = token(payload, header=header)
        assert not verify(c, wallet, bad) and code(c) == want, (payload, header, c.err)
    twice = m.b64url(b'{"alg":"ES256","alg":"ES256"}') + b"." + message.split(b".")[1]
    cut = m.b64url(b'{"alg":"ES256"}') + b"." + m.b64url(b'{"iss":"https://issuer.example","exp":1790000300,"x":tru}')
    assert not verify(c, wallet, token(raw=cut)) and code(c) == 61                      # strict JSON: every byte of the payload is JSON, or nothing is verified
    assert not verify(c, wallet, token(raw=twice)) and code(c) == 62                    # strict JSON: a member named twice
    # another wallet has no such key: its own registration is its own account, and a payer may verify with a key someone else registered
    assert oidc.ec_key_pda(URL, A, registrant=stranger.pubkey()) != key_at
    assert verify(c, wallet, good, payer=stranger), c.err
    assert oidc.token_issuer(c.data(oidc.token_pda(stranger.pubkey(), oidc.es256_token_id(good)))) == (oidc.issuer_hash(URL), wallet.pubkey())
    # the wallet ends its key; a stranger cannot; a revoked key verifies nothing and is never renewed
    assert not c.send([oidc.revoke_es256_ix(stranger.pubkey(), URL, A, registrant=wallet.pubkey())], stranger) and code(c) == 79
    assert c.send([oidc.revoke_es256_ix(wallet.pubkey(), URL, A, registrant=wallet.pubkey())], wallet), c.err
    key = oidc.read_ec_key(c.data(key_at))
    assert key.revoked and oidc.ec_key_usable(key, c.now()) == (False, "this P-256 key was revoked. It cannot be used again.")
    assert not verify(c, wallet, token({"iss": URL, "exp": NOW + 300, "sub": "after"})) and not register(c, wallet)
    # a key past its time
    assert register(c, wallet, B), c.err
    c.warp(oidc.KEY_TTL)
    late = oidc.read_ec_key(c.data(oidc.ec_key_pda(URL, B, registrant=wallet.pubkey())))
    assert not oidc.ec_key_usable(late, c.now())[0] and "expired" in oidc.ec_key_usable(late, c.now())[1]
    assert not verify(c, wallet, token({"iss": URL, "exp": c.now() + 300}, secret=m.KEY_B), key=B)
    assert register(c, wallet, B), c.err                                 # sent again by the same wallet, it lives KEY_TTL from now
    assert verify(c, wallet, token({"iss": URL, "exp": c.now() + 300}, secret=m.KEY_B), key=B), c.err
