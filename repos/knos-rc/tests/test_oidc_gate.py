"""examples/oidc_gate: another Solana program requires a GitHub-signed fact by reading a knos-oidc token account
(LiteSVM). It records the commit GitHub says a repository's workflow ran on, and refuses anything GitHub did not sign,
an account that is not knos-oidc's, another audience, a self-hosted runner and a stale token."""
from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("solders.litesvm")

from solders.account import Account  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _settle import FIX, Chain, modulus, signing_key  # noqa: E402

from knos.settle import oidc  # noqa: E402

GATE = Pubkey.from_bytes(hashlib.sha256(b"oidc_gate example program").digest())
REPO = 424242001


def record(c: Chain, tok: Pubkey, repo: int = REPO) -> bool:
    gate = Pubkey.find_program_address([b"gate", repo.to_bytes(8, "little")], GATE)[0]
    return c.send([Instruction(GATE, b"", [AccountMeta(c.payer.pubkey(), True, True), AccountMeta(tok, False, False),
                                           AccountMeta(gate, False, True), AccountMeta(oidc.SYSTEM, False, False)])], tag="gate")


def test_a_program_gates_on_a_github_signed_fact():
    c = Chain()
    c.svm.add_program_from_file(GATE, str(FIX / "oidc_gate_test.so"))
    assert c.register(oidc.GITHUB, modulus(signing_key())), c.err
    sha = "5" * 40
    tok = c.gh("oidc-gate:release", file="release.yml", wf_repo="octo/widgets", repository_id=str(REPO), sha=sha)
    assert record(c, tok), c.err
    gate = c.data(Pubkey.find_program_address([b"gate", REPO.to_bytes(8, "little")], GATE)[0])
    assert int.from_bytes(gate[0:8], "little") == REPO and gate[16:56].decode() == sha
    print("\nCU to consume a verified token:", c.cu["gate"][-1])
    assert not record(c, c.gh("knos:pay:1:2", repository_id=str(REPO), sha=sha))                       # another audience
    assert not record(c, c.gh("oidc-gate:release", repository_id=str(REPO), sha=sha, runner_environment="self-hosted"))
    # the same bytes in an account knos-oidc does not own
    real = c.svm.get_account(tok)
    fake = Keypair().pubkey()
    c.svm.set_account(fake, Account(lamports=real.lamports, data=bytes(real.data), owner=GATE, executable=False))
    assert not record(c, fake)
    # a token that was written but never verified
    from _settle import github_claims, sign_jwt
    tid = c.write(sign_jwt(signing_key(), github_claims(aud="oidc-gate:release", repository_id=str(REPO), exp=c.now() + 300, jti="nv")))
    assert not record(c, oidc.token_pda(c.payer.pubkey(), tid))
    # more than an hour past its expiry
    c.warp(300 + oidc.LATE)
    assert not record(c, tok)
