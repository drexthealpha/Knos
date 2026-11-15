"""knos.platform.verdict.check spends the verdict it accepts: a replay is refused even by a caller that keeps no
nonce set of its own (a replay found in review: a caller that keeps no nonce set). Synthetic keys and data."""
from __future__ import annotations

from solders.keypair import Keypair

from knos.platform import verdict as v

NOW = 1_790_000_000


def _verdict(nonce: int):
    panel = [Keypair() for _ in range(3)]
    keys = [bytes(k.pubkey()) for k in panel]
    m = v.message(bytes([1]) * 32, bytes([2]) * 32, "PASS", 5_000_000, bytes([3]) * 32, NOW + 3600, nonce)
    return m, [v.sign(m, k) for k in panel[:2]], keys


def test_a_verdict_accepted_once_is_refused_the_second_time_with_the_callers_set():
    m, sigs, keys = _verdict(101)
    used: set = set()
    assert v.check(m, sigs, keys, 2, now=NOW, used=used)[0]
    assert (bytes([1]) * 32, 101) in used
    assert v.check(m, sigs, keys, 2, now=NOW, used=used) == (False, "replay: this job and nonce were used")


def test_a_caller_that_keeps_no_nonces_is_protected_by_the_default_store():
    m, sigs, keys = _verdict(102)
    assert v.check(m, sigs, keys, 2, now=NOW)[0]
    assert not v.check(m, sigs, keys, 2, now=NOW)[0]
    # a read-only set of its own does not let the replay through either
    assert not v.check(m, sigs, keys, 2, now=NOW, used=frozenset())[0]


def test_a_dry_run_spends_nothing_and_a_refusal_spends_nothing():
    m, sigs, keys = _verdict(103)
    used: set = set()
    assert v.check(m, sigs, keys, 2, now=NOW, used=used, record=False)[0] and not used
    assert not v.check(m, sigs[:1], keys, 2, now=NOW, used=used)[0] and not used
    assert v.check(m, sigs, keys, 2, now=NOW, used=used)[0] and used
