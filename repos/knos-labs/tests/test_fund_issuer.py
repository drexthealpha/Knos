"""0.3.9 in LiteSVM against the built program: FundWithToken (a fund.yml OIDC token funds a github job with minted
test USDC, rate-limited per repository per hour; a prove.yml sha, a wrong audience or a job id that is not the
token's issue are refused), the issuer registry (a GitLab CI token verified by a key scoped to the GitLab issuer; a
GitHub token against the GitLab key is refused) and the program version (in the binary, checked by the client)."""
from __future__ import annotations

import base64
import json

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.system_program import CreateAccountParams, create_account  # noqa: E402

from _jobharness import Escrow, LocalLedger  # noqa: E402

from knos.jobs import market, sol  # noqa: E402

U = 1_000_000
CAP = 100 * U
REPO, REF = "octo/widgets", "refs/heads/main"
KID, GL_KID = "fake-github-kid-1", "fake-gitlab-kid-1"
PROVE_SHA = "0123456789abcdef0123456789abcdef01234567"
FUND_SHA = "fedcba9876543210fedcba9876543210fedcba98"
GL_SHA = "1111111111222222222233333333334444444444"
HEAD = "89abcdef0123456789abcdef0123456789abcdef"
CHECKS = bytes(range(32))
CU: dict = {}


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token(key, kid: str, claims: dict) -> str:
    head = b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": kid}, separators=(",", ":")).encode())
    body = b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{head}.{body}.{b64(key.sign(f'{head}.{body}'.encode(), padding.PKCS1v15(), hashes.SHA256()))}"


def gh_fund(key, repo: str = REPO, issue: int = 7, amount: int = 5 * U, wsha: str = FUND_SHA, aud: str | None = None,
            stake: bool = False) -> str:
    return token(key, KID, {"iss": sol.GH_ISSUER, "aud": aud or sol.fund_audience(issue, amount, CHECKS, stake),
                            "repository": repo, "ref": REF, "sha": HEAD, "job_workflow_sha": wsha,
                            "exp": 4_000_000_000})


def new_mint(e, authority) -> Keypair:
    m = Keypair()
    assert e.send([create_account(CreateAccountParams(
        from_pubkey=e.admin.pubkey(), to_pubkey=m.pubkey(), lamports=e.svm.minimum_balance_for_rent_exemption(82),
        space=82, owner=sol.TOKEN)),
        e._tix([20, 6] + list(bytes(authority)) + [0], [(m.pubkey(), False, True)])], e.admin, [e.admin, m])
    return m


@pytest.fixture(scope="module")
def keys():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048), \
        rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def env(keys):
    gh, gl = keys
    e = Escrow(fee_bps=500)
    a = e.admin
    e.fm = new_mint(e, sol.faucet_pda(e.pid)).pubkey()
    assert e.send([sol.init_faucet_mint(e.pid, a.pubkey(), e.fm, CAP)], a, [a])
    e.fvault = e.token_account(sol.vault_authority(e.pid, e.fm), e.fm)
    assert e.send([sol.add_mint(e.pid, a.pubkey(), e.fm, e.fvault)], a, [a])
    e.payer, _ = e.party()
    e.worker, _ = e.party()
    e.mint_accounts = {(bytes(a.pubkey()), bytes(e.fm)): e.token_account(a.pubkey(), e.fm),
                       (bytes(e.worker.pubkey()), bytes(e.fm)): e.token_account(e.worker.pubkey(), e.fm)}
    e.ledger = LocalLedger(e)
    assert e.send([sol.register_key(e.pid, a.pubkey(), KID, gh.public_key().public_numbers().n)], a, [a])
    assert e.send([sol.register_issuer(e.pid, a.pubkey(), sol.ISSUER_GITLAB, sol.GITLAB_ISSUER, sol.CLAIMS_GITLAB)],
                  a, [a])
    assert e.send([sol.register_key(e.pid, a.pubkey(), GL_KID, gl.public_key().public_numbers().n,
                                    issuer=sol.ISSUER_GITLAB)], a, [a])
    for sha, kind in ((PROVE_SHA, sol.WF_PROVE), (FUND_SHA, sol.WF_FUND), (GL_SHA, sol.WF_PROVE)):
        assert e.send([sol.set_workflow(e.pid, a.pubkey(), sha, kind=kind)], a, [a])
    return e


def fund(env, jwt: str) -> bytes | None:
    try:
        return market.fund_with_token(env.ledger, env.payer, jwt)[0]
    except RuntimeError:
        return None


def test_fund_with_token_creates_the_job_and_mints(env, keys):
    v0 = env.balance(env.fvault)
    jid = fund(env, gh_fund(keys[0], issue=7, amount=5 * U))
    CU["fund"] = env.last_cu
    print(f"\nFundWithToken CU: {CU['fund']}")
    assert jid == sol.fund_job_id(REPO, 7)
    assert CU["fund"] <= 950_000
    j = env.job(jid)
    assert j.state == "open" and j.amount == 5 * U and j.mint == env.fm and j.buyer == env.payer.pubkey()
    assert env.balance(env.fvault) - v0 == 5 * U                       # minted into the faucet mint's vault
    raw = bytes(env.svm.get_account(sol.job_pda(env.pid, jid)).data)
    assert len(raw) == sol.GH_MINT_JOB_LEN and raw[sol.JOB_LEN + 64:sol.JOB_LEN + 96] == CHECKS


def test_a_funded_job_pays_on_a_prove_token(env, keys):
    repo = "octo/paid"
    jid = fund(env, gh_fund(keys[0], repo=repo, issue=1, amount=3 * U))
    assert jid
    w = env.mint_accounts[(bytes(env.worker.pubkey()), bytes(env.fm))]
    w0 = env.balance(w)
    proof = token(keys[0], KID, {"iss": sol.GH_ISSUER, "aud": sol.gh_audience(jid, HEAD, CHECKS, env.worker.pubkey()),
                                 "repository": repo, "ref": REF, "sha": HEAD, "job_workflow_sha": PROVE_SHA,
                                 "exp": 4_000_000_000})
    market.prove_github(env.ledger, env.worker, jid, proof)
    CU["step2"] = env.last_cu
    assert CU["step2"] <= 950_000
    assert env.job(jid) is None and env.balance(w) - w0 == 3 * U - sol.fee_for(3 * U, 500)


def test_fund_rate_limit_per_repo_per_hour(env, keys):
    repo = "octo/rate"
    assert fund(env, gh_fund(keys[0], repo=repo, issue=1))
    assert fund(env, gh_fund(keys[0], repo=repo, issue=2)) is None, "a second funding of the repo inside the hour"
    assert fund(env, gh_fund(keys[0], repo="octo/other-repo", issue=2)), "another repository is not limited"
    env.warp(3601)
    assert fund(env, gh_fund(keys[0], repo=repo, issue=2))


def test_fund_refuses_a_prove_workflow_sha(env, keys):
    assert fund(env, gh_fund(keys[0], repo="octo/wf", wsha=PROVE_SHA)) is None   # kind 0, not fund.yml
    assert fund(env, gh_fund(keys[0], repo="octo/wf", wsha="9" * 40)) is None    # not registered at all
    assert fund(env, gh_fund(keys[0], repo="octo/wf"))


@pytest.mark.parametrize("aud", ["knos:fund:7:5000000:" + "00" * 32,                 # no stake part
                                 "knos:fund:7:5000000:" + "00" * 32 + ":2",          # stake not 0|1
                                 "knos:fund:x:5000000:" + "00" * 32 + ":0",          # issue not a number
                                 "knos:fund:7:5000000:" + "0G" * 32 + ":0",          # checks not hex
                                 "knos:fund:7:" + str(CAP + 1) + ":" + "00" * 32 + ":0",   # over the faucet cap
                                 "knos:fumd:7:5000000:" + "00" * 32 + ":0"])
def test_fund_refuses_a_wrong_audience(env, keys, aud):
    assert fund(env, gh_fund(keys[0], repo="octo/aud", aud=aud)) is None


def test_fund_job_id_must_be_the_tokens_issue(env, keys):
    jwt = gh_fund(keys[0], repo="octo/jid", issue=3)
    raw = jwt.encode()
    bad = sol.fund_job_id("octo/jid", 4)
    p, k = env.pid, sol.gh_key_pda(env.pid, KID)
    for off in range(0, len(raw), 800):
        assert env.send([sol.buffer_write(p, env.payer.pubkey(), bad, len(raw), off, raw[off:off + 800])],
                        env.payer, [env.payer])
    assert env.send([sol.compute_limit(), sol.verify_step1(p, env.payer.pubkey(), bad, k)], env.payer, [env.payer])
    assert not env.send([sol.compute_limit(), sol.fund_with_token(p, env.payer.pubkey(), bad, k, env.fm, env.fvault,
                                                                  FUND_SHA, "octo/jid")], env.payer, [env.payer])


def test_gitlab_token_verifies_with_a_gitlab_scoped_key(env, keys):
    gh, gl = keys
    jid = market.post_github(env.ledger, _relay(env), env.payer, market.Brief("t", "ci"), 0, "group/proj", "main", 600,
                             60, checks_hash=CHECKS)
    claims = {"iss": sol.GITLAB_ISSUER, "aud": sol.gh_audience(jid, HEAD, CHECKS, env.worker.pubkey()),
              "project_path": "group/proj", "ref": "main", "sha": HEAD, "ci_config_sha": GL_SHA, "exp": 4_000_000_000}
    # a GitLab token signed by the GitHub key (kid of the GitLab key): refused; the GitLab key: paid
    assert _prove(env, jid, token(gh, GL_KID, claims)) is False
    assert _prove(env, jid, token(gl, GL_KID, claims)) is True
    assert env.job(jid) is None
    CU["gitlab_step2"] = env.last_cu


def test_issuer_mismatch_is_refused(env, keys):
    gh, gl = keys
    jid = market.post_github(env.ledger, _relay(env), env.payer, market.Brief("t", "ci"), 0, REPO, REF, 600, 60,
                             checks_hash=CHECKS)
    base = {"aud": sol.gh_audience(jid, HEAD, CHECKS, env.worker.pubkey()), "ref": REF, "sha": HEAD,
            "exp": 4_000_000_000}
    # a GitHub-shaped token signed by the GitLab-scoped key: its iss is not that issuer's url
    gh_claims = dict(base, iss=sol.GH_ISSUER, repository=REPO, job_workflow_sha=PROVE_SHA)
    p, k = env.pid, sol.gh_key_pda(env.pid, GL_KID, sol.ISSUER_GITLAB)
    assert not _raw_prove(env, jid, token(gl, GL_KID, gh_claims), k, PROVE_SHA)
    # a GitLab iss against the legacy GitHub key: refused
    gl_claims = dict(base, iss=sol.GITLAB_ISSUER, repository=REPO, job_workflow_sha=PROVE_SHA)
    assert not _raw_prove(env, jid, token(gh, KID, gl_claims), sol.gh_key_pda(p, KID), PROVE_SHA)
    # the real GitHub token still verifies with the GitHub key registered before 0.3.9
    assert _raw_prove(env, jid, token(gh, KID, gh_claims), sol.gh_key_pda(p, KID), PROVE_SHA)


def test_register_issuer_and_scoped_keys_are_admin_only(env, keys):
    rogue = env.keypair()
    assert not env.send([sol.register_issuer(env.pid, rogue.pubkey(), 9, "https://evil.example")], rogue, [rogue])
    assert not env.send([sol.register_issuer(env.pid, env.admin.pubkey(), sol.ISSUER_GITLAB, sol.GITLAB_ISSUER,
                                             sol.CLAIMS_GITLAB)], env.admin, [env.admin]), "exists"
    assert not env.send([sol.register_issuer(env.pid, env.admin.pubkey(), 9, "http://plain.example")],
                        env.admin, [env.admin]), "https only"
    n = keys[1].public_key().public_numbers().n
    assert not env.send([sol.register_key(env.pid, env.admin.pubkey(), "k-unreg", n, issuer=9)],
                        env.admin, [env.admin]), "an unregistered issuer"
    assert not env.send([sol.register_key(env.pid, rogue.pubkey(), "k-rogue", n, issuer=sol.ISSUER_GITLAB)],
                        rogue, [rogue])


def test_program_version_in_the_binary_and_checked(env):
    assert market.assert_program_version(env.ledger) == sol.VERSION == "0.3.9"
    assert env.send([sol.version_ix(env.pid)], env.payer, [env.payer])
    assert any("knos-escrow 0.3.9" in line for line in env.last_logs)

    class Old:
        program, network = env.pid, "devnet"

        def account(self, address):
            return b"\x7fELF" + b"\0" * 64          # a build before 0.3.9: no version string

    with pytest.raises(market.ProgramVersionError, match="devnet runs knos-escrow older than 0.3.9; this client "
                                                          "needs 0.3.9 — upgrade knos or wait for the deploy"):
        market.assert_program_version(Old())

    class Next(Old):
        def account(self, address):
            return b"\x7fELF ... knos-escrow 0.4.0 ..."

    with pytest.raises(market.ProgramVersionError, match="devnet runs knos-escrow 0.4.0; this client needs 0.3.9"):
        market.assert_program_version(Next())


def test_cu_report():
    print(f"\nCU: {CU}")
    assert all(v <= 950_000 for v in CU.values())


# -- helpers -----------------------------------------------------------------------------------------------------------

_RELAY: list = []


def _relay(env):
    if not _RELAY:
        import tempfile
        from pathlib import Path

        from knos.jobs.relay import DirRelay
        _RELAY.append(DirRelay(Path(tempfile.mkdtemp())))
    return _RELAY[0]


def _prove(env, jid: bytes, jwt: str) -> bool:
    try:
        market.prove_github(env.ledger, env.worker, jid, jwt)
        return True
    except (RuntimeError, LookupError):
        return False


def _raw_prove(env, jid: bytes, jwt: str, key, wsha: str) -> bool:
    p, w = env.pid, env.worker
    raw = jwt.encode()
    for off in range(0, len(raw), 800):
        if not env.send([sol.buffer_write(p, w.pubkey(), jid, len(raw), off, raw[off:off + 800])], w, [w]):
            return False
    if not env.send([sol.compute_limit(), sol.verify_step1(p, w.pubkey(), jid, key)], w, [w]):
        return False
    st = env.stake_account(w.pubkey())
    return env.send([sol.compute_limit(), sol.verify_step2(p, w.pubkey(), jid, key, env.vault, st, env.fee_token,
                                                           env.payer.pubkey(), wsha)], w, [w])
