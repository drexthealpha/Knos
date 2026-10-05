"""The on-chain verifier against a reference, on a corpus of tokens made from a fixed seed.

The program is the BUILT one: tests/fixtures/knos_oidc_v2_test.so in LiteSVM, each token written and stepped as a relay
does it (tests/_oidc2.py). The test build differs from the deployed one in what it trusts (the two seed keys of
tests/_settle.py), not in how it verifies.

The reference is written here and shares no code with the program or with the client:

  THE RULE. A token is accepted exactly when all of this holds:
    1. it is three non-empty parts separated by two dots, each part unpadded base64url in its one canonical spelling
       (RFC 7515 section 2: the URL alphabet, no `=`, no white space, no bits left over);
    2. its third part is as long as the key's modulus and is a valid RSASSA-PKCS1-v1_5 signature with SHA-256 over
       the bytes of the first two parts and the dot between them (RFC 8017 section 8.2.2). Two voices are asked and
       must agree with each other: OpenSSL through the `cryptography` package, and RFC 8017's own steps on Python
       integers (RSAVP1, I2OSP, the encoding made again and compared);
    3. its header is a JSON document (see below) in which `alg` is the string RS256;
    4. its payload is a JSON document in which `iss` is the issuer's URL and `exp` is a whole number written in
       plain digits, below 10^18 and at most one day ahead of the clock.
  A JSON document here is one object of RFC 8259 in every byte, read by Python's `json` from strict UTF-8 (so:
  the literals `true`, `false` and `null` and no other word, numbers by the grammar, no control character in a
  string, only JSON's escapes, brackets that match, nothing after the object), and three things more, each of them
  a place where two JSON readers are known to differ: no name appears twice in the top-level object (RFC 8259
  section 4 leaves the outcome to the reader), no string holds half a surrogate pair written as an escape (section
  8.2: Python reads one, serde_json refuses it), and the document is at most 64 levels deep with at most 128
  members in its top-level object (section 9 lets a reader set such limits, and every reader has some).
  The rule says nothing of `aud`, `iat`, `nbf` or whether `exp` has passed: the verifier records what was signed,
  and the program that spends the token reads those (a second `aud` is refused there, with error 62).

The corpus is valid tokens and the classic ways a verifier is fooled (each kind is a function below, named for what it
does): signatures that open to a wrong encoding, as Bleichenbacher's 2006 forgery needs (bytes after the digest, short
padding, no 00 01, another DigestInfo, the NULL left out or doubled, more leading zeros), the cube root forgery
itself, signatures not below the modulus or of another length, headers that name another algorithm, claims written
twice, nested, escaped, with exponents or out of range, payloads the issuer's key really signed that are not JSON
in a value the verifier has no use for, and base64 in other spellings.

Three things are asserted for every case:
  - the program's answer is the reference's;
  - a token the program accepts has a signature both voices call valid, and the `exp` it recorded is the one signed;
  - the reference's answer is what the kind was written to get (so a broken generator cannot pass by making
    everything refused).
No class of token is outside the rule. (Until knos-oidc 2.2 one was: a payload that is not JSON in a value the
verifier does not read. The 2.1 program accepted all thirteen shapes of it that this file makes, `NOT_JSON` below
and bytes that are not UTF-8, and the reference refused them; 2.2 refuses each, and they are kinds like any other.)

    python -m pytest -q -s tests/test_oidc_differential.py           250 cases (KNOS_DIFF_CASES=N for more)
    python tests/test_oidc_differential.py --minutes 10 --record     the long run; writes docs/fuzz.json
    python tests/test_oidc_differential.py --seeds                   writes the fuzz targets' seed corpus
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import re
import subprocess
import sys
import time

import pytest

pytest.importorskip("solders.litesvm")

from _oidc2 import GH, GL, Chain2  # noqa: E402
from _settle import FIX, NOW, github_claims, gitlab_claims, modulus, signing_key  # noqa: E402

from knos.settle.v2 import oidc  # noqa: E402

ROOT = FIX.parents[1]
SEED = 20261005
CASES = int(os.environ.get("KNOS_DIFF_CASES", "250"))      # read at import: conftest clears KNOS_* per test
RECORD = ROOT / "docs" / "fuzz.json"
PROGRAM = "knos_oidc_v2_test.so"
SEEDS = ROOT / "programs-v2" / "knos_oidc" / "fuzz" / "seeds"
VECTORS = ROOT / "programs-v2" / "knos_oidc" / "tests" / "vectors"
AHEAD = 86_400
T_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")       # RFC 8017 section 9.2, note 1
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


# ---- the reference ----------------------------------------------------------------------------------------------------

def unbase64url(part: str) -> bytes | None:
    """The bytes of an unpadded base64url string in its canonical spelling; None for any other string."""
    if not part or any(c not in ALPHABET for c in part) or len(part) % 4 == 1:
        return None
    number = 0
    for c in part:
        number = number << 6 | ALPHABET.index(c)
    spare = 6 * len(part) % 8                                 # the bits of the last character that belong to no byte
    if number & ((1 << spare) - 1):
        return None
    return (number >> spare).to_bytes(6 * len(part) // 8, "big")


def rfc8017_verify(n: int, e: int, message: bytes, signature: bytes) -> bool:
    """RSASSA-PKCS1-V1_5-VERIFY with SHA-256, step by step as RFC 8017 section 8.2.2 writes it."""
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:                                   # step 1
        return False
    s = int.from_bytes(signature, "big")                      # 2a: OS2IP
    if not 0 <= s < n:                                        # 2b: RSAVP1 refuses a representative out of range
        return False
    em = pow(s, e, n).to_bytes(k, "big")                      # 2b, 2c: I2OSP
    t = T_SHA256 + hashlib.sha256(message).digest()           # 3: EMSA-PKCS1-v1_5-ENCODE
    if k < len(t) + 11:
        return False
    return hmac.compare_digest(em, b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t)      # 4


def openssl_verify(key, message: bytes, signature: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        key.public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError):
        return False


class Members(list):
    """A JSON object's members as they were written, a name that comes twice kept twice."""


class Digits(str):
    """A JSON integer as it was written."""


DEEPEST = 64          # levels: the top-level object is one
MOST = 128            # members of the top-level object


def _walk(value):
    """(level, value) for a document and every value inside it, the document itself at level 1. A loop, not a
    recursion: a document nested a thousand deep is one the rule must be able to refuse."""
    todo = [(1, value)]
    while todo:
        level, v = todo.pop()
        yield level, v
        if type(v) is Members:
            todo += [(level + 1, x) for pair in v for x in pair]      # a name is a string one level in, like a value
        elif type(v) is list:
            todo += [(level + 1, x) for x in v]


def _object(doc: bytes) -> dict | None:
    """A JSON document's top-level members, or None when the bytes are not a JSON document as the rule has it."""
    def refuse(_):
        raise ValueError("NaN and Infinity are not JSON")
    try:
        got = json.loads(doc.decode("utf-8"), object_pairs_hook=Members, parse_int=Digits, parse_float=float, parse_constant=refuse)
    except (ValueError, RecursionError):
        return None
    if type(got) is not Members or len({name for name, _ in got}) != len(got) or len(got) > MOST:
        return None
    for level, v in _walk(got):
        if type(v) in (Members, list) and level > DEEPEST:
            return None
        if type(v) is str and any("\ud800" <= c <= "\udfff" for c in v):
            return None
    return dict(got)


def reference(token: str, key, issuer: str, now: int) -> tuple[bool, str, bool | None, int | None]:
    """(accepted, the first clause of the rule it fails, whether the signature is valid when that could be asked,
    the `exp` signed)."""
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return False, "parts", None, None
    head, body, sig = (unbase64url(p) for p in parts)
    signed = None
    if sig is not None:
        message = f"{parts[0]}.{parts[1]}".encode()
        signed = openssl_verify(key, message, sig)
        assert signed == rfc8017_verify(key.n, 65537, message, sig), f"the reference's two voices differ on {token}"
    if head is None or body is None or sig is None:
        return False, "base64url", signed, None
    if not signed:
        return False, "signature", signed, None
    header = _object(head)
    if header is None or type(header.get("alg")) is not str or header["alg"] != "RS256":
        return False, "alg", signed, None
    claims = _object(body)
    if claims is None:
        return False, "claims", signed, None
    if type(claims.get("iss")) is not str or claims["iss"] != issuer:
        return False, "iss", signed, None
    exp = claims.get("exp")
    if type(exp) is not Digits or not exp.isdigit() or len(exp) > 18 or int(exp) > now + AHEAD:
        return False, "exp", signed, None
    return True, "", signed, int(exp)


# ---- the corpus -------------------------------------------------------------------------------------------------------

def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def dumps(o) -> bytes:
    return json.dumps(o, separators=(",", ":")).encode()


def private(key, m: int) -> int:
    """m^d mod n by the key's primes."""
    out = 0
    for p in key.primes:
        rest = key.n // p
        out += pow(m % p, key.d % (p - 1), p) * rest * pow(rest, -1, p)
    return out % key.n


def icbrt(x: int) -> int:
    """The smallest integer whose cube is at least x."""
    r = 1 << -(-x.bit_length() // 3)
    while True:
        nxt = (2 * r + x // (r * r)) // 3
        if nxt >= r:
            break
        r = nxt
    while r ** 3 < x:
        r += 1
    return r


class Make:
    """One case being made: a key, an issuer, fresh claims, and the pieces a kind puts together."""
    def __init__(self, rng: random.Random, bits: int, index: int):
        self.rng, self.bits, self.k = rng, bits, bits // 8
        self.key = signing_key(bits)
        self.issuer = GH if bits == 2048 else GL
        self.url = oidc.ISSUERS[self.issuer]
        fill = "".join(rng.choice("abcdef0123456789:/-_.~?>") for _ in range(rng.randrange(1, 120)))
        self.claims = (github_claims if bits == 2048 else gitlab_claims)(aud=f"knos-diff:{fill}", jti=f"d{index}-{rng.getrandbits(64):x}",
                                                                           iat=NOW, exp=NOW + rng.randrange(1, 600))
        self.header = {"typ": "JWT", "alg": "RS256", "kid": f"{rng.getrandbits(32):08x}"}

    # the three parts
    def head(self, header=None) -> str:
        return b64(header if isinstance(header, bytes) else dumps(self.header if header is None else header))

    def body(self, payload=None, **over) -> str:
        return b64(payload if isinstance(payload, bytes) else dumps({**self.claims, **over}))

    def text(self, **over) -> str:
        """The payload as text, to be written wrongly by hand: it ends in `}`."""
        return dumps({**self.claims, **over}).decode()

    def digest(self, signing_input: str) -> bytes:
        return hashlib.sha256(signing_input.encode()).digest()

    def em(self, signing_input: str, t: bytes | None = None) -> bytes:
        t = T_SHA256 + self.digest(signing_input) if t is None else t
        return b"\x00\x01" + b"\xff" * (self.k - len(t) - 3) + b"\x00" + t

    def sign_em(self, em: bytes) -> bytes:
        """The signature that opens to exactly these bytes (a number below the modulus, whose first byte is C4 or more)."""
        assert len(em) == self.k and int.from_bytes(em, "big") < self.key.n, em[:4].hex()
        return private(self.key, int.from_bytes(em, "big")).to_bytes(self.k, "big")

    def sig(self, signing_input: str) -> bytes:
        return self.sign_em(self.em(signing_input))

    def token(self, head: str | None = None, body: str | None = None) -> str:
        si = f"{self.head() if head is None else head}.{self.body() if body is None else body}"
        return f"{si}.{b64(self.sig(si))}"

    def opened(self, build) -> str:
        """A good header and payload under a signature that opens to build(signing input): a wrong encoding."""
        si = f"{self.head()}.{self.body()}"
        return f"{si}.{b64(self.sign_em(build(si)))}"

    def raw(self, sig) -> str:
        si = f"{self.head()}.{self.body()}"
        return f"{si}.{b64(sig(si) if callable(sig) else sig)}"


KINDS: dict[str, tuple[str, object]] = {}      # name -> (what the rule answers: "accept" or the clause it fails, the maker)


def kind(want: str):
    def add(f):
        KINDS[f.__name__] = (want, f)
        return f
    return add


# -- valid tokens
@kind("accept")
def valid(m): return m.token()
@kind("accept")
def valid_long_audience(m): return m.token(body=m.body(aud="knos2:" + "a:" * m.rng.randrange(200, 900)))
@kind("accept")
def valid_exp_exactly_a_day_ahead(m): return m.token(body=m.body(exp=NOW + AHEAD))
@kind("accept")
def valid_exp_already_past(m): return m.token(body=m.body(exp=NOW - m.rng.randrange(1, 10 ** 6)))     # the spender asks whether it is fresh


# -- signatures that open to a wrong encoding (signed with the test key, so only the encoding is at fault)
@kind("signature")
def em_bytes_after_the_digest(m):
    g = m.rng.randrange(1, m.k - 62)
    return m.opened(lambda si: b"\x00\x01" + b"\xff" * (m.k - 54 - g) + b"\x00" + T_SHA256 + m.digest(si) + m.rng.randbytes(g))
@kind("signature")
def em_bytes_after_the_digest_eight_ff(m):       # the shape of the 2006 forgery: the least padding, the rest garbage
    return m.opened(lambda si: b"\x00\x01" + b"\xff" * 8 + b"\x00" + T_SHA256 + m.digest(si) + m.rng.randbytes(m.k - 62))
@kind("signature")
def em_short_padding(m):
    j = m.rng.randrange(0, 8)
    return m.opened(lambda si: b"\x00\x01" + b"\xff" * j + b"\x00" + T_SHA256 + m.digest(si) + b"\x00" * (m.k - 54 - j))
@kind("signature")
def em_extra_leading_zeros(m):
    z = m.rng.randrange(1, m.k - 62)
    return m.opened(lambda si: b"\x00" * z + b"\x00\x01" + b"\xff" * (m.k - 54 - z) + b"\x00" + T_SHA256 + m.digest(si))
@kind("signature")
def em_no_00_01(m):
    lead = m.rng.choice([b"\x00\x02", b"\x00\x00", b"\x01\x01", b"\x00\xff", b"\x01\xff", b"\x00\x03", b"\x02\x01"])
    return m.opened(lambda si: lead + m.em(si)[2:])
@kind("signature")
def em_block_type_removed(m): return m.opened(lambda si: b"\x00" + m.em(si)[2:] + b"\x00")
@kind("signature")
def em_padding_byte_not_ff(m):
    at, byte = m.rng.randrange(2, m.k - 52), m.rng.choice([0x00, 0x01, 0xfe, 0x7f])
    return m.opened(lambda si: m.em(si)[:at] + bytes([byte]) + m.em(si)[at + 1:])
@kind("signature")
def em_separator_not_zero(m): return m.opened(lambda si: m.em(si)[:m.k - 52] + bytes([m.rng.randrange(1, 256)]) + m.em(si)[m.k - 51:])
@kind("signature")
def em_null_left_out(m): return m.opened(lambda si: m.em(si, bytes.fromhex("302f300b0609608648016503040201" "0420") + m.digest(si)))
@kind("signature")
def em_null_doubled(m): return m.opened(lambda si: m.em(si, bytes.fromhex("3033300f0609608648016503040201" "05000500" "0420") + m.digest(si)))
@kind("signature")
def em_digestinfo_of_another_hash(m):
    name, prefix = m.rng.choice([("sha1", "3021300906052b0e03021a05000414"), ("sha384", "3041300d060960864801650304020205000430"),
                                 ("sha512", "3051300d060960864801650304020305000440"), ("md5", "3020300c06082a864886f70d020505000410"),
                                 ("sha224", "302d300d06096086480165030402040500041c")])
    return m.opened(lambda si: m.em(si, bytes.fromhex(prefix) + hashlib.new(name, si.encode()).digest()))
@kind("signature")
def em_digestinfo_names_another_hash_over_the_sha256_digest(m):
    prefix = m.rng.choice(["3031300d060960864801650304020205000420", "3031300d060960864801650304020305000420", "3031300d060960864801650304020405000420"])
    return m.opened(lambda si: m.em(si, bytes.fromhex(prefix) + m.digest(si)))
@kind("signature")
def em_digestinfo_in_another_der_spelling(m):
    spelled = m.rng.choice(["308131300d060960864801650304020105000420",              # the outer length in the long form
                            "3032300e06096086480165030402010500000420"[:38] + "20",  # a byte of the lengths changed
                            "3031300d06096086480165030402010500048120",              # the digest's length in the long form
                            "3031300d0609608648016503040201050004" + "1f",           # a digest one byte short, by its length
                            "3080300d060960864801650304020105000420",                # indefinite length
                            "3031300d060960864801650304020105010420"])               # a NULL with content
    return m.opened(lambda si: m.em(si, bytes.fromhex(spelled) + m.digest(si)))
@kind("signature")
def em_digest_changed(m):
    at = m.rng.randrange(32)
    return m.opened(lambda si: m.em(si)[:m.k - 32 + at] + bytes([m.em(si)[m.k - 32 + at] ^ (1 << m.rng.randrange(8))]) + m.em(si)[m.k - 31 + at:])
@kind("signature")
def em_digest_alone(m): return m.opened(lambda si: b"\x00" * (m.k - 32) + m.digest(si))
@kind("signature")
def em_digest_of_the_payload_only(m):
    return m.opened(lambda si: m.em(si, T_SHA256 + hashlib.sha256(si.split(".")[1].encode()).digest()))
@kind("signature")
def cube_root_forgery(m):
    """Bleichenbacher 2006 as it was: no key. The cube root of 00 01 FF x8 00 DigestInfo digest garbage, which a
    verifier with exponent 3 that stops reading at the digest accepts. Here the exponent is 65537."""
    def forge(si):
        prefix = b"\x00\x01" + b"\xff" * 8 + b"\x00" + T_SHA256 + m.digest(si)
        s = icbrt(int.from_bytes(prefix + b"\x00" * (m.k - len(prefix)), "big"))
        assert (s ** 3).to_bytes(m.k, "big")[:len(prefix)] == prefix and s ** 3 < m.key.n      # it is the real forgery
        return s.to_bytes(m.k, "big")
    return m.raw(forge)
@kind("signature")
def signature_of_another_token(m): return m.raw(m.sig(f"{m.head()}.{m.body(jti='another')}"))
@kind("signature")
def signature_bit_flipped(m):
    at = m.rng.randrange(8 * m.k - 8)          # not the top byte: the number stays below the modulus or the kind changes
    return m.raw(lambda si: (int.from_bytes(m.sig(si), "big") ^ (1 << at)).to_bytes(m.k, "big"))
@kind("signature")
def signature_small_number(m): return m.raw(m.rng.choice([0, 1, 2, 3, 65537]).to_bytes(m.k, "big"))
@kind("signature")
def signature_modulus_less_one(m): return m.raw((m.key.n - m.rng.randrange(1, 3)).to_bytes(m.k, "big"))
@kind("signature")
def signature_random(m): return m.raw(m.rng.randrange(m.key.n).to_bytes(m.k, "big"))
@kind("signature")
def pss_signature_under_an_rs256_header(m): return m.raw(lambda si: pss(m, si))

# -- signatures that are not a number below the modulus, or not as long as it
@kind("signature")
def signature_is_the_modulus_or_just_above(m): return m.raw((m.key.n + m.rng.randrange(0, 3)).to_bytes(m.k, "big"))
@kind("signature")
def signature_all_ones(m): return m.raw(b"\xff" * m.k)
@kind("signature")
def signature_plus_the_modulus(m):
    """A good signature that was not reduced: s + n opens to the same bytes. It fits the length for about one token in four."""
    for salt in range(400):
        body = m.body(jti=f"{m.claims['jti']}-{salt}")
        si = f"{m.head()}.{body}"
        s = int.from_bytes(m.sig(si), "big") + m.key.n
        if s < 1 << (8 * m.k):
            return f"{si}.{b64(s.to_bytes(m.k, 'big'))}"
    raise AssertionError("no token's signature plus the modulus fits")
@kind("signature")
def signature_with_a_leading_zero_byte(m): return m.raw(lambda si: b"\x00" * m.rng.randrange(1, 4) + m.sig(si))
@kind("signature")
def signature_with_a_byte_after_it(m): return m.raw(lambda si: m.sig(si) + m.rng.randbytes(m.rng.randrange(1, 4)))
@kind("signature")
def signature_a_byte_short(m): return m.raw(lambda si: m.sig(si)[m.rng.choice([0, 1]):][:m.k - 1])
@kind("signature")
def signature_of_the_other_key_size(m):
    other = Make(m.rng, 4096 if m.bits == 2048 else 2048, -1)
    return m.raw(lambda si: other.sig(si))
@kind("signature")
def signature_one_byte(m): return m.raw(b"\x01")

# -- headers that name another algorithm (the signature is a good RS256 one over the header as sent, unless said)
@kind("alg")
def alg_none(m): return m.token(head=m.head({**m.header, "alg": m.rng.choice(["none", "None", "NONE", "nOnE", ""])}))
@kind("parts")
def alg_none_with_no_signature(m): return f"{m.head({'typ': 'JWT', 'alg': 'none'})}.{m.body()}" + m.rng.choice([".", ""])
@kind("alg")
def alg_hs256(m): return m.token(head=m.head({**m.header, "alg": m.rng.choice(["HS256", "HS384", "HS512"])}))
@kind("signature")
def alg_hs256_keyed_with_the_public_key(m):
    """Algorithm confusion as it is done: an HMAC keyed with the public key, which a verifier that lets the header pick takes."""
    si = f"{m.head({**m.header, 'alg': 'HS256'})}.{m.body()}"
    secret = m.rng.choice([m.key.n.to_bytes(m.k, "big"), b64(m.key.n.to_bytes(m.k, "big")).encode()])
    return f"{si}.{b64(hmac.new(secret, si.encode(), hashlib.sha256).digest())}"
@kind("alg")
def alg_rs384(m): return m.token(head=m.head({**m.header, "alg": m.rng.choice(["RS384", "RS512", "RS1", "ES256", "EdDSA"])}))
@kind("signature")
def alg_rs384_signed_as_rs384(m):
    si = f"{m.head({**m.header, 'alg': 'RS384'})}.{m.body()}"
    return f"{si}.{b64(m.sign_em(m.em(si, bytes.fromhex('3041300d060960864801650304020205000430') + hashlib.sha384(si.encode()).digest())))}"
@kind("alg")
def alg_ps256(m): return m.token(head=m.head({**m.header, "alg": m.rng.choice(["PS256", "PS384", "PS512"])}))
@kind("signature")
def alg_ps256_signed_as_ps256(m):
    si = f"{m.head({**m.header, 'alg': 'PS256'})}.{m.body()}"
    return f"{si}.{b64(pss(m, si))}"
@kind("alg")
def alg_in_another_case(m):
    return m.token(head=m.head({**m.header, "alg": m.rng.choice(["rs256", "Rs256", "rS256", "RS256 ", " RS256", "RS256\x00", "RS-256", "RS256\n", "RS2560", "RSA256"])}))
@kind("alg")
def alg_twice(m):
    first, second = m.rng.choice([("RS256", "RS256"), ("none", "RS256"), ("RS256", "none"), ("HS256", "RS256"), ("RS256", "HS256")])
    name = m.rng.choice(['"alg"', '"\\u0061lg"', '"a\\u006cg"', '"\\u0061\\u006C\\u0067"'])
    return m.token(head=m.head(f'{{"alg":"{first}","typ":"JWT",{name}:"{second}"}}'.encode()))
@kind("alg")
def alg_missing(m): return m.token(head=m.head(m.rng.choice([{"typ": "JWT"}, {}, {"ALG": "RS256"}, {"alg ": "RS256"}, {"x": {"alg": "RS256"}}, {"algorithm": "RS256"}])))
@kind("alg")
def alg_not_a_string(m): return m.token(head=m.head({**m.header, "alg": m.rng.choice([256, ["RS256"], {"alg": "RS256"}, None, True, ["none", "RS256"]])}))
@kind("alg")
def header_not_an_object(m):
    return m.token(head=m.head(m.rng.choice([b'["alg","RS256"]', b'"RS256"', b'[{"alg":"RS256"}]', b'{"alg":"RS256"', b'{"alg":"RS256"}}', b'{"alg":"RS256"} {}',
                                             b'{"alg":"RS256"}\x00', b'{"alg":"RS256",}', b"{'alg':'RS256'}", b'{"alg":RS256}', b'\xef\xbb\xbf{"alg":"RS256"}', b'null', b' '])))
@kind("accept")
def alg_rs256_spelled_with_escapes(m):       # the same text to any JSON reader
    spelled = m.rng.choice(['"alg":"RS\\u0032\\u0035\\u0036"', '"\\u0061lg":"RS256"', '"alg":"\\u0052S256"', '"a\\u006Cg":"\\u0052\\u0053256"'])
    return m.token(head=m.head(f'{{"typ":"JWT",{spelled}}}'.encode()))
@kind("accept")
def header_with_white_space(m): return m.token(head=m.head(b' {\n\t"typ" : "JWT" ,\r\n "alg"\t:\t"RS256" } \n'))
@kind("accept")
def header_that_carries_a_key_of_its_own(m):
    """jwk, jku, x5u, kid: a verifier that takes its key from the header is fooled. This one's key is the account it is given."""
    extra = m.rng.choice([{"jwk": {"kty": "RSA", "e": "AQAB", "n": b64(m.rng.randbytes(256))}}, {"jku": "https://evil.example/keys"},
                          {"x5u": "https://evil.example/cert"}, {"kid": "../../../../dev/null"}, {"crit": ["exp"]}, {"nested": {"alg": "none"}}])
    return m.token(head=m.head({**m.header, **extra}))

# -- claims (the signature is a good one over the payload as sent)
@kind("claims")
def iss_twice(m):
    evil = m.rng.choice(["https://evil.example", m.url])
    first, second = m.rng.choice([(evil, m.url), (m.url, evil)])
    name = m.rng.choice(['"iss"', '"\\u0069ss"', '"is\\u0073"', '"\\u0069\\u0073\\u0073"'])
    return m.token(body=b64((f'{{"iss":"{first}",' + m.text(iss=second)[1:-1].replace('"iss"', name) + "}").encode()))
@kind("claims")
def exp_twice(m):
    return m.token(body=b64((m.text()[:-1] + "," + m.rng.choice(['"exp"', '"\\u0065xp"', '"ex\\u0070"']) + f":{NOW + m.rng.choice([5, 10 ** 9])}}}").encode()))
@kind("claims")
def aud_twice(m):                            # not a claim the verifier reads, and a name twice all the same (62)
    return m.token(body=b64((m.text()[:-1] + "," + m.rng.choice(['"aud"', '"\\u0061ud"']) + ':"knos2:someone-else"}').encode()))
@kind("iss")
def iss_not_a_string(m):
    return m.token(body=m.body(iss=m.rng.choice([{"iss": m.url}, [m.url], None, 7, True, {"a": m.url}, [[m.url]]])))
@kind("iss")
def iss_only_inside_another_value(m):
    c = {k: v for k, v in m.claims.items() if k != "iss"}
    return m.token(body=b64(dumps({**c, m.rng.choice(["x", "act", "cnf"]): {"iss": m.url}, "list": [{"iss": m.url}]})))
@kind("iss")
def iss_look_alike(m):
    u = m.url
    return m.token(body=m.body(iss=m.rng.choice([u + "/", u.upper(), u.replace("https", "http"), u + "\x00", " " + u, u + " ", u + ".evil.example", u.replace(".com", ".co"),
                                                 u + "\n", u[:-1], "", u.replace("https://", "https://evil.example@"), u + "\u200b", u.replace("o", "\u043e", 1), u + '","x":"'])))
@kind("iss")
def iss_with_an_escaped_quote(m):
    """`\\u0022` is a quote inside the text, not the end of it: the claim after it is part of the issuer's name."""
    how = m.rng.choice(['https://evil.example\\u0022,\\u0022iss\\u0022:\\u0022' + m.url, m.url + '\\u0022,\\u0022x\\u0022:\\u0022', m.url + '\\"', '\\"' + m.url + '\\"',
                        m.url + "\\u0000", m.url + "\\n", m.url + "\\\\"])
    return m.token(body=b64(m.text().replace(f'"iss":"{m.url}"', f'"iss":"{how}"').encode()))
@kind("accept")
def iss_spelled_with_escapes(m):
    at = m.rng.randrange(len(m.url))
    spelled = m.rng.choice([m.url.replace("/", "\\/"), m.url[:at] + f"\\u{ord(m.url[at]):04x}" + m.url[at + 1:], "".join(f"\\u{ord(c):04X}" for c in m.url)])
    name = m.rng.choice(['"iss"', '"\\u0069ss"'])
    return m.token(body=b64(m.text().replace(f'"iss":"{m.url}"', f'{name}:"{spelled}"').encode()))
@kind("exp")
def exp_with_an_exponent(m):
    t = NOW + 300
    return _exp(m, m.rng.choice([f"{t}e0", f"{t}E0", f"{t // 10}e1", "1.7900003e9", f"{t}.0", f"{t}.5", "1e9", "1E400", f"{t}e-0", "0.0"]))
@kind("exp")
def exp_huge(m): return _exp(m, m.rng.choice([str(10 ** 18), str(2 ** 63), str(2 ** 64), str(2 ** 64 + NOW + 300), "9" * 40, str(NOW + AHEAD + 1), str(2 ** 32 * 1000), "1" + "0" * 400]))
@kind("exp")
def exp_not_plain_digits(m): return _exp(m, m.rng.choice(["-1", "-0", f"-{NOW + 300}", f'"{NOW + 300}"', "null", "true", f"[{NOW + 300}]", f'{{"exp":{NOW + 300}}}', '""']))
@kind("claims")
def exp_not_json(m): return _exp(m, m.rng.choice([f"0{NOW + 300}", f"+{NOW + 300}", "0x6ab1f230", f"{NOW + 300}.", f".{NOW}", "1_790_000_300", f"{NOW + 300}L", "Infinity", "NaN", "١٧٩"]))
@kind("exp")
def exp_missing(m): return m.token(body=b64(dumps({k: v for k, v in m.claims.items() if k != "exp"} | m.rng.choice([{}, {"EXP": NOW + 300}, {"x": {"exp": NOW + 300}}]))))
@kind("accept")
def iat_and_nbf_in_other_forms(m):           # the verifier reads neither: they are the issuer's, and the token is the issuer's
    return m.token(body=m.body(iat=m.rng.choice([1.79e9, str(NOW), 10 ** 30, -5, None, {"iat": NOW}, NOW + 10 ** 6]), nbf=m.rng.choice([NOW + 10 ** 6, 2.5, "soon"])))
@kind("accept")
def payload_with_white_space(m):
    return m.token(body=b64(json.dumps(m.claims, indent=m.rng.choice([1, 2, "\t"]), separators=(m.rng.choice([",", " ,", ",\r\n"]), m.rng.choice([": ", " : ", ":\t"]))).encode() + m.rng.choice([b"", b"\n", b" \r\n\t"])))
@kind("accept")
def payload_with_nested_values(m):
    deep = m.rng.randrange(1, 40)
    return m.token(body=m.body(nest=json.loads("[" * deep + '{"iss":"x","exp":1,"}":"]"}' + "]" * deep), text='}{"iss":"evil",\\', uni="\u00e9\u4e2d\U0001f600", esc="\n\t\"\\"))
@kind("claims")
def payload_cut_short(m):
    text = m.text()
    return m.token(body=b64(text[:m.rng.randrange(1, len(text))].encode()))
@kind("claims")
def payload_with_more_after_it(m):
    return m.token(body=b64(m.text().encode() + m.rng.choice([b"{}", b"}", b" x", b"\x00", b",", b'{"iss":"x"}', b"\xef\xbb\xbf", b"\x0c", b"//", b"]"])))
@kind("claims")
def payload_not_an_object(m):
    t = m.text()
    return m.token(body=b64(m.rng.choice([f"[{t}]", f'"{t[1:-1]}"', "null", "[]", "7", f"\ufeff{t}", f"\x0c{t}", f"/**/{t}", t[1:], t.replace(":", "=", 1), t.replace('"', "'"),
                                          "{" + t, t[:-1] + ",}", "{," + t[1:], t.replace(",", ",,", 1), t.replace(",", ";", 1), t.replace('":', '"', 1)]).encode()))

# -- a payload the test key really signed that is not JSON, in a value the verifier has no use for. Each shape is a
# kind of its own, so that every one of them is in any run of len(KINDS) cases and in the fuzz targets' seed corpus.
NOT_JSON = {"a literal cut short": '"x":tru', "a number with a leading zero": '"x":01', "brackets that do not match": '"x":[}', "a control character in a string": '"x":"a\x01b"',
            "an escape JSON does not have": '"x":"\\q"', "NaN": '"x":NaN', "a bare word": '"x":@#$', "a form feed after a number": '"x":1\x0c', "a comment as a value": '"x":/**/1',
            "a single-quoted value": "\"x\":'y'", "a number with two points": '"x":1.2.3', "a unicode escape cut short": '"x":"\\u12"'}


def _not_json(what: str, written: str):
    def make(m):
        return m.token(body=b64((m.text()[:-1] + "," + written + "}").encode()))
    make.__name__ = "unread_value_" + re.sub(r"[^a-z0-9]+", "_", what.lower())
    return kind("claims")(make)


for _what, _written in NOT_JSON.items():
    _not_json(_what, _written)
@kind("claims")
def unread_value_bytes_that_are_not_utf8(m):
    return m.token(body=b64(m.text()[:-1].encode() + b',"x":"' + m.rng.choice([b"\xff", b"\xc3\x28", b"\xed\xa0\x80", b"\xc0\x80", b"\xf4\x90\x80\x80", b"\xe4\xb8"]) + b'"}'))
@kind("claims")
def unread_value_other_ways_not_to_be_json(m):
    written = m.rng.choice(['"x":True', '"x":nul', '"x":-', '"x":1.', '"x":.5', '"x":1e', '"x":+1', '"x":0x10', '"x":[1,]', '"x":{"k":1,}', '"x":{"k"}', '"x":[1 2]', '"x":{]',
                            '"x":[1}', '"x":"a\tb"', '"x":"a\nb"', '"x":"\\x41"', '"x":"\\u12g4"', '"x":Infinity', '"x":-Infinity', '"x":undefined', '"x":1//', "'x':1", 'x:1',
                            '"x":"a\x00b"', '"x\x01":1', '"\\q":1'])
    return m.token(body=b64((m.text()[:-1] + "," + written + "}").encode()))
@kind("claims")
def unread_value_half_a_surrogate_pair(m):                     # Python's json reads these and serde_json does not: the rule refuses them
    written = m.rng.choice(['"\\ud800"', '"\\udc00"', '"\\ud83d"', '"\\ude00\\ud83d"', '"\\ud83dx"', '"\\ud83d\\u0041"', '["\\udfff"]', '{"\\ud800":1}'])
    return m.token(body=b64((m.text()[:-1] + ',"x":' + written + "}").encode()))
@kind("claims")
def unread_name_twice(m):
    first, second = m.rng.choice([('"x"', '"x"'), ('"x"', '"\\u0078"'), ('"caf\u00e9"', '"caf\\u00e9"'), ('"\U0001f600"', '"\\ud83d\\ude00"'), ('""', '""'), ('"jti"', '"jti"')])
    return m.token(body=b64((m.text()[:-1] + f',{first}:1,"y":2,{second}:1}}').encode()))
@kind("accept")
def unread_name_twice_below_the_top_level(m):                  # the rule compares the names of the top-level object only
    return m.token(body=b64((m.text()[:-1] + ',"x":{"k":1,"k":2,"iss":"a","iss":"b"},"y":[{"exp":1,"exp":2}]}').encode()))
@kind("accept")
def unread_values_of_every_json_form(m):
    return m.token(body=b64((m.text()[:-1] + ',"x":[true,false,null,0,-0,1.5,-1.25e+7,1E400,12345678901234567890123,"","\\" \\\\ \\/ \\b \\f \\n \\r \\t \\u0000 \\ud83d\\ude00",'
                             '"caf\u00e9 \u4e2d \U0001f600 \x7f",[],{},[ ] ,{ }],"X":1,"x ":2}').encode()))
@kind("claims")
def nested_deeper_than_the_rule_allows(m):
    deep = m.rng.choice([DEEPEST, DEEPEST + 1, 200])
    nest = m.rng.choice(["[" * deep + "]" * deep, '{"k":' * deep + "1" + "}" * deep, "[" * 900 + "]" * 900])      # 900: deeper than many a reader's own stack
    return m.token(body=b64((m.text()[:-1] + ',"x":' + nest + "}").encode()))
@kind("accept")
def nested_as_deep_as_the_rule_allows(m):
    deep = DEEPEST - 1
    return m.token(body=b64((m.text()[:-1] + ',"x":' + m.rng.choice(["[" * deep + "]" * deep, '{"k":' * deep + "1" + "}" * deep, '[{"k":' * (deep // 2) + "[]" + "}]" * (deep // 2)]) + "}").encode()))
@kind("claims")
def more_members_than_the_rule_allows(m):
    return m.token(body=b64((m.text()[:-1] + "".join(f',"m{k}":{k}' for k in range(MOST + 1 - len(m.claims))) + "}").encode()))
@kind("accept")
def as_many_members_as_the_rule_allows(m):
    return m.token(body=b64((m.text()[:-1] + "".join(f',"m{k}":{k}' for k in range(MOST - len(m.claims))) + "}").encode()))

# -- base64url in other spellings
@kind("base64url")
def b64_padding_on_the_signature(m): return m.token() + m.rng.choice(["==", "=", "==="])
@kind("base64url")
def b64_padding_on_a_signed_part(m):
    """`=` on the header or the payload, signed over as sent: a reader that strips padding sees a good token."""
    head, body = _odd(m)
    if m.rng.random() < 0.5:
        head += "=" * (-len(head) % 4)
    else:
        body += "=" * (-len(body) % 4)
    return m.token(head=head, body=body)
@kind("base64url")
def b64_standard_alphabet_in_the_signature(m):
    for salt in range(400):
        t = m.token(body=m.body(jti=f"{m.claims['jti']}-{salt}"))
        h, p, s = t.split(".")
        if "-" in s or "_" in s:
            return f"{h}.{p}.{s.replace('-', '+').replace('_', '/')}"
    raise AssertionError("no signature with - or _ in it")
@kind("base64url")
def b64_standard_alphabet_in_a_signed_part(m):
    body = m.body(x="???>>>~~~" * m.rng.randrange(1, 4) + "?")
    assert "-" in body or "_" in body
    return m.token(body=body.replace("-", "+").replace("_", "/"))
@kind("base64url")
def b64_white_space_in_the_signature(m):
    t = m.token()
    at = m.rng.randrange(t.rindex(".") + 1, len(t) + 1)
    return t[:at] + m.rng.choice([" ", "\n", "\t", "\r\n"]) + t[at:]
@kind("base64url")
def b64_white_space_in_a_signed_part(m):
    head, body = m.head(), m.body()
    at = m.rng.randrange(len(body) + 1)
    body = body[:at] + m.rng.choice([" ", "\n", "\t", "\r\n"]) + body[at:]
    return m.token(head=m.rng.choice([head, " " + head]) if at % 2 else head, body=body)
@kind("base64url")
def b64_bits_left_over(m):
    """The last character spelled another way: a decoder that drops the spare bits reads the same bytes."""
    head, body = _odd(m)
    t = m.token(head=head, body=body).split(".")
    part = m.rng.randrange(3)
    spare = 2 if len(t[part]) % 4 == 3 else 4
    assert len(t[part]) % 4 in (2, 3)
    t[part] = t[part][:-1] + ALPHABET[ALPHABET.index(t[part][-1]) | m.rng.randrange(1, 1 << spare)]
    if part < 2:                                         # signed over as sent
        return m.token(head=t[0], body=t[1])
    return ".".join(t)
@kind("base64url")
def b64_a_character_too_many(m):
    t = m.token().split(".")
    part = m.rng.randrange(3)
    t[part] += "A" * ((1 - len(t[part])) % 4 or 4)
    assert len(t[part]) % 4 == 1
    return m.token(head=t[0], body=t[1]) if part < 2 else ".".join(t)
@kind("base64url")
def b64_a_character_outside_the_alphabet(m):
    t = m.token()
    at = m.rng.randrange(len(t))
    return t[:at] + m.rng.choice("=+/ ~%!*\\\"',:;@") + t[at + 1:] if t[at] != "." else t + "!"
@kind("parts")
def parts_not_three(m):
    h, p, s = m.token().split(".")
    return m.rng.choice([f"{h}.{p}", f"{h}.{p}.{s}.", f".{h}.{p}.{s}", f"{h}.{p}.{s}.{s}", f"{h}..{s}", f".{p}.{s}", f"{h}.{p}..{s}", f"{h}.{p}.{s}.{p}.{s}", f"{h}{p}.{s}", f"{h}.{p}."])


def _exp(m: Make, written: str) -> str:
    return m.token(body=b64(m.text().replace(f'"exp":{m.claims["exp"]}', f'"exp":{written}').encode()))


def _odd(m: Make) -> tuple[str, str]:
    """A header and a payload whose base64 is not a whole number of four characters (so padding and spare bits exist)."""
    header, pad = dict(m.header), 0
    while len(dumps(header)) % 3 == 0:
        header["kid"] += "0"
    while len(dumps({**m.claims, "pad": "p" * pad})) % 3 == 0:
        pad += 1
    return m.head(header), m.body(pad="p" * pad)


def pss(m: Make, si: str) -> bytes:
    """RSASSA-PSS with SHA-256, MGF1 and a 32-byte salt (RFC 8017 section 9.1.1), under the test key."""
    h, salt, bits = m.digest(si), m.rng.randbytes(32), m.bits - 1
    em_len = (bits + 7) // 8
    hh = hashlib.sha256(b"\x00" * 8 + h + salt).digest()
    db = b"\x00" * (em_len - 66) + b"\x01" + salt
    mask = b"".join(hashlib.sha256(hh + c.to_bytes(4, "big")).digest() for c in range(-(-len(db) // 32)))[:len(db)]
    masked = bytearray(a ^ b for a, b in zip(db, mask))
    masked[0] &= 0xff >> (8 * em_len - bits)
    return private(m.key, int.from_bytes(bytes(masked) + hh + b"\xbc", "big")).to_bytes(m.k, "big")


def corpus(n: int, seed: int = SEED):
    """n cases from the seed: (index, kind, the maker with its key, token, what the rule answers). Every kind comes round
    in turn, so any n of at least len(KINDS) has them all; one case in ten is under the 4096-bit key."""
    names = list(KINDS)
    for i in range(n):
        rng = random.Random(f"knos differential {seed} {i}")
        name = names[i % len(names)]
        m = Make(rng, 4096 if rng.random() < 0.1 else 2048, i)
        want, make = KINDS[name]
        yield i, name, m, make(m), want


# ---- the run ----------------------------------------------------------------------------------------------------------

def code(c: Chain2) -> int | None:
    found = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(found.group(1)) if found else None


def run(n: int, seed: int = SEED, budget: float | None = None) -> dict:
    """Puts n cases to the program and to the reference (fewer when `budget` seconds run out first). Returns the
    counts; `disagreements` and `unsound` list what failed."""
    started = time.monotonic()
    c = Chain2(PROGRAM)
    for bits, issuer in ((2048, GH), (4096, GL)):
        assert c.register(issuer, modulus(signing_key(bits))), c.err
    out = {"cases": 0, "accepted": 0, "refused": 0, "disagreements": [], "unsound": [], "generator": [], "kinds": {}, "refused_by_error": {},
           "refused_by_clause": {}, "bits": {"2048": 0, "4096": 0}}
    for i, name, m, token, want in corpus(n, seed):
        if budget is not None and time.monotonic() - started > budget:
            break
        ref, clause, signed, exp = reference(token, m.key, m.url, NOW)
        account = c.verify(token, m.issuer, m.key.n)
        got, err = account is not None, code(c)
        out["bits"][str(m.bits)] += 1
        out["cases"] += 1
        out["accepted" if got else "refused"] += 1
        kinds = out["kinds"].setdefault(name, {"cases": 0, "accepted": 0})
        kinds["cases"] += 1
        kinds["accepted"] += got
        if got != ref:
            out["disagreements"].append(f"case {i} ({name}, {m.bits} bits): the program {'accepts' if got else f'refuses ({err})'}, the reference {'accepts' if ref else f'refuses ({clause})'}: {token}")
        if ref != (want == "accept") or (not ref and clause != want):
            out["generator"].append(f"case {i} ({name}): written to get {want!r}, the reference says {'accept' if ref else clause!r}")
        if not got:
            out["refused_by_error"][str(err)] = out["refused_by_error"].get(str(err), 0) + 1
            out["refused_by_clause"][clause] = out["refused_by_clause"].get(clause, 0) + 1
        if got:
            tok = oidc.read_token(c.data(account))
            if signed is not True or tok is None or not tok.verified or tok.issuer != m.issuer or (exp is not None and tok.exp != exp):
                out["unsound"].append(f"case {i} ({name}): accepted with signature {signed}, issuer {getattr(tok, 'issuer', None)}, exp {getattr(tok, 'exp', None)} for {exp}: {token}")
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


def program_hash() -> str:
    return hashlib.sha256((FIX / PROGRAM).read_bytes()).hexdigest()


def test_the_program_and_the_reference_give_the_same_answer_on_every_case():
    r = run(CASES)
    print(f"\ndifferential: {r['cases']} cases in {r['seconds']} s (seed {SEED}): {r['accepted']} accepted by both, {r['refused']} refused by both, "
          f"{len(r['disagreements'])} disagreements; refused by error {dict(sorted(r['refused_by_error'].items()))}")
    assert not r["generator"], "\n".join(r["generator"][:10])
    assert not r["unsound"], "\n".join(r["unsound"][:10])
    assert not r["disagreements"], "\n".join(r["disagreements"][:10])
    assert r["cases"] == CASES
    if CASES >= len(KINDS):
        assert set(r["kinds"]) == set(KINDS)
        assert all(cell["accepted"] in (0, cell["cases"]) for cell in r["kinds"].values())      # a kind is all one answer
        assert r["accepted"] >= 10 and r["bits"]["4096"] >= 1
        # every way the program has to say no is reached: base64 (60), JSON (61), twice (62), a claim (63), the
        # signature's length or range (65), its encoding (70), alg (71), iss (72)
        assert {"60", "61", "62", "63", "65", "70", "71", "72"} <= set(r["refused_by_error"]), r["refused_by_error"]
        # each of the thirteen shapes 2.1 accepted (a payload not JSON in a value the verifier does not read) is refused
        unread = [k for k in KINDS if k.startswith("unread_value_") and KINDS[k][0] == "claims"]
        assert len(unread) >= len(NOT_JSON) + 1 == 13 and all(r["kinds"][k]["accepted"] == 0 for k in unread)


def test_the_reference_knows_a_good_signature_from_each_classic_forgery_without_the_program():
    """The reference on its own, against vectors nobody here made: Project Wycheproof's, under their own keys. Its two
    voices agree on all of them, call the valid ones valid, and refuse the rest (the `acceptable` ones too: a
    DigestInfo without its NULL is not what RFC 8017 section 9.2 encodes)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    seen = {"valid": 0, "invalid": 0, "acceptable": 0}
    for bits in (2048, 4096):
        doc = json.loads((VECTORS / f"rsa_signature_{bits}_sha256_test.json").read_text(encoding="utf-8"))
        for group in doc["testGroups"]:
            n, e = int(group["publicKey"]["modulus"], 16), int(group["publicKey"]["publicExponent"], 16)
            public = rsa.RSAPublicNumbers(e, n).public_key()

            class Key:
                public_key = staticmethod(lambda public=public: public)
            for t in group["tests"]:
                msg, sig = bytes.fromhex(t["msg"]), bytes.fromhex(t["sig"])
                ours = rfc8017_verify(n, e, msg, sig)
                assert ours == openssl_verify(Key, msg, sig) == (t["result"] == "valid"), (bits, t["tcId"], t["comment"])
                seen[t["result"]] += 1
    assert sum(seen.values()) == 517 and seen["valid"] >= 14 and seen["acceptable"] == 2, seen
    assert unbase64url("AQ") == b"\x01" and unbase64url("AR") is None and unbase64url("AQ==") is None and unbase64url("A") is None and unbase64url("+_8") is None


def test_the_corpus_is_the_same_on_every_machine_and_holds_every_kind():
    first = [(name, token) for _, name, _, token, _ in corpus(len(KINDS))]
    assert first == [(name, token) for _, name, _, token, _ in corpus(len(KINDS))]
    assert [name for name, _ in first] == list(KINDS) and len(KINDS) >= 80
    assert hashlib.sha256("\n".join(token for _, token in first).encode()).hexdigest() == CORPUS_SHA256


def committed_sums() -> str:
    """tests/fixtures/SHA256SUMS as this commit has it. program.yml builds the test binaries again in place of the
    committed ones and the build script rewrites their lines, so on that runner the file on disk names the runner's own
    build, which is not byte for byte the committed one. The file on disk only where this is not a git checkout."""
    r = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:tests/fixtures/SHA256SUMS"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 and r.stdout.strip() else (FIX / "SHA256SUMS").read_text(encoding="utf-8")


def test_the_recorded_long_run_is_of_this_program_this_seed_and_this_corpus():
    """docs/fuzz.json is the long run, made by `python tests/test_oidc_differential.py --cases N --record`. It is a
    record of one run: its program hash is the committed test build's, its seed and its kinds are this file's."""
    rec = json.loads(RECORD.read_text(encoding="utf-8"))["differential"]
    sums = dict(reversed(line.split()) for line in committed_sums().splitlines() if line.strip())
    assert rec["program"] == f"tests/fixtures/{PROGRAM}" and rec["program_sha256"] == sums[f"tests/fixtures/{PROGRAM}"]
    assert rec["seed"] == SEED and rec["kinds"] == len(KINDS) and rec["corpus_sha256"] == CORPUS_SHA256
    assert rec["disagreements"] == 0 and rec["accepted_with_an_invalid_signature"] == 0
    assert rec["cases"] == rec["accepted_by_both"] + rec["refused_by_both"] and rec["cases"] >= 10 * len(KINDS)
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", rec["date"])
    assert "outside_the_rule" not in rec                      # since 2.2 no class of token is outside the rule
    unread = rec["not_json_in_an_unread_value"]["by_kind"]
    assert len(unread) >= 13 and all(cell["accepted"] in (0, cell["cases"]) for cell in unread.values())
    # the document says the run's numbers and no others
    page = (ROOT / "docs" / "ASSURANCE.md").read_text(encoding="utf-8")
    assert f"{rec['cases']:,} cases" in page and rec["date"] in page and rec["program_sha256"] in page


def test_the_seed_corpus_of_the_fuzz_targets_is_made_from_these_cases_and_the_wycheproof_vectors():
    """`--seeds` writes programs-v2/knos_oidc/fuzz/seeds: what is committed is what it writes today."""
    want = seeds()
    have = {p.relative_to(SEEDS).as_posix(): p.read_bytes() for p in SEEDS.rglob("*") if p.is_file()}
    assert have == want, sorted(set(have) ^ set(want))[:5]
    assert sum(len(b) for b in want.values()) < 400_000 and {name.split("/")[0] for name in want} == {"claims", "rsa_verify"}


CORPUS_SHA256 = "95bceb45540b619bd79a74dc82036419ba8bee3dabdbd86b7fb3bb307372b37b"      # the first len(KINDS) tokens: change a kind and this changes


# ---- the fuzz targets' seed corpus ------------------------------------------------------------------------------------

def seeds() -> dict[str, bytes]:
    """{path under fuzz/seeds: bytes}. For the `claims` target: the header and the payload of each kind above, as
    the JSON reader gets them. For the `rsa_verify` target (its input is fuzz/src/rsa_diff.rs's): each kind's signature with
    the test key's modulus and the digest it should open to, each wrong encoding as the bytes the signature opens to,
    and Project Wycheproof's vectors under their own keys (all of the 2048-bit file with exponent 65537; of the
    4096-bit file the valid ones and the first of each set of flags)."""
    out: dict[str, bytes] = {}
    for _, name, m, token, _ in corpus(len(KINDS)):
        parts = token.split(".")
        for which, part in zip(("header", "payload"), parts[:2]):
            doc = unbase64url(part)
            if doc is not None:
                out[f"claims/{name}-{which}"] = doc
        sig = unbase64url(parts[2]) if len(parts) == 3 and parts[2] else None
        if sig is not None and m.bits == 2048 and len(parts) == 3:
            digest = hashlib.sha256(f"{parts[0]}.{parts[1]}".encode()).digest()
            out[f"rsa_verify/{name}"] = b"\x00" + digest + m.key.n.to_bytes(256, "big") + sig
            if name.startswith("em_"):          # and what it opens to, for the test key to sign there: the fuzzer's way to a wrong encoding
                out[f"rsa_verify/opened-{name}"] = b"\x02" + digest + pow(int.from_bytes(sig, "big"), 65537, m.key.n).to_bytes(256, "big")
    for bits in (2048, 4096):
        doc = json.loads((VECTORS / f"rsa_signature_{bits}_sha256_test.json").read_text(encoding="utf-8"))
        told: set[str] = set()
        for group in doc["testGroups"]:
            n, e = int(group["publicKey"]["modulus"], 16), int(group["publicKey"]["publicExponent"], 16)
            for t in group["tests"]:
                # the 4096-bit file repeats the 2048-bit file's flaws under a longer key: its valid vectors, and
                # the first of each set of flags
                flags = ",".join(sorted(t["flags"]))
                if e != 65537 or (bits == 4096 and flags in told and t["result"] != "valid"):
                    continue
                told.add(flags)
                out[f"rsa_verify/wycheproof-{bits}-{t['tcId']:03}"] = (bytes([bits // 4096]) + hashlib.sha256(bytes.fromhex(t["msg"])).digest()
                                                               + n.to_bytes(bits // 8, "big") + bytes.fromhex(t["sig"]))
    return out


def main(argv: list[str]) -> int:
    import argparse
    import datetime
    ap = argparse.ArgumentParser(description="The long differential run, and the fuzz targets' seed corpus.")
    ap.add_argument("--cases", type=int, default=CASES)
    ap.add_argument("--minutes", type=float, help="as many cases as this long allows (the record says how many: --cases with that number repeats it)")
    ap.add_argument("--record", action="store_true", help=f"write the run to {RECORD.relative_to(ROOT)}")
    ap.add_argument("--seeds", action="store_true", help=f"write {SEEDS.relative_to(ROOT)}")
    a = ap.parse_args(argv)
    if a.seeds:
        want = seeds()
        for old in [p for p in SEEDS.rglob("*") if p.is_file()]:
            old.unlink()
        for name, data in want.items():
            (SEEDS / name).parent.mkdir(parents=True, exist_ok=True)
            (SEEDS / name).write_bytes(data)
        print(f"{len(want)} seeds, {sum(len(b) for b in want.values())} bytes, in {SEEDS.relative_to(ROOT)}")
        return 0
    r = run(10 ** 9 if a.minutes else a.cases, budget=a.minutes and 60 * a.minutes)
    bad = r["disagreements"] + r["unsound"] + r["generator"]
    print("\n".join(bad[:20]))
    total = r["cases"]
    print(f"{r['cases']} cases in {r['seconds']} s: {r['accepted']} accepted by both, {r['refused']} refused by both, {len(r['disagreements'])} disagreements, "
          f"{len(r['unsound'])} accepted with an invalid signature")
    if a.record and not r["generator"]:
        doc = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
        doc["differential"] = {
            "what": "the built verifier in LiteSVM against a reference (OpenSSL and RFC 8017 section 8.2.2 on Python integers for the signature, "
                    "Python's json for the header and the claims) on tokens made from a fixed seed: tests/test_oidc_differential.py",
            "command": f"python tests/test_oidc_differential.py --cases {total} --record",
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), "seed": SEED, "kinds": len(KINDS), "corpus_sha256": CORPUS_SHA256,
            "program": f"tests/fixtures/{PROGRAM}", "program_sha256": program_hash(),
            "cases": r["cases"], "accepted_by_both": r["accepted"] if not r["disagreements"] else None, "refused_by_both": r["refused"] if not r["disagreements"] else None,
            "disagreements": len(r["disagreements"]), "accepted_with_an_invalid_signature": len(r["unsound"]),
            "refused_by_program_error": dict(sorted(r["refused_by_error"].items())), "refused_by_clause_of_the_rule": dict(sorted(r["refused_by_clause"].items())),
            "key_bits": r["bits"], "seconds": r["seconds"],
            "not_json_in_an_unread_value": {"what": "payloads the test key signed that are not JSON, or are JSON two readers take differently, in a value the verifier "
                                                    "does not read (the thirteen shapes knos-oidc 2.1 accepted, and more): counted in `cases`; each kind's cases and "
                                                    "how many of them the program accepted",
                                            "by_kind": {k: v for k, v in sorted(r["kinds"].items()) if k.startswith("unread_")}},
            "failures": bad[:50]}
        RECORD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {RECORD.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
