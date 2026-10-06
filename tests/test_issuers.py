"""examples/issuers: the verifier is not a GitHub feature. For every issuer the table calls supported, a token with
that issuer's exact claim SHAPE (examples/issuers/issuers.json: the names and types its documentation gives, with
example values) is verified in the test build of knos-oidc (LiteSVM), under a key registered for that issuer's URL.

Every token here is signed by a TEST key derived from a fixed seed. No issuer's own key is used and none of these
tokens came from an issuer: what is shown is that the program verifies an RS256 token of that shape under a key
registered for that URL, and reads the claims the table says a program can gate on. That the issuer's real keys have
the sizes the table gives was read from their published key sets on the day the file names.

Refused: a key used for another issuer's URL, an RS256 key of a size the program does not take, and ES256, ES384
and PS256 tokens."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa  # noqa: E402
from solders.instruction import Instruction  # noqa: E402

from _oidc2 import GH, GL, Chain2  # noqa: E402
from _settle import SeedKey, b64, modulus, sign_jwt, signing_key  # noqa: E402

from knos.settle.v2 import oidc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BOOK = json.loads((ROOT / "examples" / "issuers" / "issuers.json").read_text(encoding="utf-8"))
ISSUERS = {i["id"]: i for i in BOOK["issuers"]}
BY_URL = [i for i in BOOK["issuers"] if i["path"] == "url"]
NUMBERED = {"github": GH, "gitlab": GL}
_KEYS: dict[int, SeedKey] = {}


def example_key(bits: int = 2048) -> SeedKey:
    """The one key that stands in for every issuer's: derived from a fixed seed, and nobody's real key."""
    if bits not in _KEYS:
        _KEYS[bits] = SeedKey(bits, seed=f"knos issuers example key {bits}")
    return _KEYS[bits]


def code(c: Chain2) -> int | None:
    m = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(m.group(1)) if m else None


def shaped(issuer: dict, c: Chain2, **over) -> dict:
    """The issuer's recorded claims with the times a token issued now would carry."""
    claims = dict(issuer["claims"], iat=c.now(), exp=c.now() + 300)
    claims.update(over)
    return claims


def gateable(value) -> bool:
    """What the interface crate's `claim` and `claim_u64` read: a top-level string, or a non-negative whole number."""
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


@pytest.fixture(scope="module")
def chain() -> Chain2:
    """One chain that holds a key for every issuer in the table: GitHub's as a genesis key of the test build, and
    every other on GitHub's signature, after the day's wait and the guardian's approval (the path a real key takes)."""
    c = Chain2()
    n = modulus(example_key())
    assert c.register(GH, modulus(signing_key())), c.err
    for issuer in [GL, *(i["iss"] for i in BY_URL)]:
        assert c.register(issuer, n, c.attest(issuer, n)) and c.approve(issuer, n), (issuer, c.err)
    c.travel(oidc.KEY_DELAY)
    return c


# -- the table itself --------------------------------------------------------------------------------------------------

def test_the_table_says_what_the_program_takes():
    lib = (ROOT / "programs-v2" / "knos_oidc" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "(l != 64 && l != 128)" in lib and "rest.len() != ul + 256 && rest.len() != ul + 512" in lib      # 2048 or 4096 bits, nothing else
    assert 'text(alg)? != b"RS256"' in lib and "pub const MAX_JWT: usize = 8192;" in lib and "pub const MAX_ISS: usize = 200;" in lib
    assert BOOK["accepts"] == {"alg": "RS256", "key_bits": [2048, 4096], "max_token_bytes": 8192, "max_issuer_url_bytes": 200,
                               "exp": BOOK["accepts"]["exp"]}
    assert len(ISSUERS) == len(BOOK["issuers"]) == 11
    for i in BOOK["issuers"]:
        assert i["supported"] in ("yes", "partly") and i["source"].startswith("https://") and i["get"] and i["why"], i["id"]
        assert i["iss"].startswith("https://") and len(i["iss"]) <= 200 and i["claims"]["iss"] == i["iss"], i["id"]
        assert all(bits in (2048, 4096) for bits in i["key_bits"]), i["id"]
        if i["supported"] == "yes":
            assert i["key_bits"], i["id"]                       # a "yes" has a measured key size behind it
        # what the table calls gateable is a string or a whole number at the top level, and what it calls unreadable is not
        assert i["gate"] and all(gateable(i["claims"][name]) for name in i["gate"]), i["id"]
        assert all(not gateable(i["claims"][name]) for name in i["unreadable"]), i["id"]
        assert {name for name, v in i["claims"].items() if not gateable(v)} == set(i["unreadable"]), i["id"]


def test_the_page_the_document_and_the_examples_name_the_same_issuers():
    doc = (ROOT / "docs" / "VERIFIER.md").read_text(encoding="utf-8")
    page = (ROOT / "web" / "verifier.js").read_text(encoding="utf-8")
    assert BOOK["checked"] in doc and BOOK["checked"] in page
    assert oidc.IDS["knos_oidc"] in doc and oidc.IDS["knos_oidc"] in page
    for i in BOOK["issuers"]:
        readme = (ROOT / "examples" / "issuers" / i["id"] / "README.md").read_text(encoding="utf-8")
        assert i["name"] in doc and i["name"] in page and i["source"] in doc and i["source"] in page, i["id"]
        assert i["get"] in readme and i["source"] in readme and "test key" in readme, i["id"]
        for name in i["gate"]:
            assert f"`{name}`" in doc and f"`{name}`" in readme and name in page, (i["id"], name)
    # nobody outside this repository reads the verifier yet, and both say so
    assert "no program outside this repository" in doc.lower() and "No outside program reads it yet" in page


# -- one test per issuer -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(ISSUERS))
def test_a_token_of_this_issuers_shape_verifies_under_a_key_registered_for_its_url(chain, name):
    c, i, key = chain, ISSUERS[name], example_key()
    n = modulus(key)
    issuer = NUMBERED.get(name, i["iss"])
    if name == "github":
        key, n = signing_key(), modulus(signing_key())
    claims = shaped(i, c)
    tok = c.verify(sign_jwt(key, claims), issuer, n)
    assert tok is not None, f"{name}: {c.err}"
    t = oidc.read_token(c.data(tok))
    assert t.verified and t.claims() == claims and t.key == oidc.key_pda(issuer, n)
    if name in NUMBERED:
        assert t.issuer == NUMBERED[name] and oidc.token_issuer(c.data(tok)) is None
    else:
        # the token account says which issuer by the hash of its URL: what a consumer compares
        assert t.issuer == oidc.OTHER and oidc.token_issuer(c.data(tok)) == (hashlib.sha256(i["iss"].encode()).digest(), None)
        assert oidc.read_iss(c.data(oidc.iss_pda(i["iss"]))) == i["iss"]
    # a token that says it is from this issuer is not taken under any other issuer's key, although the key is the same
    for other in BY_URL:
        if other["id"] != name:
            assert c.verify(sign_jwt(example_key(), shaped(i, c, jti=f"under-{other['id']}")), other["iss"], modulus(example_key())) is None and code(c) == 72, other["id"]


# -- what is refused ---------------------------------------------------------------------------------------------------

def test_a_key_is_good_for_the_url_it_was_registered_for_and_no_other(chain):
    c, key = chain, example_key()
    google, entra = ISSUERS["google"], ISSUERS["entra"]
    for said in (entra["iss"], google["iss"] + "/", google["iss"].replace("accounts", "accounts2"), "https://token.actions.githubusercontent.com", ""):
        assert c.verify(sign_jwt(key, shaped(google, c, iss=said)), google["iss"], modulus(key)) is None and code(c) == 72, said
    # Auth0's issuer ends in a slash and that slash is part of it
    auth0 = ISSUERS["auth0"]
    assert auth0["iss"].endswith("/")
    assert c.verify(sign_jwt(key, shaped(auth0, c, iss=auth0["iss"][:-1])), auth0["iss"], modulus(key)) is None and code(c) == 72
    # and a key nobody registered for a URL has no account there
    assert c.key("https://accounts.google.example", modulus(key)) is None


@pytest.mark.parametrize("bits", [1024, 3072])
def test_an_rs256_key_of_another_size_cannot_be_registered_or_used(chain, bits):
    c, url = chain, ISSUERS["google"]["iss"]
    odd = SeedKey(bits, seed=f"knos issuers example key {bits}")
    assert odd.n.bit_length() == bits
    good = c.register_ix(url, modulus(signing_key(4096)), c.attest(url, modulus(signing_key(4096))))
    u = url.encode()
    data = b"\x08" + bytes([len(u)]) + u + odd.n.to_bytes(bits // 8, "big")
    assert not c.send([Instruction(oidc.OIDC_ID, data, good.accounts)]) and "InvalidInstructionData" in c.err
    private = oidc.register_private_key_ix(c.payer.pubkey(), url, modulus(signing_key(4096)))
    assert not c.send([Instruction(oidc.OIDC_ID, b"\x09" + data[1:], private.accounts)]) and "InvalidInstructionData" in c.err
    numbered = oidc.register_key_ix(c.payer.pubkey(), GH, modulus(signing_key(4096)))
    assert not c.send([Instruction(oidc.OIDC_ID, b"\x03\x00" + odd.n.to_bytes(bits // 8, "big"), numbered.accounts)]) and "InvalidInstructionData" in c.err
    # a token such a key signed is refused under the issuer's registered key: its signature has the wrong length
    jwt = sign_jwt(odd, shaped(ISSUERS["google"], c))
    assert c.verify(jwt, url, modulus(example_key())) is None and code(c) == 65


def test_es256_es384_and_ps256_tokens_are_refused(chain):
    c, google, key = chain, ISSUERS["google"], example_key()
    n = modulus(key)

    def token(alg: str, sign) -> str:
        head = b64(json.dumps({"alg": alg, "typ": "JWT", "kid": "k"}, separators=(",", ":")).encode())
        body = b64(json.dumps(shaped(google, c, jti=alg), separators=(",", ":")).encode())
        return f"{head}.{body}.{b64(sign(f'{head}.{body}'.encode()))}"

    def ecdsa(curve, digest, size: int):
        private = ec.derive_private_key(0x1D0C5A11CE5EED, curve)

        def sign(data: bytes) -> bytes:
            from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
            r, s = decode_dss_signature(private.sign(data, ec.ECDSA(digest)))
            return r.to_bytes(size, "big") + s.to_bytes(size, "big")
        return sign

    # an elliptic-curve signature is not the length of the key: refused before anything is computed
    assert c.verify(token("ES256", ecdsa(ec.SECP256R1(), hashes.SHA256(), 32)), google["iss"], n) is None and code(c) == 65
    assert c.verify(token("ES384", ecdsa(ec.SECP384R1(), hashes.SHA384(), 48)), google["iss"], n) is None and code(c) == 65
    # PS256 is the same key with another padding: the signature is as long as the key and is not a PKCS#1 v1.5 one
    p, q = key.primes
    numbers = rsa.RSAPrivateNumbers(p, q, pow(65537, -1, (p - 1) * (q - 1)), pow(65537, -1, p - 1), pow(65537, -1, q - 1), pow(q, -1, p),
                                    rsa.RSAPublicNumbers(65537, key.n))
    pss = numbers.private_key()
    ps256 = token("PS256", lambda data: pss.sign(data, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=0), hashes.SHA256()))
    assert len(base64.urlsafe_b64decode(ps256.split(".")[2] + "==")) == 256
    assert c.verify(ps256, google["iss"], n) is None and code(c) == 70
    # and a token that only says PS256 or ES256 over a signature the key did make is refused by its header
    for alg in ("PS256", "ES256", "HS256", "none"):
        assert c.verify(token(alg, key.sign), google["iss"], n) is None and code(c) == 71, alg
    assert c.verify(token("RS256", key.sign), google["iss"], n) is not None, c.err
