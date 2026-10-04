"""Project Wycheproof's RSASSA-PKCS1-v1_5 SHA-256 vectors through the verifier's ON-CHAIN path: the compiled program
in LiteSVM, the token written and stepped as a relay does it (Write, then Step by Step), 517 vectors in all.
`programs-v2/knos_oidc/tests/wycheproof.rs` runs the same files through `verify_native`, the one-call form of the same
arithmetic; this runs them through the form the chain runs.

A vector is (key, message, signature, verdict). The program does not take a message: it verifies a token, and what it
hashes is the token's own first two parts. No token's first two parts are the vectors' messages (they are "123400"
and the like, with no dot in them), and the vectors' private keys are not published, so a vector cannot be fed to the
program as it stands. What a vector tests is what its signature OPENS to: the encoded message s^e mod n, which is a
right or a wrong PKCS#1 v1.5 encoding of the message's digest. So each vector is carried over:

  1. the signature is opened with the vector's own public key (Python integers): the encoded message, k bytes;
  2. where that holds the SHA-256 of the vector's message, those 32 bytes are replaced by the SHA-256 of a token's
     first two parts; everything else (padding, DigestInfo, lengths, trailing bytes) is the vector's, byte for byte;
  3. that encoded message is signed again with the test key the test build trusts (2048 bits for the 2048-bit file,
     4096 for the other), and the token with that signature is written and stepped on chain.

The program must verify it when the vector says valid and refuse it with error 70 (not the issuer's signature) when it
says invalid or acceptable (a DigestInfo without its NULL: this verifier compares the whole encoding). What this does
not carry over is the vector's own modulus: the arithmetic runs under the two test moduli. A vector whose flaw is in
the signature as a number (not below the modulus, or of another length) cannot be opened at all; those are put to the
program under the test key with the same flaw (the test modulus itself, one more, all ones, the test modulus added to
a valid signature; a byte more or less) and must be refused with error 65 at the first step (61 for the empty signature: a token with no third part).

What could not be carried over: a vector whose opened encoding is not below the test modulus (a first byte that is
wrong and large). No signature under the test key opens to such a number, so there would be nothing to send. The files
have no such vector today (NOT_CARRIED pins that); one that appears is counted, printed with Wycheproof's comment, must
be an invalid one, and fails the test until the count here is changed.

With -s the test prints its counts and its time.
"""
from __future__ import annotations

import hashlib
import json
import time

import pytest

pytest.importorskip("solders.litesvm")

from _oidc2 import GH, GL, Chain2  # noqa: E402
from _settle import FIX, NOW, b64, github_claims, gitlab_claims, modulus, signing_key  # noqa: E402

from knos.settle.v2 import oidc  # noqa: E402

VECTORS = FIX.parents[1] / "programs-v2" / "knos_oidc" / "tests" / "vectors"
HEAD = b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": "k"}, separators=(",", ":")).encode())
E_JSON, E_SIG, E_BADSIG = 61, 65, 70
NOT_CARRIED = {2048: 0, 4096: 0}          # vectors whose flawed encoding is not below the test modulus (see above)


def signing_input(bits: int, tc: int, salt: int = 0) -> str:
    """The first two parts of a token of the issuer whose test key has this size, one per vector (and per `salt`)."""
    claims = (github_claims if bits == 2048 else gitlab_claims)(aud=f"wycheproof:{bits}:{tc}", jti=f"w{bits}-{tc}-{salt}", iat=NOW, exp=NOW + 300)
    return f"{HEAD}.{b64(json.dumps(claims, separators=(',', ':')).encode())}"


def private(key, m: int) -> int:
    """m^d mod n with the test key, by its primes (the plain power takes a quarter of a second at 4096 bits)."""
    out = 0
    for p in key.primes:
        rest = key.n // p
        out += pow(m % p, key.d % (p - 1), p) * rest * pow(rest, -1, p)
    return out % key.n


def encoded(key, head: str) -> bytes:
    """The PKCS#1 v1.5 encoding of this token's digest, as long as the test key's modulus: what a good signature opens to."""
    t = key.DIGEST_INFO + hashlib.sha256(head.encode()).digest()
    return b"\x00\x01" + b"\xff" * (key.bits // 8 - len(t) - 3) + b"\x00" + t


def carried(n_w: int, e_w: int, msg: bytes, sig: bytes, key, head: str) -> tuple[str, bytes | None]:
    """("resigned", the signature under the test key of the vector's encoding over this token's digest), or
    ("shape", the test key's signature with the vector's flaw of length or range; None when this token's signature
    plus the modulus does not fit the modulus's length: another token's will), or ("unsignable", None)."""
    k, n = key.bits // 8, key.n
    top = (1 << (8 * k)) - 1
    if len(sig) != k:                                   # a byte more or less than the modulus
        good = private(key, int.from_bytes(encoded(key, head), "big")).to_bytes(k, "big")
        return "shape", b"\x00" * (len(sig) - k) + good if len(sig) > k else good[k - len(sig):]
    if (s_w := int.from_bytes(sig, "big")) >= n_w:      # not below the modulus
        # all ones stays all ones; the modulus itself, or a little above it, is the test modulus and as much; anything
        # else is a signature that was not reduced: this token's good signature plus the test modulus
        out = top if s_w == top else n + (s_w - n_w) if s_w - n_w < 1 << 16 else private(key, int.from_bytes(encoded(key, head), "big")) + n
        return "shape", out.to_bytes(k, "big") if out <= top else None
    em = pow(int.from_bytes(sig, "big"), e_w, n_w).to_bytes(k, "big")
    digest = hashlib.sha256(msg).digest()
    if em.count(digest) == 1:
        em = em.replace(digest, hashlib.sha256(head.encode()).digest())
    if int.from_bytes(em, "big") >= n:
        return "unsignable", None
    return "resigned", private(key, int.from_bytes(em, "big")).to_bytes(k, "big")


def code(c: Chain2) -> int | None:
    import re
    m = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(m.group(1)) if m else None


@pytest.mark.parametrize("bits", [2048, 4096])
def test_wycheproof_vectors_through_the_on_chain_step_path(bits):
    started = time.monotonic()
    doc = json.loads((VECTORS / f"rsa_signature_{bits}_sha256_test.json").read_text(encoding="utf-8"))
    key, issuer = signing_key(bits), GH if bits == 2048 else GL
    n = modulus(key)
    c = Chain2()
    assert c.register(issuer, n), c.err                 # the test build's genesis key of this size
    seen = {"valid verified": 0, "invalid refused": 0, "acceptable refused": 0, "refused for its length or range": 0, "not carried over": 0}
    left: list[str] = []
    for group in doc["testGroups"]:
        n_w, e_w = int(group["publicKey"]["modulus"], 16), int(group["publicKey"]["publicExponent"], 16)
        assert n_w.bit_length() == bits
        for t in group["tests"]:
            tc, verdict = t["tcId"], t["result"]
            for salt in range(64):                      # a signature plus the modulus fits the length for about one token in four
                head = signing_input(bits, tc, salt)
                how, sig = carried(n_w, e_w, bytes.fromhex(t["msg"]), bytes.fromhex(t["sig"]), key, head)
                if sig is not None or how != "shape":
                    break
            if sig is None:
                assert verdict == "invalid", f"tcId {tc} is {verdict} and could not be carried over"
                seen["not carried over"] += 1
                left.append(f"tcId {tc} ({t['comment']})")
                continue
            account = c.verify(f"{head}.{b64(sig)}", issuer, n)
            if how == "shape":                         # an empty signature leaves a token of two parts, which is no token: error 61
                assert verdict == "invalid" and account is None and code(c) == (E_SIG if sig else E_JSON), f"{bits} tcId {tc} ({t['comment']}): {c.err}"
                seen["refused for its length or range"] += 1
            elif verdict == "valid":
                tok = oidc.read_token(c.data(account)) if account is not None else None
                assert tok is not None and tok.verified and tok.issuer == issuer, f"{bits} tcId {tc} is valid and the program refused it: {c.err}"
                seen["valid verified"] += 1
            else:
                assert account is None and code(c) == E_BADSIG, f"{bits} tcId {tc} ({verdict}: {t['comment']}) was not refused with error 70: {c.err or 'VERIFIED'}"
                seen[f"{verdict} refused"] += 1
    total = sum(len(g["tests"]) for g in doc["testGroups"])
    print(f"\nwycheproof {bits}, on chain: {total} vectors in {time.monotonic() - started:.1f} s: "
          + ", ".join(f"{count} {what}" for what, count in seen.items()) + (f". Not carried over: {'; '.join(left)}" if left else ""))
    assert total == doc["numberOfTests"] == sum(seen.values()) and seen["not carried over"] == NOT_CARRIED[bits]
    assert seen["valid verified"] >= 7 and seen["acceptable refused"] == 1 and seen["refused for its length or range"] >= 6
    assert seen["invalid refused"] >= 240


def test_carrying_a_vector_over_keeps_its_encoding_and_changes_only_the_digest():
    """The carried signature opens, under the test key, to the vector's encoded message with one thing changed: the
    digest of the vector's message is the digest of the token's first two parts."""
    doc = json.loads((VECTORS / "rsa_signature_2048_sha256_test.json").read_text(encoding="utf-8"))
    key, checked = signing_key(2048), 0
    for group in doc["testGroups"]:
        n_w, e_w = int(group["publicKey"]["modulus"], 16), int(group["publicKey"]["publicExponent"], 16)
        for t in group["tests"]:
            head, msg, sig = signing_input(2048, t["tcId"]), bytes.fromhex(t["msg"]), bytes.fromhex(t["sig"])
            how, mine = carried(n_w, e_w, msg, sig, key, head)
            if how != "resigned":
                continue
            theirs = pow(int.from_bytes(sig, "big"), e_w, n_w).to_bytes(256, "big")
            opened = pow(int.from_bytes(mine, "big"), 65537, key.n).to_bytes(256, "big")
            old, new = hashlib.sha256(msg).digest(), hashlib.sha256(head.encode()).digest()
            assert opened == (theirs.replace(old, new) if theirs.count(old) == 1 else theirs)
            if t["result"] == "valid":
                assert opened == b"\x00\x01" + b"\xff" * 202 + b"\x00" + key.DIGEST_INFO + new      # exactly what the test key itself would sign
                assert mine == key.sign(head.encode())
            checked += 1
    assert checked >= 240
    assert all(private(k, 12345) == pow(12345, k.d, k.n) for k in (key, signing_key(4096)))
