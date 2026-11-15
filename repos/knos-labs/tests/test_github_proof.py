"""0.3.7: a GitHub Actions OIDC token verified on chain by the Solana escrow (programs/knos_escrow/src/github.rs), in
LiteSVM against the built program. The test makes its own RSA-2048 key, registers it as a fake GitHub kid, and signs
its own tokens: a valid proof pays the worker; every tampering, a wrong key, workflow, audience, repository or ref,
a replay and a wrong r2 are refused; with no proof by the deadline the buyer gets the price and the claim's stake.
Prints the compute units of VerifyStep1 and VerifyStep2 (each must be under 1.4M)."""
from __future__ import annotations

import base64
import hashlib
import json

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

from _jobharness import Escrow, LocalLedger  # noqa: E402

from knos.jobs import market, sol  # noqa: E402
from knos.jobs.relay import DirRelay  # noqa: E402

PRICE = 5_000_000
REPO, REF = "octo/widgets", "refs/heads/main"
KID = "fake-github-kid-1"
WF_SHA = "0123456789abcdef0123456789abcdef01234567"
HEAD = "89abcdef0123456789abcdef0123456789abcdef"
PAYOUT: list = []
CU = {}


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def env(key, tmp_path_factory):
    e = Escrow(fee_bps=500)
    e.buyer, e.b_tok = e.party(10 ** 12)
    e.worker, e.w_tok = e.party()
    PAYOUT[:] = [e.worker.pubkey()]
    e.ledger = LocalLedger(e)
    e.relay = DirRelay(tmp_path_factory.mktemp("relay"))
    n = key.public_key().public_numbers().n
    assert e.send([sol.register_key(e.pid, e.admin.pubkey(), KID, n)], e.admin, [e.admin])
    assert e.send([sol.set_workflow(e.pid, e.admin.pubkey(), WF_SHA)], e.admin, [e.admin])
    return e


def jwt(key, job_id: bytes, kid: str = KID, sign_key=None, payout=None, checks: bytes = bytes(32), **over) -> str:
    claims = {"jti": "x", "sub": f"repo:{REPO}:ref:{REF}", "aud": sol.gh_audience(job_id, HEAD, checks, payout or PAYOUT[0]), "sha": HEAD, "ref": REF,
              "repository": REPO, "repository_owner": "octo", "run_id": "1", "event_name": "workflow_dispatch",
              "job_workflow_sha": WF_SHA, "iss": sol.GH_ISSUER,
              "nbf": 1, "iat": 1, "exp": 4_000_000_000}
    claims.update(over)
    head = b64(json.dumps({"typ": "JWT", "alg": "RS256", "x5t": "abc", "kid": kid}, separators=(",", ":")).encode())
    body = b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = (sign_key or key).sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(sig)}"


_N = [0]


def job(env, price: int = PRICE, repo: str = REPO, ref: str = REF, work_s: int = 600, stake_required: bool = True,
        checks: bytes = bytes(32)) -> bytes:
    _N[0] += 1
    jid = market.post_github(env.ledger, env.relay, env.buyer, market.Brief("t", "make CI pass"), price, repo, ref,
                             work_s, 60, checks_hash=checks, stake_required=stake_required)
    assert env.job(jid).state == "open"
    if stake_required:
        assert env.claim(env.worker, jid)
    return jid


def prove(env, jid: bytes, token: str) -> bool:
    try:
        market.prove_github(env.ledger, env.worker, jid, token)
        return True
    except (RuntimeError, LookupError):
        return False


def test_valid_proof_pays_the_worker_and_closes(env, key):
    jid = job(env)
    stake_acct = env.stake_account(env.worker.pubkey())
    w0, f0, b_lam = env.balance(stake_acct), env.balance(env.fee_token), env.lamports(env.buyer.pubkey())
    token = jwt(key, jid).encode()
    pid, w = env.pid, env.worker
    k = sol.gh_key_pda(pid, KID)
    for off in range(0, len(token), 800):
        assert env.send([sol.buffer_write(pid, w.pubkey(), jid, len(token), off, token[off:off + 800])], w, [w])
    assert env.send([sol.compute_limit(), sol.verify_step1(pid, w.pubkey(), jid, k)], w, [w]), env.last_logs[-5:]
    CU["step1"] = env.last_cu
    assert env.send([sol.compute_limit(), sol.verify_step2(pid, w.pubkey(), jid, k, env.vault, stake_acct,
                                                           env.fee_token, env.buyer.pubkey(), WF_SHA)], w, [w]), env.last_logs[-5:]
    CU["step2"] = env.last_cu
    print(f"\nVerifyStep1 CU: {CU['step1']}  VerifyStep2 CU: {CU['step2']}")
    assert CU["step1"] < 1_400_000 and CU["step2"] < 1_400_000
    assert env.job(jid) is None                                          # closed
    assert env.svm.get_account(sol.gh_buffer_pda(pid, jid, w.pubkey())) is None or \
        env.lamports(sol.gh_buffer_pda(pid, jid, w.pubkey())) == 0       # buffer consumed
    fee = sol.fee_for(PRICE, 500)
    assert env.balance(stake_acct) - w0 == PRICE - fee + sol.stake_for(PRICE)   # price - fee, and the stake back
    assert env.balance(env.fee_token) - f0 == fee
    assert env.lamports(env.buyer.pubkey()) > b_lam                      # the job's rent back to the buyer


def test_market_prove_github_and_zero_bounty(env, key):
    jid = job(env, price=0)
    stake_acct = env.stake_account(env.worker.pubkey())
    w0 = env.balance(stake_acct)
    assert env.job(jid).stake == sol.stake_for(0)
    sigs = market.prove_github(env.ledger, env.worker, jid, jwt(key, jid))
    assert len(sigs) == 2
    assert env.job(jid) is None
    assert env.balance(stake_acct) == w0 + sol.stake_for(0)              # the stake back, no money, no fee


def _tamper_payload(t: str) -> str:
    h, p, s = t.split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=="))
    claims["repository"] = REPO
    claims["run_id"] = "2"
    return ".".join([h, b64(json.dumps(claims, separators=(",", ":")).encode()), s])


def _tamper_sig(t: str) -> str:
    h, p, s = t.split(".")
    raw = bytearray(base64.urlsafe_b64decode(s + "=="))
    raw[100] ^= 1
    return ".".join([h, p, b64(bytes(raw))])


@pytest.mark.parametrize("case", ["tampered_payload", "tampered_signature", "unregistered_kid", "other_key_same_kid",
                                  "wrong_workflow", "wrong_aud", "wrong_repo", "wrong_ref", "wrong_issuer",
                                  "expired"])
def test_bad_proofs_are_refused(env, key, case):
    jid = job(env)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048) if case == "other_key_same_kid" else None
    t = {
        "tampered_payload": lambda: _tamper_payload(jwt(key, jid)),
        "tampered_signature": lambda: _tamper_sig(jwt(key, jid)),
        "unregistered_kid": lambda: jwt(key, jid, kid="not-registered"),
        "other_key_same_kid": lambda: jwt(key, jid, sign_key=other),
        "wrong_workflow": lambda: jwt(key, jid, job_workflow_sha="f" * 40),
        "wrong_aud": lambda: jwt(key, jid, aud=sol.gh_audience(bytes(32))),
        "wrong_repo": lambda: jwt(key, jid, repository="octo/other"),
        "wrong_ref": lambda: jwt(key, jid, ref="refs/heads/dev"),
        "wrong_issuer": lambda: jwt(key, jid, iss="https://evil.example"),
        "expired": lambda: jwt(key, jid, exp=env.ledger.now()),          # exp <= the chain clock
    }[case]()
    assert not prove(env, jid, t)
    j = env.job(jid)
    assert j is not None and j.state == "claimed"                        # nothing paid


def test_replay_after_settle_is_refused(env, key):
    jid = job(env)
    t = jwt(key, jid)
    assert prove(env, jid, t)
    assert not prove(env, jid, t)                                        # the job closed: nothing to prove
    # the same token against another job of the same repo/ref: the audience names the first job
    jid2 = job(env)
    assert not prove(env, jid2, t)


def test_wrong_r2_or_n0inv_at_registration_is_refused(env, key):
    n = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_numbers().n
    r2, n0 = sol.rsa_r2_n0inv(n)
    a = env.admin
    assert not env.send([sol.register_key(env.pid, a.pubkey(), "k-bad-r2", n, r2=(r2 + 1) % n)], a, [a])
    assert not env.send([sol.register_key(env.pid, a.pubkey(), "k-bad-n0", n, n0inv=(n0 + 2) % 2 ** 32)], a, [a])
    assert not env.send([sol.register_key(env.pid, env.worker.pubkey(), "k-not-admin", n)], env.worker, [env.worker])
    assert env.send([sol.register_key(env.pid, a.pubkey(), "k-good", n)], a, [a])
    assert not env.send([sol.register_key(env.pid, a.pubkey(), "k-good", n)], a, [a])   # no overwrite


def test_no_proof_by_deadline_refunds_buyer_with_stake(env, key):
    b0 = env.balance(env.b_tok)
    jid = job(env, work_s=30)
    stake = env.job(jid).stake
    assert stake == sol.stake_for(PRICE)
    assert not env.deliver(env.worker, jid)                              # a github job is not settled by delivery
    env.warp(31)
    assert not prove(env, jid, jwt(key, jid))                            # too late
    assert env.settle(env.worker, jid)
    assert env.job(jid) is None
    assert env.balance(env.b_tok) - b0 == stake                          # the price back, plus the stake


def test_workflow_sha_registry_add_remove_admin_only(env, key):
    a, w = env.admin, env.worker
    other = "fedcba9876543210fedcba9876543210fedcba98"
    assert not env.send([sol.set_workflow(env.pid, w.pubkey(), other)], w, [w])            # admin only
    jid = job(env)
    assert not prove(env, jid, jwt(key, jid, job_workflow_sha=other))                      # sha not registered
    assert env.send([sol.set_workflow(env.pid, a.pubkey(), other)], a, [a])
    assert not env.send([sol.set_workflow(env.pid, a.pubkey(), other)], a, [a])            # no double add
    assert env.send([sol.set_workflow(env.pid, a.pubkey(), other, add=False)], a, [a])     # removed again
    assert not prove(env, jid, jwt(key, jid, job_workflow_sha=other))
    assert not prove(env, jid, jwt(key, jid, job_workflow_sha=WF_SHA.upper()))             # lowercase hex only
    assert prove(env, jid, jwt(key, jid))                                                   # the pinned sha: paid


def test_permissionless_relay_pays_the_aud_payout(env, key):
    jid = job(env, stake_required=False)
    assert not env.claim(env.worker, jid)                                # no claim on an unstaked github job
    relayer, _ = env.party()
    payee, _ = env.party()
    pt = env.stake_account(payee.pubkey())
    p0, r0 = env.balance(pt), env.balance(env.stake_account(relayer.pubkey()))
    sigs = market.prove_github(env.ledger, relayer, jid, jwt(key, jid, payout=payee.pubkey()))
    assert len(sigs) == 2 and env.job(jid) is None
    assert env.balance(pt) - p0 == PRICE - sol.fee_for(PRICE, 500)       # the aud's payout is paid, no stake
    assert env.balance(env.stake_account(relayer.pubkey())) == r0        # the relayer only paid gas


def test_aud_head_sha_must_equal_the_sha_claim(env, key):
    jid = job(env)
    assert not prove(env, jid, jwt(key, jid, sha="1" * 40))
    assert not prove(env, jid, jwt(key, jid, aud=sol.gh_audience(jid, "x" * 40, bytes(32), PAYOUT[0]), sha="x" * 40))
    assert prove(env, jid, jwt(key, jid))


def test_checks_hash_is_fixed_at_funding(env, key):
    checks = hashlib.sha256(b"pytest -q").digest()
    jid = job(env, checks=checks)
    assert not prove(env, jid, jwt(key, jid))                            # zero checks hash: not the job's
    assert not prove(env, jid, jwt(key, jid, checks=bytes(31) + b"\1"))
    assert prove(env, jid, jwt(key, jid, checks=checks))


def test_staked_job_pays_only_its_claimer(env, key):
    jid = job(env)                                                       # stake required, claimed by env.worker
    other, _ = env.party()
    assert not prove(env, jid, jwt(key, jid, payout=other.pubkey()))     # payout is not the claimer
    assert not prove(env, jid, jwt(key, jid, aud=f"knos:{jid.hex()}:{HEAD}:{'00' * 32}:notbase58!!"))
    assert prove(env, jid, jwt(key, jid))
