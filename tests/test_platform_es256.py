"""ES256 through the secp256r1 precompile (SIMD-0075, active on devnet) at top level, with the instructions-sysvar
check in knos-oidc's VerifyEs256 (programs-v2/knos_oidc/src/es256.rs). New in 0.4.0 (the 0.3.29 branch): in a v1 transaction (4,096
bytes, SIMD-0385) a token whose signing input is far longer than the 780 bytes a legacy transaction leaves is verified
in one transaction (knos.platform.verify.es256_v1_ixs). Under the test build of today's program and under the sBPF v2
build (tests/fixtures/platform/knos_oidc_v2_test.so)."""
from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("solders.litesvm")

import _es256 as m  # noqa: E402
from _oidc2 import Chain2  # noqa: E402
from _settle import FIX  # noqa: E402

from knos import chain as kchain  # noqa: E402
from knos.platform import verify  # noqa: E402
from knos.settle.v2 import oidc  # noqa: E402

URL, A = m.ISSUER, m.public(m.KEY_A)


def _token(length: int) -> str:
    signing = m.padded(length)
    return f"{signing.decode()}.{m.b64url(m.sign(m.KEY_A, signing)).decode()}"


@pytest.mark.parametrize("build", ["knos_oidc_v2_test.so", str(FIX / "platform" / "knos_oidc_v2_test.so")])
def test_a_long_es256_token_is_verified_in_one_v1_transaction(build, monkeypatch):
    monkeypatch.setattr(kchain, "V1_BUDGET_IX", True)
    c = Chain2(oidc_build=build)
    wallet = c.fund()
    assert c.send([oidc.register_private_es256_key_ix(wallet.pubkey(), URL, A)], wallet), c.err
    at = oidc.ec_key_pda(URL, A, registrant=wallet.pubkey())
    with pytest.raises(ValueError, match="at most 780"):
        oidc.verify_es256_ixs(wallet.pubkey(), at, _token(2_000), A)          # the legacy client stops at 780
    for length in (781, 2_000, 3_000):
        jwt = _token(length)
        ixs = verify.es256_v1_ixs(wallet.pubkey(), at, jwt, A)
        assert verify.fits_v1(ixs, wallet.pubkey()) and kchain.tx_size(ixs, wallet.pubkey()) > kchain.MAX_TX_BYTES
        assert c._sent(c.svm.send_transaction(kchain.sign(ixs, wallet, [], c.svm.latest_blockhash(), v1=True)), f"es{length}"), c.err
        tok = oidc.read_token(c.data(oidc.token_pda(wallet.pubkey(), hashlib.sha256(jwt.rsplit(".", 1)[0].encode()).digest())))
        assert tok is not None and tok.verified and tok.issuer == oidc.PRIVATE
        print(f"\nCU ES256 {length}-byte signing input, one v1 transaction ({kchain.tx_size(ixs, wallet.pubkey(), v1=True)} bytes), {build.rsplit('/', 2)[-2:]}: {c.cu[f'es{length}'][-1]}")
    # a signature over other bytes is refused by the precompile: the transaction does not run
    jwt = _token(2_000)
    head, body, sig = jwt.split(".")
    forged = f"{head}.{body[:-2]}{'A' if body[-2] != 'A' else 'B'}{body[-1]}.{sig}"
    ixs = verify.es256_v1_ixs(wallet.pubkey(), at, forged, A)
    assert not c._sent(c.svm.send_transaction(kchain.sign(ixs, wallet, [], c.svm.latest_blockhash(), v1=True)), None)
    # and a longest input still fits one v1 transaction
    longest = next(n for n in range(4_000, 2_000, -16) if verify.fits_v1(verify.es256_v1_ixs(wallet.pubkey(), at, _token(n), A), wallet.pubkey()))
    assert longest >= 3_400
