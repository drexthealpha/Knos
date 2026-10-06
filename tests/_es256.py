"""A model of ES256 as knos_oidc's VerifyEs256 takes it (programs-v2/knos_oidc/src/es256.rs, docs/ES256.md).

Pure Python, no dependency: P-256, ECDSA with the nonces of RFC 6979 (so a key and a message give one signature and
two runs write the same bytes), the two spellings of a signature (s and n - s), a compact ES256 token, and the data of
the secp256r1 precompile instruction that carries it. It is slow and not constant-time: for tests and vectors only.

    python tests/_es256.py            # write programs-v2/testdata/es256.json, which the Rust handler tests read
    python tests/_es256.py --check    # fail if the committed file differs from what this would write
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "programs-v2" / "testdata" / "es256.json"

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)
Point = tuple[int, int] | None

SIG_LEN = 64
KEY_LEN = 33
SELF = 0xFFFF  # an instruction index of the precompile: "these bytes are in my own data"
# A legacy transaction that carries one precompile instruction and VerifyEs256, without the signing input: one
# signature, seven account keys (payer, token, key, system, the instructions sysvar, the precompile, knos_oidc).
LEGACY_LIMIT = 1232
FIXED = (1 + 64) + 3 + (1 + 7 * 32) + 32 + 1 + (1 + 1 + 2 + 16 + KEY_LEN + SIG_LEN) + (1 + 1 + 5 + 1 + 1)
MAX_SIGNING_INPUT = LEGACY_LIMIT - FIXED  # 780

NOW = 1_790_000_000  # the clock the handler tests set
ISSUER = "https://issuer.example"
KEY_A = int.from_bytes(hashlib.sha256(b"knos es256 test key A").digest(), "big") % (N - 1) + 1
KEY_B = int.from_bytes(hashlib.sha256(b"knos es256 test key B").digest(), "big") % (N - 1) + 1


def add(a: Point, b: Point) -> Point:
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        m = (3 * a[0] * a[0] - 3) * pow(2 * a[1], -1, P) % P
    else:
        m = (b[1] - a[1]) * pow(b[0] - a[0], -1, P) % P
    x = (m * m - a[0] - b[0]) % P
    return x, (m * (a[0] - x) - a[1]) % P


def mul(k: int, point: Point) -> Point:
    out: Point = None
    while k:
        if k & 1:
            out = add(out, point)
        point = add(point, point)
        k >>= 1
    return out


def public(secret: int) -> bytes:
    """The key as the precompile and the key account hold it: SEC1 compressed, 0x02 or 0x03 then x."""
    point = mul(secret, G)
    assert point is not None
    return bytes([2 + (point[1] & 1)]) + point[0].to_bytes(32, "big")


def decompress(key: bytes) -> Point:
    x = int.from_bytes(key[1:], "big")
    y = pow((x * x * x - 3 * x + B) % P, (P + 1) // 4, P)
    if (y * y - (x * x * x - 3 * x + B)) % P != 0:
        raise ValueError("not a point of P-256")
    return x, y if (y & 1) == (key[0] & 1) else P - y


def _nonce(secret: int, digest: bytes) -> int:
    """RFC 6979, section 3.2, for P-256 and SHA-256."""
    x, h = secret.to_bytes(32, "big"), (int.from_bytes(digest, "big") % N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < N:
            return cand
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign(secret: int, message: bytes, high: bool = False) -> bytes:
    """r || s, 32 bytes each, as JWS writes an ES256 signature. s is the lower of the two values, or the upper."""
    digest = hashlib.sha256(message).digest()
    k = _nonce(secret, digest)
    point = mul(k, G)
    assert point is not None
    r = point[0] % N
    s = pow(k, -1, N) * (int.from_bytes(digest, "big") + r * secret) % N
    assert r and s
    s = min(s, N - s)
    return r.to_bytes(32, "big") + (N - s if high else s).to_bytes(32, "big")


def verify(key: bytes, message: bytes, signature: bytes) -> bool:
    """Plain ECDSA: both spellings of s pass."""
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (0 < r < N and 0 < s < N):
        return False
    w = pow(s, -1, N)
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    point = add(mul(e * w % N, G), mul(r * w % N, decompress(key)))
    return point is not None and point[0] % N == r


def low_s(signature: bytes) -> bool:
    return len(signature) == SIG_LEN and int.from_bytes(signature[32:], "big") <= N // 2


def normalise(signature: bytes) -> bytes:
    """What a relay does to a JWS signature before the precompile sees it: s becomes n - s when it is the upper one.
    It needs no secret, and the signing input is not touched."""
    s = int.from_bytes(signature[32:], "big")
    return signature[:32] + min(s, N - s).to_bytes(32, "big")


def precompile_accepts(key: bytes, message: bytes, signature: bytes) -> bool:
    """The precompile's rule (SIMD-0075): a valid signature whose s is the lower one."""
    return low_s(signature) and verify(key, message, signature)


def b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def signing_input(header: dict[str, object], payload: dict[str, object]) -> bytes:
    def enc(o: dict[str, object]) -> bytes:
        return b64url(json.dumps(o, separators=(",", ":")).encode())
    return enc(header) + b"." + enc(payload)


def padded(length: int) -> bytes:
    """A signing input of exactly `length` bytes: ISSUER's token with a claim that fills it."""
    for kid in range(4):
        header: dict[str, object] = {"alg": "ES256", "typ": "JWT", "kid": "k" * (kid + 1)}
        for pad in range(length):
            got = signing_input(header, {"iss": ISSUER, "exp": NOW + 300, "sub": "x" * pad})
            if len(got) == length:
                return got
            if len(got) > length:
                break
    raise ValueError(f"no token of {length} bytes")


def precompile_data(key: bytes, signature: bytes, message: bytes) -> bytes:
    """One signature, every part in the instruction's own data: count, padding, seven u16 LE, key, signature, message."""
    head = bytes([1, 0])
    for v in (16 + KEY_LEN, SELF, 16, SELF, 16 + KEY_LEN + SIG_LEN, len(message), SELF):
        head += v.to_bytes(2, "little")
    return head + key + signature + message


def vectors() -> dict[str, object]:
    claims: dict[str, object] = {"iss": ISSUER, "sub": "spiffe://issuer.example/workload", "aud": "knos-test", "exp": NOW + 300, "iat": NOW}
    good = signing_input({"alg": "ES256", "typ": "JWT", "kid": "a"}, claims)
    other = signing_input({"alg": "ES256", "typ": "JWT", "kid": "a"}, {**claims, "sub": "spiffe://issuer.example/other"})
    rs256 = signing_input({"alg": "RS256", "typ": "JWT", "kid": "a"}, claims)
    elsewhere = signing_input({"alg": "ES256", "typ": "JWT", "kid": "a"}, {**claims, "iss": "https://other.example"})
    late = signing_input({"alg": "ES256", "typ": "JWT", "kid": "a"}, {**claims, "exp": NOW + 86_401})
    twice = b64url(b'{"alg":"ES256","alg":"ES256"}') + b"." + good.split(b".")[1]
    largest, over = padded(MAX_SIGNING_INPUT), padded(MAX_SIGNING_INPUT + 1)
    a, b = public(KEY_A), public(KEY_B)
    tokens = {"good": good, "other": other, "rs256": rs256, "elsewhere": elsewhere, "late": late, "twice": twice, "largest": largest, "over": over}
    out: dict[str, object] = {
        "now": NOW, "issuer": ISSUER, "key_a": a.hex(), "key_b": b.hex(), "max_signing_input": MAX_SIGNING_INPUT,
        "tokens": {name: {"input": t.decode(), "sig_a": sign(KEY_A, t).hex()} for name, t in tokens.items()},
        "good_sig_b": sign(KEY_B, good).hex(), "good_sig_a_high": sign(KEY_A, good, high=True).hex(),
    }
    return out


def main(argv: list[str]) -> int:
    text = json.dumps(vectors(), indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT}: not what tests/_es256.py writes", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
