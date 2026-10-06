"""The ES256 model (tests/_es256.py) against known answers, and the vectors the Rust handler tests read."""
from __future__ import annotations

import hashlib
import json

import _es256 as m


def test_the_curve_and_the_nonces_are_those_of_rfc_6979():
    # RFC 6979, appendix A.2.5: P-256, SHA-256, message "sample"
    x = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
    assert m.public(x).hex() == "0360fed4ba255a9d31c961eb74c6356d68c049b8923b61fa6ce669622e60f29fb6"
    sig = m.sign(x, b"sample")
    assert sig[:32].hex().upper() == "EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716"
    rfc_s = 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8
    assert int.from_bytes(sig[32:], "big") == min(rfc_s, m.N - rfc_s)
    assert m.verify(m.public(x), b"sample", sig) and not m.verify(m.public(x), b"sampel", sig)


def test_both_spellings_verify_and_the_precompile_takes_only_the_lower():
    key, msg = m.public(m.KEY_A), b"header.payload"
    low, high = m.sign(m.KEY_A, msg), m.sign(m.KEY_A, msg, high=True)
    assert low != high and low[:32] == high[:32]
    assert m.verify(key, msg, low) and m.verify(key, msg, high)
    assert m.precompile_accepts(key, msg, low) and not m.precompile_accepts(key, msg, high)
    # a relay turns the upper one into the lower one with no secret, and nothing else into anything that passes
    assert m.normalise(high) == low and m.normalise(low) == low
    assert not m.precompile_accepts(key, msg + b"x", m.normalise(high))
    assert not m.precompile_accepts(m.public(m.KEY_B), msg, low)


def test_the_bound_is_what_a_legacy_transaction_leaves():
    assert (m.FIXED, m.MAX_SIGNING_INPUT) == (452, 780)
    assert len(m.padded(m.MAX_SIGNING_INPUT)) == 780 and len(m.padded(781)) == 781
    data = m.precompile_data(m.public(m.KEY_A), bytes(64), b"abc")
    assert len(data) == 2 + 14 + 33 + 64 + 3 and data[:2] == b"\x01\x00"
    assert data[2:16] == b"".join(v.to_bytes(2, "little") for v in (49, 0xFFFF, 16, 0xFFFF, 113, 3, 0xFFFF))


def test_the_committed_vectors_are_what_the_model_writes():
    assert m.main(["--check"]) == 0
    doc = json.loads(m.OUT.read_text(encoding="utf-8"))
    a, b = bytes.fromhex(doc["key_a"]), bytes.fromhex(doc["key_b"])
    for name, t in doc["tokens"].items():
        assert m.precompile_accepts(a, t["input"].encode(), bytes.fromhex(t["sig_a"])), name
    good = doc["tokens"]["good"]["input"].encode()
    assert m.precompile_accepts(b, good, bytes.fromhex(doc["good_sig_b"]))
    assert not m.precompile_accepts(a, good, bytes.fromhex(doc["good_sig_b"]))
    high = bytes.fromhex(doc["good_sig_a_high"])
    assert m.verify(a, good, high) and not m.precompile_accepts(a, good, high)
    assert hashlib.sha256(good).digest() != hashlib.sha256(doc["tokens"]["other"]["input"].encode()).digest()
