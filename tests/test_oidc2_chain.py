"""The second deployment of knos-oidc in the Solana runtime (LiteSVM, the testkeys build): tokens are verified as in
the first deployment, and a signing key now has a life. GitHub's four keys are the root. Any other key enters on
GitHub's own signature from the pinned rotate workflow run in the attester's repository, waits a day and the
guardian's approval, expires 30 days after it was last attested, and can be revoked for ever. Prints the compute
units of every step."""
from __future__ import annotations

import base64
import json
import random
import re

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _oidc2 import GH, GL, GUARDIAN, Chain2, attest_claims  # noqa: E402
from _settle import FIX, NOW, b64, github_claims, gitlab_claims, jwt_size, modulus, sign_jwt, signing_key, sized_jwt  # noqa: E402

from knos.settle import oidc as first  # noqa: E402
from knos.settle.v2 import oidc  # noqa: E402

DAY = 86_400
REAL_OWNER, REAL_REPOS = oidc.IDS["attest_owner_id"], oidc.IDS["attest_repo_ids"]


@pytest.fixture(scope="module")
def chain():
    c = Chain2()
    assert c.register(GH, modulus(signing_key(2048))), c.err
    assert c.register(GL, modulus(signing_key(4096))), c.err
    return c


def code(c: Chain2) -> int | None:
    m = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(m.group(1)) if m else None


def new_key(bits: int = 2048):
    k = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    return k, modulus(k)


_serial = iter(range(10 ** 9))


def token(key, **over) -> str:
    """A fresh GitHub token signed by `key` (a new jti each time, so each one gets its own account)."""
    return sign_jwt(key, github_claims(jti=f"j{next(_serial)}", **over))


def signed_claims(jwt: str) -> dict:
    body = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


# -- genesis --------------------------------------------------------------------------------------------------------

def test_a_genesis_key_verifies_at_once_and_only_githubs_four_keys_are_genesis():
    c = Chain2()
    seed, sn = signing_key(), modulus(signing_key())
    assert c.register(GH, sn), c.err
    assert c.key(GH, sn) == oidc.Key(state=1, issuer=GH, bits=2048, active_at=NOW, expires_at=NOW + oidc.KEY_TTL,
                                     approved=True, revoked=False, genesis=True)
    claims = github_claims(aud="knos2:pay:987654321:7")
    tok = c.verify(sign_jwt(seed, claims), GH, sn)             # the clock has not moved since the key was registered
    assert tok is not None, c.err
    t = oidc.read_token(c.data(tok))
    assert t.verified and t.issuer == GH and t.exp == NOW + 300 and t.claims() == claims and t.key == oidc.key_pda(GH, sn)
    # GitHub's four keys of 2 Oct 2026 register with no attestation
    github = oidc.jwks_keys(json.loads((FIX / "github_jwks_2026-10-02.json").read_text()))
    assert len(github) == 4
    for _kid, n in github:
        assert c.register(GH, n), c.err
        k = c.key(GH, n)
        assert (k.state, k.genesis, k.approved, k.revoked, k.active_at, k.expires_at) == (1, True, True, False, NOW, NOW + oidc.KEY_TTL)
        assert oidc.key_usable(k, c.now()) == (True, "")
    # GitLab's keys were genesis keys of the first deployment; here they need GitHub's signature like any later key
    gitlab = oidc.jwks_keys(json.loads((FIX / "gitlab_jwks_2026-10-02.json").read_text()))
    assert len(gitlab) == 3
    for _kid, n in gitlab:
        assert not c.send([oidc.register_key_ix(c.payer.pubkey(), GL, n)]) and code(c) == 73
        assert c.key(GL, n) is None
    # a GitHub key is not a GitLab key, and a key nobody vouched for is nobody's
    assert not c.send([oidc.register_key_ix(c.payer.pubkey(), GL, github[0][1])]) and code(c) == 73
    assert not c.send([oidc.register_key_ix(c.payer.pubkey(), GH, new_key()[1])]) and code(c) == 73
    # with an attestation a GitLab key comes in, waits, and then verifies GitLab's tokens (here: the 4096-bit one)
    n = next(n for _kid, n in gitlab if n.bit_length() == 4096)
    assert c.register(GL, n, c.attest(GL, n)), c.err
    k = c.key(GL, n)
    assert (k.bits, k.genesis, k.approved, k.active_at, k.expires_at) == (4096, False, False, NOW + oidc.KEY_DELAY, NOW + oidc.KEY_DELAY + oidc.KEY_TTL)


def test_the_key_account_is_a_40_byte_header_then_the_modulus_and_r2():
    c = Chain2()
    for issuer, key in ((GH, signing_key(2048)), (GL, signing_key(4096))):
        n = modulus(key)
        assert c.send([oidc.register_key_ix(c.payer.pubkey(), issuer, n)]), c.err
        d = c.data(oidc.key_pda(issuer, n))
        limbs = n.bit_length() // 32
        assert len(d) == oidc.K_HDR + 8 * limbs == 40 + 8 * limbs
        bump = Pubkey.find_program_address([b"key", bytes([issuer]), oidc.key_hash(n)], oidc.OIDC_ID)[1]
        assert d[:8] == bytes([0, issuer, limbs, bump, 0, 0, 0, 0])                    # created, not ready: no n0inv yet
        assert int.from_bytes(d[8:16], "little") == NOW and int.from_bytes(d[16:24], "little") == NOW + oidc.KEY_TTL
        assert d[24] == oidc.GENESIS | oidc.APPROVED and d[25:40] == bytes(15)
        assert int.from_bytes(d[40:40 + 4 * limbs], "little") == n and d[40 + 4 * limbs:] == bytes(4 * limbs)
        assert oidc.read_key(d).state == 0 and not oidc.key_usable(oidc.read_key(d), NOW)[0]
        # a token cannot be stepped against a key that is not ready
        tid = c.write(token(key))
        assert not c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(issuer, n), 1)]) and code(c) == 68
        assert c.send([oidc.key_params_ix(c.payer.pubkey(), issuer, n)]), c.err
        created, d = d, c.data(oidc.key_pda(issuer, n))
        n0inv, r2 = oidc.key_params(n)
        assert d[0] == 1 and int.from_bytes(d[4:8], "little") == n0inv and int.from_bytes(d[40 + 4 * limbs:], "little") == int.from_bytes(r2, "big")
        assert d[1:4] == created[1:4] and d[8:40 + 4 * limbs] == created[8:40 + 4 * limbs]     # KeyParams changed nothing else
        # no consumer can take a key account for a verified token: its first byte is never 2
        assert not first.read_token(d) or not first.read_token(d).verified
        # and the token instructions do not reach a key account: nothing writes into one, nothing closes one
        kp, p = oidc.key_pda(issuer, n), c.payer.pubkey()
        write = oidc.write_ixs(p, tid, "x")[0]
        for ix in (Instruction(oidc.OIDC_ID, bytes(write.data), [write.accounts[0], AccountMeta(kp, False, True), write.accounts[2]]),
                   Instruction(oidc.OIDC_ID, b"\x01" + tid + b"\x01", [AccountMeta(p, True, False), AccountMeta(kp, False, True), AccountMeta(kp, False, False)]),
                   Instruction(oidc.OIDC_ID, b"\x02" + tid, [AccountMeta(p, True, True), AccountMeta(kp, False, True)])):
            assert not c.send([ix]) and code(c) == 67
        assert c.data(kp) == d
    assert oidc.read_key(None) is None and oidc.read_key(bytes(39)) is None and oidc.read_key(bytes(552)) is None
    assert oidc.read_key(bytes([1, 0, 64]) + bytes(550)) is None and oidc.read_key(bytes([1, 0, 64]) + bytes(549)).bits == 2048


# -- verification, and what it costs ----------------------------------------------------------------------------------

def test_a_github_token_is_verified_in_two_transactions(chain):
    claims = github_claims(aud="knos2:pay:987654321:7:1234567:" + "a" * 40 + ":" + "c" * 64 + ":0:-")
    jwt = sign_jwt(signing_key(), claims)
    tok = chain.verify(jwt, GH, modulus(signing_key()), tag="verify")
    assert tok is not None, chain.err
    t = oidc.read_token(chain.data(tok))
    assert t.verified and t.issuer == GH and t.exp == NOW + 300 and t.claims() == claims
    assert t.key == oidc.key_pda(GH, modulus(signing_key())) and t.payer == chain.payer.pubkey()
    cu = {k: v[-1] for k, v in chain.cu.items() if k.startswith("verify_2048")}
    print(f"\nCU 2048-bit, {len(jwt)}-byte GitHub token, plan {oidc.step_plan(2048)}:", cu)
    assert len(cu) == 2 and all(v < 1_200_000 for v in cu.values())


def test_a_gitlab_token_under_a_4096_bit_key_is_verified_in_six(chain):
    key, n = signing_key(4096), modulus(signing_key(4096))
    claims = gitlab_claims(aud="knos2:pay:1:2")
    jwt = sign_jwt(key, claims)
    tok = chain.verify(jwt, GL, n, tag="verify")
    assert tok is not None, chain.err
    t = oidc.read_token(chain.data(tok))
    assert t.verified and t.issuer == GL and t.claims() == claims
    cu = [chain.cu[f"verify_4096_step{i + 1}"][-1] for i in range(6)]
    print(f"\nCU 4096-bit, {len(jwt)}-byte GitLab token, plan {oidc.step_plan(4096)}:", cu)
    assert oidc.step_plan(4096) == [2, 3, 3, 3, 4, 1] == first.step_plan(4096) and max(cu) < 1_300_000
    # the same key cannot vouch for GitHub's issuer
    assert chain.verify(sign_jwt(key, github_claims()), GL, n) is None and code(chain) == 72


def test_the_plans_fit_the_longest_token_the_program_takes(chain):
    """Every step must stay under the 1,400,000 compute units a transaction can have, for a token of any size. The
    last step grows with the token (it hashes it, decodes its payload and reads its claims), so the 4096-bit plan
    gives it one squaring. The plan the first deployment's client used to send ended with two and ran out."""
    longest = {}
    for bits, issuer, claims in ((2048, GH, github_claims), (4096, GL, gitlab_claims)):
        key, n = signing_key(bits), modulus(signing_key(bits))
        for size in (3_500, oidc.MAX_JWT):
            jwt = sized_jwt(key, claims(aud=f"knos2:pay:1:{size}", groups_direct=["g"]), size)
            longest[bits] = len(jwt)
            tok = chain.verify(jwt, issuer, n, tag=f"size{size}")
            assert tok is not None, f"{bits}-bit, {len(jwt)} bytes: {chain.err}"
            assert oidc.read_token(chain.data(tok)).claims() == signed_claims(jwt)
            cu = [chain.cu[f"size{size}_{bits}_step{i + 1}"][-1] for i in range(len(oidc.step_plan(bits)))]
            print(f"\nCU {bits}-bit, {len(jwt)}-byte token, plan {oidc.step_plan(bits)}: {cu}")
            assert max(cu) < 1_340_000, cu                  # at least 60,000 compute units to spare in every step
    # the old 4096-bit plan on the longest token: the sixth step runs out
    key, n = signing_key(4096), modulus(signing_key(4096))
    jwt = sized_jwt(key, gitlab_claims(aud="knos2:pay:1:0"), oidc.MAX_JWT)
    assert chain.verify(jwt, GL, n, plan=[2, 3, 3, 3, 3, 2]) is None and "ProgramFailedToComplete" in chain.err
    # claims of the costliest shape we could build (many two-byte pairs that are not ASCII), at the largest size
    base = json.dumps(gitlab_claims(), separators=(",", ":")).encode()[:-1]
    pairs = next(k for k in range(2000, 0, -1) if jwt_size(key, len(base) + 6 * k + 1) <= oidc.MAX_JWT)
    worst = sign_jwt(key, {}, raw_payload=base + b"," + b",".join([b'"\xff":\xff'] * pairs) + b"}")
    assert oidc.MAX_JWT - 8 <= len(worst) <= oidc.MAX_JWT
    assert chain.verify(worst, GL, n, tag="worst") is not None, chain.err
    cu = [chain.cu[f"worst_4096_step{i + 1}"][-1] for i in range(6)]
    print(f"CU 4096-bit, {len(worst)}-byte token of the costliest claims: {cu}")
    # exactly the maximum fits (base64 cannot make the 4096-bit token 8,192 bytes long); one byte more is refused
    # before anything is written
    assert longest == {2048: oidc.MAX_JWT, 4096: oidc.MAX_JWT - 1}
    with pytest.raises(ValueError):
        oidc.write_ixs(chain.payer.pubkey(), b"\0" * 32, "x" * (oidc.MAX_JWT + 1))
    over = Instruction(oidc.OIDC_ID, b"\x00" + bytes(32) + (oidc.MAX_JWT + 1).to_bytes(2, "little") + bytes(2) + b"x",
                       oidc.write_ixs(chain.payer.pubkey(), bytes(32), "x")[0].accounts)
    assert not chain.send([over]) and code(chain) == 64


def test_the_first_deployments_client_drives_this_program_when_given_its_address(chain):
    """Write, Step, Close, RegisterKey and KeyParams are the first deployment's instructions, byte for byte."""
    p, n, tid = chain.payer.pubkey(), modulus(signing_key()), bytes(range(32))
    same = lambda a, b: (bytes(a.data), a.program_id, a.accounts) == (bytes(b.data), b.program_id, b.accounts)  # noqa: E731
    for a, b in zip(oidc.write_ixs(p, tid, "x" * 2000), first.write_ixs(p, tid, "x" * 2000, program=oidc.OIDC_ID)):
        assert same(a, b)
    assert same(oidc.step_ix(p, tid, oidc.key_pda(GH, n), 8), first.step_ix(p, tid, first.key_pda(GH, n, oidc.OIDC_ID), 8, program=oidc.OIDC_ID))
    assert same(oidc.close_ix(p, tid), first.close_ix(p, tid, program=oidc.OIDC_ID))
    assert same(oidc.register_key_ix(p, GH, n), first.register_key_ix(p, GH, n, program=oidc.OIDC_ID))
    assert same(oidc.register_key_ix(p, GH, n, p), first.register_key_ix(p, GH, n, p, program=oidc.OIDC_ID))
    assert same(oidc.key_params_ix(p, GH, n), first.key_params_ix(p, GH, n, program=oidc.OIDC_ID))
    assert oidc.OIDC_ID != first.OIDC_ID and oidc.token_pda(p, tid) != first.token_pda(p, tid)
    # and a whole verification sent with the first client alone
    jwt = token(signing_key(), aud="first-client")
    tid = first.token_id(jwt)
    for ix in first.write_ixs(p, tid, jwt, program=oidc.OIDC_ID):
        assert chain.send([ix]), chain.err
    for sq in first.step_plan(2048):
        assert chain.send([first.step_ix(p, tid, first.key_pda(GH, n, oidc.OIDC_ID), sq, program=oidc.OIDC_ID)]), chain.err
    t = first.read_token(chain.data(first.token_pda(p, tid, oidc.OIDC_ID)))
    assert t.verified and t.claims()["aud"] == "first-client"
    assert chain.send([first.close_ix(p, tid, program=oidc.OIDC_ID)]), chain.err


# -- a key that GitHub's signature admits ---------------------------------------------------------------------------------

@pytest.mark.parametrize("approve_first", [True, False], ids=["approved, then the day passes", "the day passes, then approved"])
def test_an_attested_key_verifies_only_after_its_delay_and_the_guardians_approval(approve_first):
    c = Chain2()
    key, n = new_key()
    refused = lambda: c.verify(token(key), GH, n) is None and code(c) == 76  # noqa: E731
    assert c.register(GH, n, c.attest(GH, n)), c.err
    k = c.key(GH, n)
    assert k == oidc.Key(state=1, issuer=GH, bits=2048, active_at=NOW + oidc.KEY_DELAY, expires_at=NOW + oidc.KEY_DELAY + oidc.KEY_TTL,
                         approved=False, revoked=False, genesis=False)
    assert refused()                                                   # neither
    ok, why = oidc.key_usable(k, c.now())
    assert not ok and "has not approved" in why and "24-hour wait" in why
    if approve_first:
        assert c.approve(GH, n), c.err
        assert c.key(GH, n).approved and refused()                     # approved, the day has not passed
        ok, why = oidc.key_usable(c.key(GH, n), c.now())
        assert not ok and "can be used from" in why
        c.warp(oidc.KEY_DELAY - 1)
        assert refused()                                               # one second short
        c.warp(1)
    else:
        c.warp(oidc.KEY_DELAY)
        assert refused()                                               # the day has passed, not approved
        c.warp(10 * DAY)
        assert refused()                                               # and no amount of waiting replaces the approval
        ok, why = oidc.key_usable(c.key(GH, n), c.now())
        assert not ok and "has not approved" in why and "wait" not in why
        assert c.approve(GH, n), c.err
    assert oidc.key_usable(c.key(GH, n), c.now()) == (True, "")
    jwt = token(key, aud="knos2:pay:1:1")
    tok = c.verify(jwt, GH, n)
    assert tok is not None, c.err
    assert oidc.read_token(c.data(tok)).claims() == signed_claims(jwt)
    # the approval and the wait changed nothing else
    k2 = c.key(GH, n)
    assert (k2.active_at, k2.expires_at, k2.approved, k2.genesis, k2.revoked) == (k.active_at, k.expires_at, True, False, False)


def test_every_condition_of_the_attestation_is_needed_to_register_a_key_and_to_refresh_one():
    c = Chain2()
    signer, sn = signing_key(), modulus(signing_key())
    key, n = new_key()
    have, hn = new_key()                                    # a key that is already registered: the target of Refresh
    assert c.register(GH, hn, c.attest(GH, hn)), c.err
    expires = c.key(GH, hn).expires_at
    c.warp(5 * DAY)                                         # so that a Refresh that worked would show

    reg = lambda tok: c.send([c.register_ix(GH, n, tok)])  # noqa: E731
    ref = lambda tok: c.send([c.refresh_ix(GH, hn, tok)])  # noqa: E731

    def refused(what: str, want: int, **over) -> None:
        for send, target in ((reg, n), (ref, hn)):
            over_t = {k: (v(target) if callable(v) else v) for k, v in over.items()}
            tok = c.attest(GH, target, **over_t)
            assert tok is not None, c.err
            assert not send(tok), f"{what}: accepted"
            assert code(c) == want, f"{what}: {c.err}, wanted {want}"
        assert c.key(GH, n) is None and c.key(GH, hn).expires_at == expires

    assert not reg(None) and code(c) == 73                 # no attestation at all
    wrong = {
        "another repository of the same owner": dict(repository_id="987654322"),
        "another owner": dict(repository_owner_id="424243"),
        "the attester's account with the test repository": dict(repository_owner_id=str(REAL_OWNER)),
        "the test account with the attester's repository": dict(repository_id=str(REAL_REPOS[0])),
        "an id that only starts like the right one": dict(repository_id="9876543210"),
        "a push": dict(event_name="push"),
        "a pull request": dict(event_name="pull_request_target"),
        "a comment": dict(event_name="issue_comment"),
        "another workflow run that finished": dict(event_name="workflow_run"),
        "another workflow file": dict(job_workflow_ref="drexthealpha/knos-oidc-rotate/.github/workflows/other.yml@refs/heads/main"),
        "the same file name in another repository": dict(job_workflow_ref="evil/knos-oidc-rotate/.github/workflows/rotate.yml@refs/heads/main"),
        "another commit of the workflow": dict(job_workflow_sha="2" * 40),
        "the real commit's first 39 characters": dict(job_workflow_sha=oidc.IDS["rotate_sha"][:39]),
        "a self-hosted runner": dict(runner_environment="self-hosted"),
        "an audience naming another issuer": dict(aud=lambda t: oidc.rotate_audience(GL, t)),
        "an audience naming another key": dict(aud=lambda t: oidc.rotate_audience(GH, t + 2)),
        "an audience with the hash in capitals": dict(aud=lambda t: oidc.rotate_audience(GH, t).upper().replace("KNOS-OIDC:KEY", "knos-oidc:key")),
        "an audience for something else": dict(aud="knos2:bind:11111111111111111111111111111111"),
    }
    for what, over in wrong.items():
        refused(what, 74, **over)
    # a claim that is not there at all, or is not text or a number
    for name in ("repository_id", "repository_owner_id", "event_name", "job_workflow_ref", "job_workflow_sha", "runner_environment"):
        for send, target in ((reg, n), (ref, hn)):
            claims = attest_claims(GH, target, jti=f"m{next(_serial)}", iat=c.now(), exp=c.now() + 300)
            del claims[name]
            assert not send(c.verify(sign_jwt(signer, claims), GH, sn)) and code(c) == 63, f"no {name}: {c.err}"
    refused("an owner id that is not a number", 63, repository_owner_id="drexthealpha")
    refused("an event that is a list", 63, event_name=["schedule"])
    # an attestation GitHub did not sign: a GitLab token with the same claims, verified under a GitLab key
    gl = signing_key(4096)
    assert c.register(GL, modulus(gl)), c.err
    for send, target in ((reg, n), (ref, hn)):
        tok = c.verify(sign_jwt(gl, attest_claims(GH, target, iss=oidc.ISSUERS[GL], exp=c.now() + 300)), GL, modulus(gl))
        assert tok is not None and not send(tok) and code(c) == 74
    # an attestation more than an hour past its expiry
    for send, target in ((reg, n), (ref, hn)):
        tok = c.attest(GH, target)
        c.warp(300 + oidc.LATE)
        assert not send(tok) and code(c) == 75
        c.warp(-(300 + oidc.LATE))
    # an account that is not a verified token: one still being written, a key account, the payer, nothing
    tid = c.write(sign_jwt(signer, attest_claims(GH, n, jti="unverified")))
    for send in (reg, ref):
        for not_a_token in (oidc.token_pda(c.payer.pubkey(), tid), oidc.key_pda(GL, modulus(gl)), oidc.key_pda(GH, sn), c.payer.pubkey(), Keypair().pubkey()):
            assert not send(not_a_token) and code(c) == 73
    assert c.key(GH, n) is None and c.key(GH, hn).expires_at == expires
    # the real thing: a scheduled run, and a run started by hand; relayed 59 minutes after the token's own life ended
    tok = c.attest(GH, n)
    c.warp(300 + oidc.LATE - 60)
    assert reg(tok), c.err
    assert c.key(GH, n).active_at == c.now() + oidc.KEY_DELAY          # the day counts from the registration
    c.warp(-(300 + oidc.LATE - 60))
    assert ref(c.attest(GH, hn, event_name="workflow_dispatch")), c.err
    assert c.key(GH, hn).expires_at == c.now() + oidc.KEY_TTL > expires
    # the attester's real account and both of its repositories are in this build too
    for repo in REAL_REPOS:
        other, on = new_key()
        tok = c.attest(GH, on, repository_owner_id=str(REAL_OWNER), repository_id=str(repo), repository="drexthealpha/Knos")
        assert c.send([c.register_ix(GH, on, tok)]), c.err
    assert REAL_OWNER == 142920951 and REAL_REPOS == [1353152983, 1401432540]
    # the same key cannot be registered twice
    assert not reg(c.attest(GH, n)) and code(c) == 67


def test_an_attestation_counts_only_while_the_key_that_verified_it_is_usable():
    """RegisterKey and Refresh take the key account that verified the attestation and ask of it what Step asks. A
    VERIFIED token account outlives its key by up to 25 hours (a day of `exp` ahead, an hour of lateness); an
    attestation does not outlive it by a second."""
    c = Chain2()
    sn = modulus(signing_key())
    assert c.register(GH, sn), c.err
    second, n2 = new_key()                                  # a second key of GitHub's
    assert c.admit(GH, n2), c.err
    target, p = new_key()[1], c.payer.pubkey()
    c.warp(10 * DAY)
    assert c.refresh(GH, sn), c.err                         # the seed key now lives longer than the second
    c.warp(c.key(GH, n2).expires_at - c.now() - 1)          # the second key's last second
    far = c.now() + DAY                                     # the furthest expiry Step lets through
    reg_tok, ref_tok, seed_tok = (c.attest(GH, n, by=second, exp=far) for n in (target, n2, sn))
    assert reg_tok and ref_tok and seed_tok, c.err
    # the key account is the one the token account names, and no other: a usable key that did not verify it, the
    # token itself, a wallet, nothing
    for wrong in (oidc.key_pda(GH, sn), reg_tok, p, Keypair().pubkey()):
        assert not c.send([oidc.register_key_ix(p, GH, target, reg_tok, wrong)]) and code(c) == 68, c.err
        assert not c.send([oidc.refresh_ix(p, GH, sn, seed_tok, wrong)]) and code(c) == 68, c.err
    assert not c.send([oidc.register_key_ix(p, GH, target, reg_tok)]) and "NotEnoughAccountKeys" in c.err
    assert not c.send([oidc.refresh_ix(p, GH, sn, seed_tok)]) and "NotEnoughAccountKeys" in c.err
    before = c.key(GH, sn)
    uses = lambda: (c.register_ix(GH, target, reg_tok), c.refresh_ix(GH, n2, ref_tok), c.refresh_ix(GH, sn, seed_tok))  # noqa: E731
    c.warp(1)                                               # the second key has expired; its tokens are fresh for a day
    assert all(oidc.read_token(c.data(t)).verified and c.now() < oidc.read_token(c.data(t)).exp for t in (reg_tok, ref_tok, seed_tok))
    for ix in uses():
        assert not c.send([ix]) and code(c) == 77, c.err    # not even to refresh itself
    assert c.key(GH, target) is None and c.key(GH, sn) == before and not oidc.key_usable(c.key(GH, n2), c.now())[0]
    # GitHub names the expired key again in a token verified under a key that is live: that refreshes it
    assert c.refresh(GH, n2), c.err
    assert c.send([c.refresh_ix(GH, sn, seed_tok)]), c.err   # and what it verified counts again, for its own time
    assert c.key(GH, sn).expires_at == c.now() + oidc.KEY_TTL > before.expires_at
    # revoked: nothing it verified attests anything again
    before = c.key(GH, sn)
    assert c.revoke(GH, n2), c.err
    for warp in (0, DAY + oidc.LATE):
        c.warp(warp)
        for ix in uses():
            assert not c.send([ix]) and code(c) == 78, c.err
    assert c.key(GH, target) is None and c.key(GH, sn) == before


def test_anyone_refreshes_a_key_from_a_repository_of_his_own_and_nobody_registers_one_that_way():
    """The rotate workflow at its pinned commit, started by hand in a repository owned by the person who started it
    (repository_owner_id == actor_id: a personal account, whose hosted runners are GitHub's), counts for Refresh.
    So the keys stay alive without the attester's schedule. It never counts for RegisterKey."""
    c = Chain2()
    sn = modulus(signing_key())
    assert c.register(GH, sn), c.err
    have, hn = new_key()
    assert c.admit(GH, hn), c.err
    new = new_key()[1]
    c.warp(5 * DAY)
    mine = dict(event_name="workflow_dispatch", repository_owner_id="555000", actor_id="555000", repository_id="777000111",
                repository="someone/rotate-knos", repository_owner="someone", actor="someone")
    expires = c.key(GH, hn).expires_at
    refused = {
        "the schedule": dict(event_name="schedule"),
        "a push": dict(event_name="push"),
        "started by someone who does not own the repository": dict(actor_id="555001"),
        "an organisation's repository": dict(repository_owner_id="9000001"),
        "no actor": dict(actor_id=None),
        "an actor that is not a number": dict(actor_id="someone"),
        "a self-hosted runner": dict(runner_environment="self-hosted"),
        "another commit of the workflow": dict(job_workflow_sha="2" * 40),
        "a copy of the workflow in his repository": dict(job_workflow_ref="someone/rotate-knos/.github/workflows/rotate.yml@refs/heads/main"),
        "another key's audience": dict(aud=oidc.rotate_audience(GH, new)),
    }
    for what, over in refused.items():
        claims = {k: v for k, v in {**mine, **over}.items() if v is not None}
        tok = c.attest(GH, hn, **claims) if "actor_id" in claims else c.verify(
            sign_jwt(signing_key(), {k: v for k, v in attest_claims(GH, hn, iat=c.now(), exp=c.now() + 300, jti="noactor", **claims).items() if k != "actor_id"}), GH, sn)
        assert tok is not None, c.err
        assert not c.send([c.refresh_ix(GH, hn, tok)]) and code(c) == 74, f"{what}: {c.err}"
    assert c.key(GH, hn).expires_at == expires
    stranger = c.fund()
    tok = c.attest(GH, hn, **mine)
    assert c.refresh(GH, hn, tok, payer=stranger), c.err
    assert c.key(GH, hn).expires_at == c.now() + oidc.KEY_TTL > expires
    # the same run names a key the chain does not have: that is the attester's to say, and the guardian's to approve
    tok = c.attest(GH, new, **mine)
    assert tok is not None and not c.send([c.register_ix(GH, new, tok)]) and code(c) == 74
    assert c.key(GH, new) is None
    assert c.register(GH, new, c.attest(GH, new)), c.err                # the attester's run does register it
    assert c.refresh(GH, new, c.attest(GH, new, **mine)), c.err         # and then anyone keeps it alive


# -- any RS256 issuer --------------------------------------------------------------------------------------------------

# two issuers that are neither GitHub nor GitLab: a CI service, and a company's GitHub Enterprise Server
ISSUER_URLS = {2048: "https://oidc.ci.example.dev", 4096: "https://ghe.example.org/_services/token"}


def issuer_claims(url: str, c: Chain2, **over) -> dict:
    """What such an issuer signs: its own `iss`, its own claim names, and the three every OIDC token has."""
    claims = {"iss": url, "sub": "org/acme/project/widgets/pipeline/release", "aud": "acme:release:1.2.0", "iat": c.now(), "exp": c.now() + 300,
              "jti": f"i{next(_serial)}", "project_id": "8841", "pipeline": "release"}
    claims.update(over)
    return claims


@pytest.mark.parametrize("bits", [2048, 4096])
def test_any_rs256_issuer_is_admitted_on_githubs_signature_and_step_checks_its_iss(bits):
    c = Chain2()
    url, sn = ISSUER_URLS[bits], modulus(signing_key())
    key, n = new_key(bits)
    assert c.register(GH, sn), c.err
    ih = oidc.issuer_hash(url)
    assert oidc.rotate_audience(url, n) == f"knos-oidc:ikey:{ih.hex()}:{oidc.key_hash(n).hex()}"
    # what does not admit it: the audience of a numbered issuer's key, another issuer's, another key's, anyone's run,
    # an attestation by a GitLab key, and RegisterKey (the two numbered issuers only)
    other_url, other_n = "https://oidc.ci.example.com", new_key()[1]
    anyone = dict(event_name="workflow_dispatch", repository_owner_id="555000", actor_id="555000", repository_id="777000111")
    for what, tok in {"a numbered key's audience": c.attest(GH, n), "another issuer's": c.attest(other_url, n), "another key's": c.attest(url, other_n),
                      "anyone's run": c.attest(url, n, **anyone), "a push": c.attest(url, n, event_name="push")}.items():
        assert tok is not None and not c.send([c.register_ix(url, n, tok)]) and code(c) == 74, f"{what}: {c.err}"
    tok = c.attest(url, n)
    for issuer in (GH, GL):
        assert not c.send([c.register_ix(issuer, n, tok)]) and code(c) == 74
    assert not c.send([Instruction(oidc.OIDC_ID, b"\x03\x02" + oidc.modulus_bytes(n), c.register_ix(GH, n, tok).accounts)]) and code(c) == 72
    # an issuer is an https URL as it stands in `iss`: nothing else has an account
    for bad in ("http://oidc.ci.example.dev", "https://", "oidc.ci.example.dev/https://", 'https://a"b', "https://a b", "https://a\\b", "https://" + "a" * 193):
        u = bad.encode()
        ix = c.register_ix(url, n, tok)
        assert not c.send([Instruction(oidc.OIDC_ID, b"\x08" + bytes([len(u)]) + u + oidc.modulus_bytes(n), ix.accounts)]) and code(c) == 72, bad
    # the accounts are the ones the URL and the modulus derive
    ix = c.register_ix(url, n, tok)
    swap = lambda at, meta: Instruction(ix.program_id, bytes(ix.data), ix.accounts[:at] + [meta] + ix.accounts[at + 1:])  # noqa: E731
    for at, key_ in ((1, oidc.key_pda(other_url, n)), (1, oidc.key_pda(url, other_n)), (1, oidc.key_pda(GH, n)), (2, oidc.iss_pda(other_url)),
                     (2, oidc.key_pda(url, n)), (3, oidc.OIDC_ID)):
        assert not c.send([swap(at, AccountMeta(key_, False, at < 3))]) and code(c) == 67, (at, c.err)
    assert c.key(url, n) is None and c.data(oidc.iss_pda(url)) is None
    # GitHub's signature names it: registered, with the issuer's URL on chain beside it
    assert c.register(url, n, tok), c.err
    k = c.key(url, n)
    assert k == oidc.Key(state=1, issuer=oidc.OTHER, bits=bits, active_at=c.now() + oidc.KEY_DELAY, expires_at=c.now() + oidc.KEY_DELAY + oidc.KEY_TTL,
                         approved=False, revoked=False, genesis=False, issuer_hash=ih)
    d = c.data(oidc.key_pda(url, n))
    assert len(d) == oidc.K_HDR + 8 * (bits // 32) + oidc.KEY_TAIL and d[-64:] == ih + bytes(32)
    iss = c.data(oidc.iss_pda(url))
    assert oidc.read_iss(iss) == url and iss[0] == 3 and iss[2:4] == bytes([0, len(url)])
    assert not c.send([c.register_ix(url, n, c.attest(url, n))]) and code(c) == 67          # once
    # the same day of waiting and the same approval as any attested key
    jwt = sign_jwt(key, issuer_claims(url, c))
    assert c.verify(jwt, url, n) is None and code(c) == 76
    c.travel(oidc.KEY_DELAY)
    assert c.verify(jwt, url, n) is None and code(c) == 76
    assert c.approve(url, n), c.err
    claims = issuer_claims(url, c)
    tok = c.verify(sign_jwt(key, claims), url, n, tag="issuer")
    assert tok is not None, c.err
    print(f"\nCU Step under a {bits}-bit key of another issuer:", [c.cu[f"issuer_{bits}_step{i + 1}"][-1] for i in range(len(oidc.step_plan(bits)))])
    t = oidc.read_token(c.data(tok))
    assert t.verified and t.claims() == claims and t.key == oidc.key_pda(url, n)
    # the token account says OTHER and which issuer: it is never GitHub's or GitLab's number
    assert t.issuer == oidc.OTHER and oidc.token_issuer(c.data(tok)) == (ih, None)
    gh_tok = c.gh("knos2:bind:x")
    assert oidc.token_issuer(c.data(gh_tok)) is None and oidc.read_token(c.data(gh_tok)).issuer == GH
    # `iss` must be the URL the key was admitted for: this key signs for no other issuer
    for iss_claim in (other_url, oidc.ISSUERS[GH], oidc.ISSUERS[GL], url + "/", url.upper(), ""):
        assert c.verify(sign_jwt(key, issuer_claims(url, c, iss=iss_claim)), url, n) is None and code(c) == 72, iss_claim
    claims = issuer_claims(url, c)
    del claims["iss"]
    assert c.verify(sign_jwt(key, claims), url, n) is None and code(c) == 63
    # an issuer that writes its slashes escaped is the same issuer
    claims = issuer_claims(url, c)
    raw = json.dumps(claims, separators=(",", ":")).replace("/", "\\/").encode()
    assert c.verify(sign_jwt(key, claims, raw_payload=raw), url, n) is not None, c.err
    # as an attestation such a token is worth nothing: only GitHub's own keys attest
    forged = c.verify(sign_jwt(key, {**attest_claims(GH, other_n, iat=c.now(), exp=c.now() + 300, jti="forged"), "iss": url}), url, n)
    assert forged is not None and not c.send([c.register_ix(GH, other_n, forged)]) and code(c) == 74
    assert not c.send([c.refresh_ix(GH, sn, forged)]) and code(c) == 74
    # a second key of the same issuer finds the issuer's account there
    key2, n2 = new_key()
    assert c.register(url, n2, c.attest(url, n2)), c.err
    assert c.data(oidc.iss_pda(url)) == iss
    # expiry and Refresh: with the issuer key's own audience, from the attester or from anyone's run
    c.warp(oidc.KEY_TTL)
    assert c.verify(sign_jwt(key, issuer_claims(url, c)), url, n) is None and code(c) == 77
    assert c.refresh(GH, sn) is False and code(c) == 77                  # GitHub's key expired with it: this chain is dead
    c2 = Chain2()
    assert c2.register(GH, sn) and c2.register(url, n, c2.attest(url, n)) and c2.approve(url, n), c2.err
    c2.travel(oidc.KEY_DELAY + 5 * DAY)
    before = c2.key(url, n).expires_at
    c2.warp(DAY)
    for wrong in (c2.attest(GH, n), c2.attest(other_url, n), c2.attest(url, n2)):
        assert not c2.send([c2.refresh_ix(url, n, wrong)]) and code(c2) == 74
    assert c2.send([c2.refresh_ix(url, n, c2.attest(url, n, **anyone))]), c2.err
    assert c2.key(url, n).expires_at == c2.now() + oidc.KEY_TTL == before + DAY
    assert c2.verify(sign_jwt(key, issuer_claims(url, c2)), url, n) is not None, c2.err
    # revocation, for ever
    assert not c2.revoke(url, n, guardian=c2.fund()) and code(c2) == 79
    assert c2.revoke(url, n), c2.err
    assert c2.verify(sign_jwt(key, issuer_claims(url, c2)), url, n) is None and code(c2) == 78
    assert not c2.send([c2.refresh_ix(url, n, c2.attest(url, n))]) and code(c2) == 78


# -- private keys ------------------------------------------------------------------------------------------------------

def test_a_private_key_is_its_registrants_word_and_is_marked_so_in_every_token_it_verifies():
    c = Chain2()
    sn = modulus(signing_key())
    assert c.register(GH, sn), c.err
    company, url = c.fund(), "https://ghe.acme.example/_services/token"
    key, n = new_key()
    who, ih = company.pubkey(), oidc.issuer_hash(url)
    kp = oidc.key_pda(url, n, registrant=who)
    assert kp not in (oidc.key_pda(url, n), oidc.key_pda(url, n, registrant=c.payer.pubkey()))
    # the registrant signs and pays; the address is derived from him, the URL and the modulus
    ix = oidc.register_private_key_ix(who, url, n)
    unsigned = Instruction(ix.program_id, bytes(ix.data), [AccountMeta(who, False, True), *ix.accounts[1:]])
    assert not c.send([unsigned]) and code(c) == 67
    for at, other in ((1, oidc.key_pda(url, n)), (1, oidc.key_pda(url, n, registrant=c.payer.pubkey())), (2, oidc.OIDC_ID)):
        swapped = Instruction(ix.program_id, bytes(ix.data), ix.accounts[:at] + [AccountMeta(other, False, at == 1)] + ix.accounts[at + 1:])
        assert not c.send([swapped], company) and code(c) == 67
    assert not c.send([Instruction(ix.program_id, b"\x09" + bytes([4]) + b"ftp:" + oidc.modulus_bytes(n), ix.accounts)], company) and code(c) == 72
    assert c.register_private(company, url, n), c.err
    k = oidc.read_key(c.data(kp))
    assert k == oidc.Key(state=1, issuer=oidc.PRIVATE, bits=2048, active_at=c.now(), expires_at=c.now() + oidc.KEY_TTL, approved=False, revoked=False,
                         genesis=False, issuer_hash=ih, private=True, registrant=who)
    assert c.data(kp)[24] == oidc.PRIVATE_FLAG and c.data(kp)[-64:] == ih + bytes(who)
    assert oidc.key_usable(k, c.now()) == (True, "")                    # at once: nobody's approval is asked, or given
    assert not c.approve(url, n) and not c.send([Instruction(oidc.OIDC_ID, b"\x06", [AccountMeta(GUARDIAN.pubkey(), True, False), AccountMeta(kp, False, True)])],
                                                signers=[GUARDIAN]) and code(c) == 68
    claims = issuer_claims(url, c)
    tok = c.verify(sign_jwt(key, claims), url, n, registrant=who, tag="private")
    assert tok is not None, c.err
    t = oidc.read_token(c.data(tok))
    assert t.verified and t.claims() == claims and t.key == kp
    # the token account says PRIVATE and whose word it is
    assert t.issuer == oidc.PRIVATE and oidc.token_issuer(c.data(tok)) == (ih, who)
    assert c.verify(sign_jwt(key, issuer_claims(url, c, iss="https://ghe.other.example/_services/token")), url, n, registrant=who) is None and code(c) == 72

    # A thief registers his own key as a private key "of GitHub" and signs whatever GitHub would sign.
    thief, github = c.fund(), oidc.ISSUERS[GH]
    tk, tn = new_key()
    assert c.register_private(thief, github, tn), c.err
    assert c.key(GH, tn) is None and c.key(github, tn) is None          # it is nobody's key but his
    target = new_key()[1]
    forged = c.verify(sign_jwt(tk, attest_claims(GH, target, iat=c.now(), exp=c.now() + 300, jti="thief-reg")), github, tn, registrant=thief.pubkey())
    keep = c.verify(sign_jwt(tk, attest_claims(GH, sn, iat=c.now(), exp=c.now() + 300, jti="thief-ref")), github, tn, registrant=thief.pubkey())
    pay = c.verify(sign_jwt(tk, github_claims(aud="knos2:pay:987654321:7:1234567:" + "a" * 40 + ":" + "c" * 64 + ":0:-", iat=c.now(), exp=c.now() + 300)),
                   github, tn, registrant=thief.pubkey())
    assert forged and keep and pay, c.err
    for account in (forged, keep, pay):
        t = oidc.read_token(c.data(account))
        # every claim reads as GitHub's, the signature verified, and the account is VERIFIED...
        assert t.verified and t.claims()["iss"] == github
        # ...and it is marked: not GitHub's number, and the thief's own address is in it
        assert t.issuer == oidc.PRIVATE != GH and oidc.token_issuer(c.data(account)) == (oidc.issuer_hash(github), thief.pubkey())
    # the verifier itself takes no attestation from it: no key is registered and none is refreshed
    before = c.key(GH, sn)
    c.warp(DAY)
    assert not c.send([c.register_ix(GH, target, forged)]) and code(c) == 74
    assert not c.send([c.register_ix(github, target, forged)]) and code(c) == 74
    assert not c.send([c.refresh_ix(GH, sn, keep)]) and code(c) == 74
    assert c.key(GH, target) is None and c.key(github, target) is None and c.key(GH, sn) == before
    # nor with a real GitHub key account beside it, nor with a real attestation beside the private key
    real = c.attest(GH, target)
    p = c.payer.pubkey()
    assert not c.send([oidc.register_key_ix(p, GH, target, forged, oidc.key_pda(GH, sn))]) and code(c) == 68
    assert not c.send([oidc.register_key_ix(p, GH, target, real, oidc.key_pda(github, tn, registrant=thief.pubkey()))]) and code(c) == 68
    # so the one reader it fools is a consumer that reads the claims and asks neither the issuer's number nor the flag
    forgetful = lambda d: oidc.read_token(d).verified and oidc.read_token(d).claims()["iss"] == github  # noqa: E731
    careful = lambda d: forgetful(d) and oidc.read_token(d).issuer == GH and oidc.token_issuer(d) is None  # noqa: E731
    real_pay = c.gh("knos2:pay:1:1")
    assert forgetful(c.data(pay)) and not careful(c.data(pay)) and careful(c.data(real_pay))

    # renewing: the same wallet sends it again; another wallet's signature makes another wallet's key
    c.warp(10 * DAY)
    assert c.send([oidc.register_private_key_ix(who, url, n)], company), c.err
    assert oidc.read_key(c.data(kp)).expires_at == c.now() + oidc.KEY_TTL and oidc.read_key(c.data(kp)).active_at == k.active_at
    assert c.send([oidc.register_private_key_ix(thief.pubkey(), url, n)], thief), c.err
    assert oidc.read_key(c.data(oidc.key_pda(url, n, registrant=thief.pubkey()))).registrant == thief.pubkey() and oidc.read_key(c.data(kp)).registrant == who
    # no attestation refreshes it, GitHub's included
    assert not c.send([oidc.refresh_ix(p, url, n, real, oidc.key_pda(GH, sn))]) and code(c) == 68          # the attested issuer's key: not there
    r = oidc.refresh_ix(p, url, n, real, oidc.key_pda(GH, sn))
    assert not c.send([Instruction(r.program_id, bytes(r.data), [r.accounts[0], AccountMeta(kp, False, True), *r.accounts[2:]])]) and code(c) == 72
    # it expires like any key
    c.warp(oidc.KEY_TTL)
    assert c.verify(sign_jwt(key, issuer_claims(url, c)), url, n, registrant=who) is None and code(c) == 77
    assert c.send([oidc.register_private_key_ix(who, url, n)], company), c.err
    assert c.verify(sign_jwt(key, issuer_claims(url, c)), url, n, registrant=who) is not None, c.err
    # its registrant ends it, or the guardian does; nobody else; and then it is over
    assert not c.send([oidc.revoke_ix(thief.pubkey(), url, n, registrant=who)], thief) and code(c) == 79
    assert not c.send([oidc.revoke_ix(who, GH, sn)], company) and code(c) == 79         # a registrant revokes no key but his own
    assert c.send([oidc.revoke_ix(who, url, n, registrant=who)], company), c.err
    assert oidc.read_key(c.data(kp)).revoked
    assert c.verify(sign_jwt(key, issuer_claims(url, c)), url, n, registrant=who) is None and code(c) == 78
    assert not c.send([oidc.register_private_key_ix(who, url, n)], company) and code(c) == 78
    assert c.send([oidc.revoke_ix(GUARDIAN.pubkey(), github, tn, registrant=thief.pubkey())], signers=[GUARDIAN]), c.err
    print("\nCU Step under a private 2048-bit key:", [c.cu[f"private_2048_step{i + 1}"][-1] for i in range(2)])


# -- expiry ---------------------------------------------------------------------------------------------------------------

def test_refresh_moves_the_expiry_to_thirty_days_from_now_and_never_earlier():
    c = Chain2()
    sn = modulus(signing_key())
    assert c.register(GH, sn), c.err
    assert c.key(GH, sn).expires_at == NOW + oidc.KEY_TTL == NOW + 30 * DAY
    c.warp(10 * DAY)
    anyone = c.fund()
    tok = c.attest(GH, sn)
    assert c.refresh(GH, sn, tok, payer=anyone), c.err              # anyone may send it
    assert c.key(GH, sn).expires_at == c.now() + oidc.KEY_TTL == NOW + 40 * DAY
    print("\nCU Refresh:", c.cu["refresh"][-1])
    # the same attestation again, 20 minutes later: the expiry follows the clock, not the sender
    c.warp(1200)
    assert c.refresh(GH, sn, tok) and c.key(GH, sn).expires_at == NOW + 40 * DAY + 1200
    c.warp(-1200)
    assert c.refresh(GH, sn, c.attest(GH, sn)) and c.key(GH, sn).expires_at == NOW + 40 * DAY + 1200      # never earlier
    # a key still waiting has an expiry further away than now + 30 days: Refresh leaves it where it is
    key, n = new_key()
    assert c.register(GH, n, c.attest(GH, n)), c.err
    before = c.key(GH, n)
    assert before.expires_at == c.now() + oidc.KEY_DELAY + oidc.KEY_TTL
    assert c.refresh(GH, n), c.err
    assert c.key(GH, n) == before                                   # no earlier expiry, no approval, no shorter wait
    c.warp(DAY + 3600)
    assert c.refresh(GH, n) and c.key(GH, n).expires_at == before.expires_at + 3600
    assert c.key(GH, n).active_at == before.active_at and not c.key(GH, n).approved
    # Refresh takes no data, needs a signer, and works on key accounts only
    ix = c.refresh_ix(GH, n, c.attest(GH, n))
    assert not c.send([Instruction(oidc.OIDC_ID, b"\x05\x00", ix.accounts)]) and "InvalidInstructionData" in c.err
    unsigned = Instruction(oidc.OIDC_ID, b"\x05", [AccountMeta(anyone.pubkey(), False, False), *ix.accounts[1:]])
    assert not c.send([unsigned]) and code(c) == 67
    missing = new_key()[1]
    assert not c.send([c.refresh_ix(GH, missing, c.attest(GH, missing))]) and code(c) == 68


def test_a_key_past_its_expiry_verifies_nothing_until_github_names_it_again():
    c = Chain2()
    seed, sn = signing_key(), modulus(signing_key())
    gl, gn = signing_key(4096), modulus(signing_key(4096))
    assert c.register(GH, sn) and c.register(GL, gn), c.err
    c.warp(oidc.KEY_TTL - DAY)
    assert c.refresh(GH, sn), c.err                                    # GitHub's key is attested again on day 29
    # a verification under the GitLab key, begun one second before its expiry
    c.warp(DAY - 1)
    assert c.verify(sign_jwt(gl, gitlab_claims(jti="last")), GL, gn) is not None, c.err
    half = sign_jwt(gl, gitlab_claims(jti="half"))
    tid = c.write(half)
    assert c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(GL, gn), 2)]), c.err
    c.warp(1)                                                          # now == expires_at
    assert c.now() == c.key(GL, gn).expires_at
    assert c.verify(sign_jwt(gl, gitlab_claims(jti="late")), GL, gn) is None and code(c) == 77
    assert not c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(GL, gn), 3)]) and code(c) == 77   # nor is a begun one finished
    ok, why = oidc.key_usable(c.key(GL, gn), c.now())
    assert not ok and "expired" in why and "Refresh" in why
    assert c.verify(token(seed), GH, sn) is not None, c.err            # the refreshed key goes on
    # a genesis key cannot be registered a second time to get a new life
    assert not c.send([oidc.register_key_ix(c.payer.pubkey(), GL, gn)]) and code(c) == 67
    # the guardian cannot bring it back either: approving changes no time
    assert c.approve(GL, gn) and c.verify(sign_jwt(gl, gitlab_claims(jti="late2")), GL, gn) is None and code(c) == 77
    # GitHub's signature does
    c.warp(3 * DAY)
    assert c.refresh(GL, gn), c.err
    assert c.key(GL, gn).expires_at == c.now() + oidc.KEY_TTL
    assert c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(GL, gn), 3)]), c.err
    assert c.verify(sign_jwt(gl, gitlab_claims(jti="again")), GL, gn) is not None, c.err
    # when no key of GitHub's is live any more, nothing can be attested, so nothing can be refreshed: the rotate
    # workflow has to run at least once in every 30 days
    c.warp(oidc.KEY_TTL)
    assert c.attest(GH, sn) is None and code(c) == 77
    assert c.verify(sign_jwt(gl, gitlab_claims(jti="dead")), GL, gn) is None and code(c) == 77


# -- the guardian -----------------------------------------------------------------------------------------------------------

def test_revoke_is_for_ever():
    c = Chain2()
    key, n = new_key()
    assert c.admit(GH, n), c.err
    jwt = token(key, aud="before")
    before = c.verify(jwt, GH, n)
    assert before is not None, c.err
    half = token(key, aud="half")
    tid = c.write(half)
    assert c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(GH, n), 8)]), c.err
    assert c.revoke(GH, n), c.err
    print("\nCU Approve, Revoke:", c.cu["approve"][-1], c.cu["revoke"][-1])
    k = c.key(GH, n)
    assert k.revoked and k.approved and oidc.key_usable(k, c.now()) == (False, "the guardian revoked this signing key. It cannot be used again.")
    assert c.verify(token(key), GH, n) is None and code(c) == 78
    assert not c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(GH, n), 8)]) and code(c) == 78     # a begun one stops
    # nothing brings it back: not the guardian, not a new attestation, not time
    assert not c.approve(GH, n) and code(c) == 78
    tok = c.attest(GH, n)
    assert not c.send([c.refresh_ix(GH, n, tok)]) and code(c) == 78
    assert not c.send([c.register_ix(GH, n, tok)]) and code(c) == 67     # the account stays: no second life
    assert not c.send([oidc.register_key_ix(c.payer.pubkey(), GH, n)]) and code(c) == 67
    assert not c.send([oidc.key_params_ix(c.payer.pubkey(), GH, n)]) and code(c) == 69
    assert c.revoke(GH, n) and c.key(GH, n).revoked                                                   # again: still revoked
    c.travel(100 * DAY)
    assert c.key(GH, n) == k and c.verify(token(key), GH, n) is None and code(c) == 78
    # a token verified before the revocation is still the account it was; a consumer's `fresh` bounds it to an hour
    t = oidc.read_token(c.data(before))
    assert t.verified and t.claims() == signed_claims(jwt)
    # a genesis key can be revoked too, and then even GitHub's root is gone for that key
    sn = modulus(signing_key())
    assert c.revoke(GH, sn) and c.verify(token(signing_key()), GH, sn) is None and code(c) == 78
    assert not c.send([oidc.register_key_ix(c.payer.pubkey(), GH, sn)]) and code(c) == 67


def test_no_token_outlives_its_key_by_more_than_25_hours_whatever_expiry_it_carries():
    """Whoever holds a leaked key writes any `exp` he likes. Before the guardian revokes the key he verifies an
    attestation that expires in ten years; if that account stayed good, "revoked for ever" would leave him able to
    refresh and register keys for ten years. The finishing Step refuses an `exp` more than a day ahead of the clock
    (lib.rs AHEAD), and an attestation is refused an hour past its `exp`: 25 hours after the revocation nothing the
    key verified is good for anything."""
    ahead = DAY                                             # lib.rs AHEAD
    c = Chain2()
    leaked, n = new_key()                                   # a key of GitHub's whose private half got out
    assert c.admit(GH, n), c.err
    sn = modulus(signing_key())                             # a key its holder wants kept alive
    mine = new_key()[1]                                     # and one of his own

    def forged(target: int, exp: int):
        claims = attest_claims(GH, target, iat=c.now(), nbf=c.now() - 600, exp=exp, jti=f"f{next(_serial)}")
        return c.verify(sign_jwt(leaked, claims), GH, n)

    for exp in (c.now() + ahead + 1, c.now() + 3650 * DAY, 10 ** 18 - 1):
        assert forged(sn, exp) is None, f"an attestation that expires at {exp} was verified"
        assert code(c) == 63, c.err
    assert c.verify(token(leaked, exp=c.now() + ahead + 1), GH, n) is None and code(c) == 63   # any token, not only an attestation
    gl = signing_key(4096)
    assert c.register(GL, modulus(gl)), c.err
    assert c.verify(sign_jwt(gl, gitlab_claims(exp=c.now() + ahead + 1)), GL, modulus(gl)) is None and code(c) == 63
    assert c.verify(sign_jwt(gl, gitlab_claims(exp=c.now() + ahead)), GL, modulus(gl)) is not None, c.err
    # the furthest expiry that verifies, and what it is worth once the key is revoked
    keep, own = forged(sn, c.now() + ahead), forged(mine, c.now() + ahead)
    assert keep is not None and own is not None, c.err
    assert c.revoke(GH, n), c.err
    expires = c.key(GH, sn).expires_at
    # as an attestation it is worth nothing from the second of the revocation: RegisterKey and Refresh ask the key
    assert not c.send([c.refresh_ix(GH, sn, keep)]) and code(c) == 78
    assert not c.send([c.register_ix(GH, mine, own)]) and code(c) == 78
    c.warp(ahead + oidc.LATE)
    assert not c.send([c.refresh_ix(GH, sn, keep)]) and code(c) == 78
    assert not c.send([c.register_ix(GH, mine, own)]) and code(c) == 78
    assert c.key(GH, sn).expires_at == expires and c.key(GH, mine) is None
    # a token already past its expiry still verifies (lateness is `fresh`'s question, asked by whoever consumes it)
    assert c.verify(token(signing_key(), exp=c.now() - 10 * DAY), GH, sn) is not None, c.err


def test_only_the_guardian_approves_and_revokes_and_it_can_do_nothing_else():
    c = Chain2()
    key, n = new_key()
    assert c.register(GH, n, c.attest(GH, n)), c.err
    kp = oidc.key_pda(GH, n)
    stranger = c.fund()
    for send in (c.approve, c.revoke):
        assert not send(GH, n, guardian=stranger) and code(c) == 79
        assert not send(GH, n, guardian=c.payer) and code(c) == 79
    # the guardian's address without its signature, the real guardian's address without its signature
    for tag in (b"\x06", b"\x07"):
        for who in (GUARDIAN.pubkey(), oidc.GUARDIAN):
            assert not c.send([Instruction(oidc.OIDC_ID, tag, [AccountMeta(who, False, False), AccountMeta(kp, False, True)])]) and code(c) == 79
    k = c.key(GH, n)
    assert not k.approved and not k.revoked
    # the real guardian is a multisig vault: an address no key signs for. With signature checking off (as the
    # vault's signature by a cross-program call would look to this program) it approves and revokes; a stranger's
    # address sent the same way still does not
    assert oidc.GUARDIAN == Pubkey.from_string("AT1aKj1DpgaWerxmS4YjDkNpWPNUtCCKVDvxLhFxg5Jc") and not oidc.GUARDIAN.is_on_curve()
    vn = new_key()[1]
    assert c.register(GH, vn, c.attest(GH, vn)), c.err
    assert not c.send_unsigned([oidc.approve_ix(stranger.pubkey(), GH, vn)]) and code(c) == 79
    assert not c.send_unsigned([oidc.revoke_ix(Keypair().pubkey(), GH, vn)]) and code(c) == 79
    assert c.send_unsigned([oidc.approve_ix(oidc.GUARDIAN, GH, vn)]), c.err
    assert c.key(GH, vn).approved and not c.key(GH, vn).revoked
    assert c.send_unsigned([oidc.revoke_ix(oidc.GUARDIAN, GH, vn)]), c.err
    assert c.key(GH, vn).revoked
    assert c.svm.get_sigverify()                                                               # checking is back on
    # the guardian cannot add a key: that takes GitHub's signature
    other = new_key()[1]
    assert not c.send([oidc.register_key_ix(GUARDIAN.pubkey(), GH, other)], payer=GUARDIAN) and code(c) == 73
    # its two instructions take no data and touch key accounts only: not a token account, not another program's
    tid = c.write(token(signing_key()))
    assert c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(GH, modulus(signing_key())), 8)]), c.err
    tok = oidc.token_pda(c.payer.pubkey(), tid)
    before = c.data(tok)
    for tag in (b"\x06", b"\x07"):
        for account in (tok, c.payer.pubkey(), oidc.key_pda(GH, other)):
            ix = Instruction(oidc.OIDC_ID, tag, [AccountMeta(GUARDIAN.pubkey(), True, False), AccountMeta(account, False, True)])
            assert not c.send([ix], signers=[GUARDIAN]) and code(c) == 68
        ix = Instruction(oidc.OIDC_ID, tag + b"\x01", [AccountMeta(GUARDIAN.pubkey(), True, False), AccountMeta(kp, False, True)])
        assert not c.send([ix], signers=[GUARDIAN]) and "InvalidInstructionData" in c.err
    assert c.data(tok) == before and c.key(GH, n) == k
    # the instructions after its two are not the guardian's: a key of another issuer takes GitHub's signature like any key
    url = "https://oidc.ci.example.dev"
    g = oidc.register_issuer_key_ix(GUARDIAN.pubkey(), url, other, tok, oidc.key_pda(GH, modulus(signing_key())))
    assert not c.send([g], payer=GUARDIAN) and code(c) == 73 and c.key(url, other) is None
    # and there is no instruction after RegisterPrivateKey
    for tag in range(10, 256):
        ix = Instruction(oidc.OIDC_ID, bytes([tag]), [AccountMeta(GUARDIAN.pubkey(), True, True), AccountMeta(kp, False, True)])
        assert not c.send([ix], signers=[GUARDIAN]) and "InvalidInstructionData" in c.err
    # approving changes the approval and nothing else; the day still has to pass
    assert c.approve(GH, n), c.err
    k2 = c.key(GH, n)
    assert k2.approved and (k2.state, k2.active_at, k2.expires_at, k2.revoked, k2.genesis) == (k.state, k.active_at, k.expires_at, False, False)
    assert c.verify(token(key), GH, n) is None and code(c) == 76
    assert c.data(kp)[25:40] == bytes(15)


def test_the_real_build_trusts_none_of_the_test_values():
    """tests/fixtures/knos_oidc_v2_real.so is the same source built with no features, as the deployed program is. The
    seed keys are nobody's keys there and the test guardian is a stranger. (The test rotate pin and the test
    repository cannot be tried on chain: without a seed key nothing can sign an attestation. `cargo test` in the
    crate checks that they exist only under the testkeys feature.)"""
    c = Chain2("knos_oidc_v2_real.so")
    for issuer, key in ((GH, signing_key(2048)), (GL, signing_key(4096))):
        assert not c.send([oidc.register_key_ix(c.payer.pubkey(), issuer, modulus(key))]) and code(c) == 73
    github = [n for _kid, n in oidc.jwks_keys(json.loads((FIX / "github_jwks_2026-10-02.json").read_text()))]
    for n in github:
        assert c.register(GH, n), c.err
        assert oidc.key_usable(c.key(GH, n), c.now()) == (True, "") and c.key(GH, n).genesis
    for _kid, n in oidc.jwks_keys(json.loads((FIX / "gitlab_jwks_2026-10-02.json").read_text())):
        assert not c.send([oidc.register_key_ix(c.payer.pubkey(), GL, n)]) and code(c) == 73
    # the test guardian: refused with its real signature, and with signature checking off
    for send in (c.approve, c.revoke):
        assert not send(GH, github[0]) and code(c) == 79
    assert not c.send_unsigned([oidc.revoke_ix(GUARDIAN.pubkey(), GH, github[0])]) and code(c) == 79
    assert not c.key(GH, github[0]).revoked
    # the real guardian revokes, and the key is gone
    assert c.send_unsigned([oidc.revoke_ix(oidc.GUARDIAN, GH, github[0])]), c.err
    assert c.key(GH, github[0]).revoked and not c.send_unsigned([oidc.approve_ix(oidc.GUARDIAN, GH, github[0])]) and code(c) == 78
    assert [c.key(GH, n).revoked for n in github] == [True, False, False, False]


# -- what held in the first deployment still holds ----------------------------------------------------------------------------

def test_wrong_montgomery_constants_are_refused(chain):
    key, n = new_key()
    assert chain.send([chain.register_ix(GH, n, chain.attest(GH, n))]), chain.err
    n0inv, r2 = oidc.key_params(n)
    kp = oidc.key_pda(GH, n)
    acc = [AccountMeta(chain.payer.pubkey(), True, False), AccountMeta(kp, False, True)]
    bad_r2 = (int.from_bytes(r2, "big") ^ 2).to_bytes(256, "big")
    assert not chain.send([Instruction(oidc.OIDC_ID, b"\x04" + n0inv.to_bytes(4, "little") + bad_r2, acc)]) and code(chain) == 66
    assert not chain.send([Instruction(oidc.OIDC_ID, b"\x04" + ((n0inv + 2) % 2 ** 32).to_bytes(4, "little") + r2, acc)]) and code(chain) == 66
    assert not chain.send([Instruction(oidc.OIDC_ID, b"\x04" + n0inv.to_bytes(4, "little") + r2[:-1], acc)]) and "InvalidInstructionData" in chain.err
    assert chain.key(GH, n).state == 0
    assert chain.send([oidc.key_params_ix(chain.payer.pubkey(), GH, n)]), chain.err
    assert chain.key(GH, n).state == 1
    assert not chain.send([oidc.key_params_ix(chain.payer.pubkey(), GH, n)]) and code(chain) == 69       # once
    # KeyParams on a token account, and an even modulus or one with its top bit clear
    tid = chain.write(token(signing_key()))
    acc[1] = AccountMeta(oidc.token_pda(chain.payer.pubkey(), tid), False, True)
    assert not chain.send([Instruction(oidc.OIDC_ID, b"\x04" + n0inv.to_bytes(4, "little") + r2, acc)]) and "InvalidInstructionData" in chain.err
    for bad in (n + 1, n >> 1):
        assert not chain.send([chain.register_ix(GH, bad, chain.attest(GH, bad))]) and code(chain) == 66


def _flip(jwt: str, part: int, at: int) -> str:
    parts = jwt.split(".")
    raw = bytearray(base64.urlsafe_b64decode(parts[part] + "=" * (-len(parts[part]) % 4)))
    raw[at % len(raw)] ^= 1
    parts[part] = b64(bytes(raw))
    return ".".join(parts)


def test_every_forgery_is_refused(chain):
    key, n = signing_key(), modulus(signing_key())
    good = sign_jwt(key, github_claims(aud="knos2:pay:1:1"))
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    hs = sign_jwt(key, github_claims(), header={"typ": "JWT", "alg": "HS256", "kid": "k"})
    none = sign_jwt(key, github_claims(), header={"typ": "JWT", "alg": "none", "kid": "k"})
    dup = sign_jwt(key, {}, raw_payload=b'{"iss":"https://evil.example","iss":"' + oidc.ISSUERS[GH].encode() + b'","exp":%d}' % (NOW + 300))
    cases = {
        "claims changed after signing": (_flip(good, 1, 40), 70),
        "signature changed": (_flip(good, 2, 100), 70),
        "signed by another key": (sign_jwt(other, github_claims()), 70),
        "alg HS256": (hs, 71),
        "alg none": (none, 71),
        "another issuer in iss": (sign_jwt(key, github_claims(iss="https://gitlab.com")), 72),
        "a look-alike issuer": (sign_jwt(key, github_claims(iss=oidc.ISSUERS[GH] + ".evil.example")), 72),
        "iss twice": (dup, 62),
        "exp as a string": (sign_jwt(key, github_claims(exp=str(NOW + 300))), 63),
        "no exp": (sign_jwt(key, {k: v for k, v in github_claims().items() if k != "exp"}), 63),
        "payload is not an object": (sign_jwt(key, {}, raw_payload=b'["iss"]'), 61),
        "trailing bytes after the object": (sign_jwt(key, {}, raw_payload=json.dumps(github_claims()).encode() + b'{"iss":"x"}'), 61),
        "a fourth part": (good + ".AAAA", 61),
        "signature one byte short": (good[:-2], 65),
        "padding characters": (good + "=", 65),
        "a payload that is not base64url": (good.replace(".", ".+", 1), 70),
    }
    for what, (jwt, want) in cases.items():
        assert chain.verify(jwt, GH, n) is None, f"{what}: accepted"
        assert code(chain) == want, f"{what}: error {chain.err}, wanted {want}"
    # a signature equal to or above the modulus is refused before any arithmetic
    parts = good.split(".")
    for big in (n, n + 1, 2 ** 2048 - 1):
        assert chain.verify(".".join([parts[0], parts[1], b64(big.to_bytes(256, "big"))]), GH, n) is None and code(chain) == 65
    # and a signature of 0 or 1 never verifies
    for small in (0, 1):
        assert chain.verify(".".join([parts[0], parts[1], b64(small.to_bytes(256, "big"))]), GH, n) is None and code(chain) == 70
    # a 2048-bit signature under the 4096-bit key, and the other way round
    assert chain.verify(good, GL, modulus(signing_key(4096))) is None and code(chain) == 65
    assert chain.verify(sign_jwt(signing_key(4096), gitlab_claims()), GH, n) is None and code(chain) == 65


def test_escaped_claims_read_as_the_same_text(chain):
    key, n = signing_key(), modulus(signing_key())
    c = github_claims(aud="knos2:pay:1:1")
    raw = json.dumps(c, separators=(",", ":")).replace("/", "\\/").encode()
    tok = chain.verify(sign_jwt(key, c, raw_payload=raw), GH, n)
    assert tok is not None, chain.err
    assert oidc.read_token(chain.data(tok)).claims() == c
    # an attestation whose claims are escaped names the same key
    new, nn = new_key()
    ac = attest_claims(GH, nn, jti="escaped")
    tok = chain.verify(sign_jwt(key, ac, raw_payload=json.dumps(ac, separators=(",", ":")).replace("/", "\\/").replace("schedule", "sch\\u0065dule").encode()), GH, n)
    assert tok is not None and chain.send([chain.register_ix(GH, nn, tok)]), chain.err


def test_claims_are_read_at_the_top_level_only_and_a_time_is_plain_digits():
    c = Chain2()
    key, sn = signing_key(), modulus(signing_key())
    assert c.register(GH, sn), c.err
    dumps = lambda d: json.dumps(d, separators=(",", ":"))  # noqa: E731
    reg = lambda n, tok: c.send([c.register_ix(GH, n, tok)])  # noqa: E731
    # exp: an unsigned whole number of at most 18 digits, written once
    good, at = dumps(github_claims(jti="exp")), '"exp":%d' % (NOW + 300)
    assert at in good
    for form in ("1.7900003e9", "17900003e2", f"+{NOW + 300}", "-1", f"0{NOW + 300}", f"{NOW + 300}.0", "1" + "0" * 18, "null", "true",
                 f"[{NOW + 300}]", '{"exp":%d}' % (NOW + 300)):
        jwt = sign_jwt(key, {}, raw_payload=good.replace(at, '"exp":' + form).encode())
        assert c.verify(jwt, GH, sn) is None and code(c) == 63, f"exp {form}: {c.err}"
    assert c.verify(sign_jwt(key, {}, raw_payload=good.replace(at, at + "," + at).encode()), GH, sn) is None and code(c) == 62
    # a claim's name inside a nested object, inside a list, or inside a string's text is not that claim: with the
    # right values only there, and one wrong value where the claims are, the attestation names nothing
    _new, n = new_key()
    right = attest_claims(GH, n)
    decoys = {"decoy": {**{k: right[k] for k in ("aud", "repository_id", "repository_owner_id", "event_name", "job_workflow_sha")},
                        "deeper": [{"aud": right["aud"]}, "]}", {"x": "}"}]},
              "note": '","aud":"%s","event_name":"schedule","x":"' % right["aud"]}
    for name, bad in (("aud", oidc.rotate_audience(GH, n + 2)), ("repository_id", "1"), ("event_name", "push")):
        tok = c.verify(sign_jwt(key, {**decoys, **attest_claims(GH, n, jti=f"decoy {name}", **{name: bad})}), GH, sn)
        assert tok is not None, c.err
        assert not reg(n, tok) and code(c) == 74, f"{name}: {c.err}"
    # and the other way round: wrong values in the decoys change nothing
    lies = {"decoy": {"aud": "evil", "repository_id": "1", "event_name": "push", "exp": 1, "iss": "https://evil.example"},
            "note": '","aud":"evil","exp":1,"iss":"https://evil.example","x":"'}
    claims = {**lies, **attest_claims(GH, n, jti="top")}
    tok = c.verify(sign_jwt(key, claims), GH, sn)
    assert tok is not None and oidc.read_token(c.data(tok)).claims() == claims, c.err
    assert reg(n, tok), c.err
    # a claim RegisterKey reads, written twice: the token verifies (Step reads iss and exp), the attestation is refused
    _new, n2 = new_key()
    twice = dumps(attest_claims(GH, n2, jti="twice", aud="evil"))[:-1] + ',"aud":"%s"}' % oidc.rotate_audience(GH, n2)
    tok = c.verify(sign_jwt(key, {}, raw_payload=twice.encode()), GH, sn)
    assert tok is not None and not reg(n2, tok) and code(c) == 62
    # alg twice in the header
    head = b'{"alg":"none","typ":"JWT","alg":"RS256"}'
    body = b64(dumps(github_claims(jti="alg")).encode())
    sig = key.sign(f"{b64(head)}.{body}".encode())
    assert c.verify(f"{b64(head)}.{body}.{b64(sig)}", GH, sn) is None and code(c) == 62


def test_nothing_computed_for_one_token_serves_another_and_no_account_stands_in_for_another():
    c = Chain2()
    key, sn = signing_key(), modulus(signing_key())
    me, kp = c.payer.pubkey(), oidc.key_pda(GH, modulus(signing_key()))
    swap = lambda ix, at, meta: Instruction(ix.program_id, bytes(ix.data), [*ix.accounts[:at], meta, *ix.accounts[at + 1:]])  # noqa: E731
    # a key whose Montgomery constants nobody has sent verifies nothing
    assert c.send([oidc.register_key_ix(me, GH, sn)]), c.err
    jwt = sign_jwt(key, github_claims(jti="one", aud="knos2:pay:1:1"))
    tid = c.write(jwt)
    tok = oidc.token_pda(me, tid)
    assert not c.send([oidc.step_ix(me, tid, kp, 8)]) and code(c) == 68
    assert c.send([oidc.key_params_ix(me, GH, sn)]), c.err
    # once the first step has run the token's bytes are fixed: the half-done power cannot be given another token
    assert c.send([oidc.step_ix(me, tid, kp, 8)]), c.err
    other = sign_jwt(key, github_claims(jti="two", aud="knos2:pay:1:2"))
    assert len(other) == len(jwt)
    half = c.data(tok)
    for ix in oidc.write_ixs(me, tid, other):
        assert not c.send([ix]) and code(c) == 69
    assert c.data(tok) == half
    assert c.send([oidc.step_ix(me, tid, kp, 8)]), c.err
    assert oidc.read_token(c.data(tok)).claims() == signed_claims(jwt)
    # closing and writing under the same id starts from nothing
    assert c.send([oidc.close_ix(me, tid)]), c.err
    for ix in oidc.write_ixs(me, tid, other):
        assert c.send([ix]), c.err
    d = c.data(tok)
    assert d[0] == 0 and d[2] == 0 and d[18:50] == bytes(32) and d[114:626] == bytes(512)
    assert c.send([oidc.step_ix(me, tid, kp, 8)]) and c.send([oidc.step_ix(me, tid, kp, 8)]), c.err
    assert oidc.read_token(c.data(tok)).claims() == signed_claims(other)
    # all sixteen squarings of a 4096-bit key in one call: it runs out, and nothing is left behind
    gl, gn = signing_key(4096), modulus(signing_key(4096))
    assert c.register(GL, gn), c.err
    big = sign_jwt(gl, gitlab_claims(jti="big"))
    btid = c.write(big)
    before = c.data(oidc.token_pda(me, btid))
    assert not c.send([oidc.step_ix(me, btid, oidc.key_pda(GL, gn), 16)]) and code(c) is None
    assert c.data(oidc.token_pda(me, btid)) == before
    assert c.verify(sign_jwt(gl, gitlab_claims(jti="big2")), GL, gn) is not None, c.err
    # accounts: every instruction that needs the payer's signature refuses without it
    stranger = c.fund()
    unsigned = AccountMeta(me, False, True)
    for ix in (oidc.write_ixs(me, bytes(32), "a.b.c")[0], oidc.step_ix(me, btid, oidc.key_pda(GL, gn), 1), oidc.close_ix(me, btid),
               oidc.register_key_ix(me, GH, new_key()[1]), oidc.key_params_ix(me, GH, sn)):
        assert not c.send([swap(ix, 0, unsigned)], stranger) and code(c) == 67, c.err
    # Write: only the address derived from the payer and the id, and only the system program
    w = oidc.write_ixs(me, bytes(32), "a.b.c")[0]
    for at, meta in ((1, AccountMeta(oidc.token_pda(stranger.pubkey(), bytes(32)), False, True)), (1, AccountMeta(oidc.token_pda(me, bytes([1]) * 32), False, True)),
                     (1, AccountMeta(kp, False, True)), (2, AccountMeta(oidc.OIDC_ID, False, False))):
        assert not c.send([swap(w, at, meta)]) and code(c) == 67
    # RegisterKey: only the address derived from the issuer and the modulus's hash, and only the system program
    _k, n = new_key()
    r = c.register_ix(GH, n, c.attest(GH, n))
    for at, meta in ((1, AccountMeta(oidc.key_pda(GL, n), False, True)), (1, AccountMeta(oidc.key_pda(GH, n + 2), False, True)),
                     (1, AccountMeta(Keypair().pubkey(), False, True)), (2, AccountMeta(oidc.OIDC_ID, False, False))):
        assert not c.send([swap(r, at, meta)]) and code(c) == 67
    assert c.key(GH, n) is None and c.send([r]), c.err
    # Step: the key must be a key account of this program
    t2 = c.write(sign_jwt(key, github_claims(jti="three")))
    for not_a_key in (me, oidc.OIDC_ID, tok, Keypair().pubkey()):
        assert not c.send([oidc.step_ix(me, t2, not_a_key, 8)]) and code(c) == 68


def test_a_token_account_belongs_to_its_payer_and_closes_with_its_rent(chain):
    key, n = signing_key(), modulus(signing_key())
    alice, bob = chain.fund(), chain.fund()
    jwt = sign_jwt(key, github_claims(aud="knos2:pay:1:9"))
    tid = chain.write(jwt, alice)
    kp = oidc.key_pda(GH, n)
    # bob cannot step or close alice's account (the address is derived from the payer)
    atok = oidc.token_pda(alice.pubkey(), tid)
    forged = Instruction(oidc.OIDC_ID, b"\x01" + tid + bytes([8]), [AccountMeta(bob.pubkey(), True, False), AccountMeta(atok, False, True), AccountMeta(kp, False, False)])
    assert not chain.send([forged], bob) and code(chain) == 67
    forged = Instruction(oidc.OIDC_ID, b"\x02" + tid, [AccountMeta(bob.pubkey(), True, True), AccountMeta(atok, False, True)])
    assert not chain.send([forged], bob) and code(chain) == 67
    assert chain.send([oidc.step_ix(alice.pubkey(), tid, kp, 8)], alice) and chain.send([oidc.step_ix(alice.pubkey(), tid, kp, 8)], alice)
    assert oidc.read_token(chain.data(atok)).verified
    # a verified account is final: no more writes, no more steps
    assert not chain.send([oidc.write_ixs(alice.pubkey(), tid, jwt)[0]], alice) and code(chain) == 69
    assert not chain.send([oidc.step_ix(alice.pubkey(), tid, kp, 8)], alice) and code(chain) == 69
    before = chain.svm.get_balance(alice.pubkey())
    assert chain.send([oidc.close_ix(alice.pubkey(), tid)], alice)
    assert chain.data(atok) is None and chain.svm.get_balance(alice.pubkey()) > before
    # steps in a different split still verify (any number of squarings per call, 16 in all)
    tid = chain.write(jwt, bob)
    for sq in (1, 5, 0, 7, 16):
        assert chain.send([oidc.step_ix(bob.pubkey(), tid, kp, sq)], bob), chain.err
    assert oidc.read_token(chain.data(oidc.token_pda(bob.pubkey(), tid))).verified
    # a step under one key cannot be finished under another, and a token account is not a key
    k2 = oidc.jwks_keys(json.loads((FIX / "github_jwks_2026-10-02.json").read_text()))[0][1]
    assert chain.register(GH, k2), chain.err
    tid = chain.write(sign_jwt(key, github_claims(aud="knos2:pay:1:10")), bob)
    assert chain.send([oidc.step_ix(bob.pubkey(), tid, kp, 8)], bob)
    assert not chain.send([oidc.step_ix(bob.pubkey(), tid, oidc.key_pda(GH, k2), 8)], bob) and code(chain) == 68
    assert not chain.send([oidc.step_ix(bob.pubkey(), tid, oidc.token_pda(bob.pubkey(), tid), 8)], bob) and code(chain) == 68


def test_the_chain_agrees_with_a_reference_rsa_library_on_random_tokens(chain):
    """Differential test: 60 random tokens, each also with one random bit flipped; the on-chain verdict equals
    `cryptography`'s (OpenSSL) PKCS#1 v1.5 verification of the same bytes."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key, n = signing_key(), modulus(signing_key())
    rng = random.Random(20261002)
    agree = 0
    for i in range(60):
        claims = github_claims(aud="knos2:" + "".join(rng.choice("abcdef0123456789:") for _ in range(rng.randrange(1, 200))),
                               workflow="w" * rng.randrange(0, 300), run_id=str(rng.randrange(10 ** 12)))
        good = sign_jwt(key, claims)
        part, at = rng.choice([1, 2]), rng.randrange(4000)
        for jwt in (good, _flip(good, part, at)):
            h, p, s = jwt.split(".")
            try:
                key.public_key().verify(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
                ref = True
            except InvalidSignature:
                ref = False
            got = chain.verify(jwt, GH, n) is not None
            # a flipped payload bit can also break the JSON or the iss/exp claims: then the reference accepts the
            # signature of different bytes only if the bytes are unchanged, which a flip never leaves
            assert got == ref, f"token {i}: chain {got}, reference {ref}, {chain.err}"
            agree += 1
    assert agree == 120


# -- the client's words -------------------------------------------------------------------------------------------------------

def test_key_usable_says_what_the_program_will_say_and_what_to_do():
    K = oidc.Key
    base = dict(state=1, issuer=GH, bits=2048, active_at=1_000, expires_at=2_000, approved=True, revoked=False, genesis=False)
    usable = lambda now, **over: oidc.key_usable(K(**{**base, **over}), now)  # noqa: E731
    assert usable(1_000) == (True, "") and usable(1_999) == (True, "") and usable(1_500, approved=False, genesis=True) == (True, "")
    for now, over, word in ((999, {}, "can be used from 1970-01-01 00:16 UTC"), (2_000, {}, "expired 1970-01-01 00:33 UTC"),
                            (1_500, dict(approved=False), "has not approved"), (1_500, dict(revoked=True), "revoked"),
                            (1_500, dict(state=0), "KeyParams"), (5_000, dict(revoked=True, approved=False, state=1), "revoked")):
        ok, why = usable(now, **over)
        assert not ok and word in why and why[0].islower() and why.endswith("."), why
    ok, why = oidc.key_usable(None, 0)
    assert not ok and "RegisterKey" in why
    # the same order as the program: revoked before anything, then not active, then expired
    assert "has not approved" in usable(5_000, approved=False)[1] and "revoked" in usable(0, revoked=True)[1]
    assert (oidc.KEY_DELAY, oidc.KEY_TTL, oidc.K_HDR) == (86_400, 30 * 86_400, 40)
