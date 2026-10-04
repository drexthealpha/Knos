"""knos-oidc in the Solana runtime (LiteSVM, the testkeys build): an RS256 token from GitHub Actions or GitLab CI is
verified on chain against keys nobody administers. Real issuer keys register from the hashes fixed in the binary;
anything else needs GitHub's own signature from the pinned rotate workflow. Prints the compute units of every step."""
from __future__ import annotations

import base64
import json
import random

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from _settle import FIX, NOW, Chain, b64, github_claims, gitlab_claims, jwt_size, modulus, sign_jwt, signing_key, sized_jwt  # noqa: E402

from knos.settle import oidc  # noqa: E402

GH, GL = oidc.GITHUB, oidc.GITLAB
ROTATE_REF = "drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@refs/heads/main"
TEST_ROTATE_SHA = "1" * 40


@pytest.fixture(scope="module")
def chain():
    c = Chain()
    assert c.register(GH, modulus(signing_key(2048))), c.err
    assert c.register(GL, modulus(signing_key(4096))), c.err
    return c


def code(c: Chain) -> int | None:
    import re
    m = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(m.group(1)) if m else None


def test_the_real_issuer_keys_register_from_the_hashes_in_the_binary_and_no_other_key_does(chain):
    for issuer, file in ((GH, "github_jwks_2026-10-02.json"), (GL, "gitlab_jwks_2026-10-02.json")):
        keys = oidc.jwks_keys(json.loads((FIX / file).read_text()))
        assert len(keys) >= 3
        for _kid, n in keys:
            assert chain.register(issuer, n), chain.err
            assert chain.data(oidc.key_pda(issuer, n))[0] == 1          # ready
    # a GitHub key is not a GitLab key
    gh_n = oidc.jwks_keys(json.loads((FIX / "github_jwks_2026-10-02.json").read_text()))[0][1]
    assert not chain.send([oidc.register_key_ix(chain.payer.pubkey(), GL, gh_n)]) and code(chain) == 73
    # a key nobody vouched for
    stranger = modulus(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    assert not chain.send([oidc.register_key_ix(chain.payer.pubkey(), GH, stranger)]) and code(chain) == 73


def test_wrong_montgomery_constants_are_refused(chain):
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = modulus(k)
    # get it registered through an attestation (see the rotation test), then try bad parameters
    tok = chain.verify(sign_jwt(signing_key(), github_claims(aud=oidc.rotate_audience(GH, n), job_workflow_ref=ROTATE_REF,
                                                           job_workflow_sha=TEST_ROTATE_SHA)), GH, modulus(signing_key()))
    assert chain.send([oidc.register_key_ix(chain.payer.pubkey(), GH, n, tok)]), chain.err
    n0inv, r2 = oidc.key_params(n)
    key = oidc.key_pda(GH, n)
    from solders.instruction import AccountMeta, Instruction
    acc = [AccountMeta(chain.payer.pubkey(), True, False), AccountMeta(key, False, True)]
    bad_r2 = (int.from_bytes(r2, "big") ^ 2).to_bytes(256, "big")
    assert not chain.send([Instruction(oidc.OIDC_ID, b"\x04" + n0inv.to_bytes(4, "little") + bad_r2, acc)]) and code(chain) == 66
    assert not chain.send([Instruction(oidc.OIDC_ID, b"\x04" + ((n0inv + 2) % 2 ** 32).to_bytes(4, "little") + r2, acc)]) and code(chain) == 66
    # a token cannot be stepped against a key that is not ready
    jwt = sign_jwt(k, github_claims())
    tid = chain.write(jwt)
    assert not chain.send([oidc.step_ix(chain.payer.pubkey(), tid, key, 8)]) and code(chain) == 68
    assert chain.send([oidc.key_params_ix(chain.payer.pubkey(), GH, n)]), chain.err
    assert chain.send([oidc.step_ix(chain.payer.pubkey(), tid, key, 8)]) and chain.send([oidc.step_ix(chain.payer.pubkey(), tid, key, 8)])


def test_a_github_token_is_verified_in_two_transactions(chain):
    claims = github_claims(aud="knos:pay:987654321:7")
    jwt = sign_jwt(signing_key(), claims)
    tok = chain.verify(jwt, GH, modulus(signing_key()), tag="verify")
    assert tok is not None, chain.err
    t = oidc.read_token(chain.data(tok))
    assert t.verified and t.issuer == GH and t.exp == NOW + 300 and t.claims() == claims
    assert t.key == oidc.key_pda(GH, modulus(signing_key())) and t.payer == chain.payer.pubkey()
    print("\nCU 2048-bit:", {k: v[-1] for k, v in chain.cu.items() if k.startswith("verify_2048")})
    assert all(v[-1] < 1_200_000 for k, v in chain.cu.items() if k.startswith("verify_2048"))


def test_a_gitlab_token_under_a_4096_bit_key_is_verified_in_six(chain):
    claims = {"iss": oidc.ISSUERS[GL], "sub": "project_path:grp/app:ref_type:branch:ref:main", "aud": "knos:pay:1:2",
              "project_path": "grp/app", "project_id": "55", "ref": "main", "sha": "d" * 40, "pipeline_source": "merge_request_event",
              "user_id": "77", "user_login": "sam", "ci_config_ref_uri": "gitlab.com/grp/app//.gitlab-ci.yml@refs/heads/main",
              "ci_config_sha": "e" * 40, "runner_environment": "gitlab-hosted", "nbf": NOW - 5, "exp": NOW + 300, "iat": NOW}
    key = signing_key(4096)
    tok = chain.verify(sign_jwt(key, claims), GL, modulus(key), tag="verify")
    assert tok is not None, chain.err
    t = oidc.read_token(chain.data(tok))
    assert t.verified and t.issuer == GL and t.claims() == claims
    print("\nCU 4096-bit:", {k: v[-1] for k, v in chain.cu.items() if k.startswith("verify_4096")})
    assert all(v[-1] < 1_350_000 for k, v in chain.cu.items() if k.startswith("verify_4096"))
    # the same key cannot vouch for GitHub's issuer
    assert chain.verify(sign_jwt(key, github_claims()), GL, modulus(key)) is None and code(chain) == 72


def test_the_4096_bit_plan_fits_a_token_of_any_size_and_the_old_plan_ran_out(chain):
    """Regression. A GitLab token grows with the user's groups. The plan this client used to send for 4096-bit keys,
    [2, 3, 3, 3, 3, 2], ends with two squarings, and the call that finishes also multiplies once more, hashes the
    token, decodes its payload and reads its claims: past about 5,000 bytes of such a token that call ran out of
    compute units (it fits at 4,500 and does not at 5,500; in between it depends on the token). step_plan now ends
    with one squaring, and every call fits for every size the program takes."""
    key, n = signing_key(4096), modulus(signing_key(4096))
    old, plan = [2, 3, 3, 3, 3, 2], oidc.step_plan(4096)
    assert plan == [2, 3, 3, 3, 4, 1] and sum(plan) == 16 == sum(oidc.step_plan(2048)) and len(plan) == len(old)

    def steps(jwt: str, squarings: list[int]) -> list[int]:
        """The compute units of each step that succeeded (a failed step ends the run)."""
        tid, out = chain.write(jwt), []
        for sq in squarings:
            if not chain.send([oidc.step_ix(chain.payer.pubkey(), tid, oidc.key_pda(GL, n), sq)], tag="plan"):
                break
            out.append(chain.cu["plan"][-1])
        return out

    for size in (2_500, 3_500, 4_500, 5_500, oidc.MAX_JWT):
        jwt = sized_jwt(key, gitlab_claims(aud=f"knos:pay:1:{size}"), size)
        tok = chain.verify(jwt, GL, n, tag=f"gitlab{size}")
        assert tok is not None, f"{len(jwt)} bytes: {chain.err}"
        cu = [chain.cu[f"gitlab{size}_4096_step{i + 1}"][-1] for i in range(len(plan))]
        print(f"\nCU 4096-bit, {len(jwt)}-byte GitLab token, plan {plan}: {cu}")
        assert max(cu) < 1_340_000, cu                      # at least 60,000 compute units to spare in every step
        body = jwt.split(".")[1]
        signed = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        assert oidc.read_token(chain.data(tok)).claims() == signed and signed["aud"] == f"knos:pay:1:{size}"
        # the same token under the old plan
        assert chain.send([oidc.close_ix(chain.payer.pubkey(), oidc.token_id(jwt))]), chain.err
        got = steps(jwt, old)
        print(f"   the old plan {old}: {got if len(got) == 6 else got + ['out of compute units']}")
        if size <= 4_500:
            assert len(got) == 6 and oidc.read_token(chain.data(oidc.token_pda(chain.payer.pubkey(), oidc.token_id(jwt)))).verified
        else:
            assert len(got) == 5 and "ProgramFailedToComplete" in chain.err
            assert not oidc.read_token(chain.data(oidc.token_pda(chain.payer.pubkey(), oidc.token_id(jwt)))).verified
    # no shorter plan exists: the first call cannot take three squarings, no call five, and the last needs its own
    short = sized_jwt(key, gitlab_claims(aud="knos:pay:1:0"), 2_500)
    assert steps(short, [3]) == [] and "ProgramFailedToComplete" in chain.err
    assert chain.send([oidc.close_ix(chain.payer.pubkey(), oidc.token_id(short))]), chain.err
    assert len(steps(short, [2, 5])) == 1 and "ProgramFailedToComplete" in chain.err
    # claims of the costliest shape we could build (many two-byte pairs that are not ASCII), at the largest size
    base = json.dumps(gitlab_claims(), separators=(",", ":")).encode()[:-1]
    pairs = next(k for k in range(2000, 0, -1) if jwt_size(key, len(base) + 6 * k + 1) <= oidc.MAX_JWT)
    worst = sign_jwt(key, {}, raw_payload=base + b"," + b",".join([b'"\xff":\xff'] * pairs) + b"}")
    assert oidc.MAX_JWT - 8 <= len(worst) <= oidc.MAX_JWT
    assert chain.verify(worst, GL, n, tag="worst") is not None, chain.err
    cu = [chain.cu[f"worst_4096_step{i + 1}"][-1] for i in range(len(plan))]
    print(f"CU 4096-bit, {len(worst)}-byte token of the costliest claims: {cu}")
    assert max(cu) < 1_400_000


def _flip(jwt: str, part: int, at: int) -> str:
    parts = jwt.split(".")
    raw = bytearray(base64.urlsafe_b64decode(parts[part] + "=" * (-len(parts[part]) % 4)))
    raw[at % len(raw)] ^= 1
    parts[part] = b64(bytes(raw))
    return ".".join(parts)


def _by_another_key(n: int) -> str:
    """A token signed by another 2048-bit key, whose signature read as a number is below n. One at or above n is
    refused before any arithmetic (E_SIG 65, asserted below), and a random key's signature is that whenever it falls
    between n and the other key's larger modulus: drawn unchecked, it made this test fail now and then."""
    while True:
        jwt = sign_jwt(rsa.generate_private_key(public_exponent=65537, key_size=2048), github_claims())
        sig = jwt.split(".")[2]
        if int.from_bytes(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)), "big") < n:
            return jwt


def test_every_forgery_is_refused(chain):
    key, n = signing_key(), modulus(signing_key())
    good = sign_jwt(key, github_claims(aud="knos:pay:1:1"))
    other = _by_another_key(n)
    hs = sign_jwt(key, github_claims(), header={"typ": "JWT", "alg": "HS256", "kid": "k"})
    none = sign_jwt(key, github_claims(), header={"typ": "JWT", "alg": "none", "kid": "k"})
    dup = sign_jwt(key, {}, raw_payload=b'{"iss":"https://evil.example","iss":"' + oidc.ISSUERS[GH].encode() + b'","exp":%d}' % (NOW + 300))
    cases = {
        "claims changed after signing": (_flip(good, 1, 40), 70),
        "signature changed": (_flip(good, 2, 100), 70),
        "signed by another key": (other, 70),
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


def test_escaped_claims_and_long_tokens(chain):
    key, n = signing_key(), modulus(signing_key())
    # an issuer may escape "/" in JSON; the claim still reads as the same text
    c = github_claims(aud="knos:pay:1:1")
    raw = json.dumps(c, separators=(",", ":")).replace("/", "\\/").encode()
    tok = chain.verify(sign_jwt(key, c, raw_payload=raw), GH, n)
    assert tok is not None, chain.err
    assert oidc.read_token(chain.data(tok)).claims() == c
    # the longest names GitHub allows: a 39-character owner, a 100-character repository, a 244-character branch
    repo = "o" * 39 + "/" + "r" * 100
    branch = "feature/" + "b" * 236
    long = github_claims(repository=repo, repository_owner="o" * 39, ref=f"refs/heads/{branch}", head_ref=branch, base_ref="main",
                         sub=f"repo:{repo}:ref:refs/heads/{branch}", workflow="w" * 200,
                         workflow_ref=f"{repo}/.github/workflows/{'k' * 60}.yml@refs/heads/{branch}",
                         aud="knos:pay:987654321:1234567:7654321:" + "a" * 40 + ":" + "c" * 64 + ":1")
    jwt = sign_jwt(key, long)
    print(f"\nworst-case GitHub token: {len(jwt)} bytes")
    assert 2_400 < len(jwt) < oidc.MAX_JWT
    tok = chain.verify(jwt, GH, n, tag="long")
    assert tok is not None, chain.err
    assert oidc.read_token(chain.data(tok)).claims() == long
    print("CU worst-case token:", {k: v[-1] for k, v in chain.cu.items() if k.startswith("long")})
    assert all(v[-1] < 1_200_000 for k, v in chain.cu.items() if k.startswith("long"))
    # exactly the maximum fits; one byte more is refused before anything is written
    pad = github_claims(workflow="")
    base = len(sign_jwt(key, pad))
    fill = (oidc.MAX_JWT - base) * 3 // 4 - 2
    biggest = sign_jwt(key, github_claims(workflow="w" * fill))
    while len(biggest) < oidc.MAX_JWT:
        fill += 1; biggest = sign_jwt(key, github_claims(workflow="w" * fill))
    while len(biggest) > oidc.MAX_JWT:
        fill -= 1; biggest = sign_jwt(key, github_claims(workflow="w" * fill))
    assert chain.verify(biggest, GH, n, tag="max") is not None, chain.err
    print(f"{len(biggest)}-byte token CU:", {k: v[-1] for k, v in chain.cu.items() if k.startswith("max")})
    with pytest.raises(ValueError):
        oidc.write_ixs(chain.payer.pubkey(), b"\0" * 32, "x" * (oidc.MAX_JWT + 1))


def test_a_new_key_is_added_by_githubs_own_signature_and_by_nothing_else(chain):
    signer, sn = signing_key(), modulus(signing_key())
    new = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = modulus(new)

    def attest(**over):
        c = github_claims(aud=oidc.rotate_audience(GH, n), job_workflow_ref=ROTATE_REF, job_workflow_sha=TEST_ROTATE_SHA,
                          event_name="schedule")
        c.update(over)
        return chain.verify(sign_jwt(signer, c), GH, sn)

    reg = lambda tok: chain.send([oidc.register_key_ix(chain.payer.pubkey(), GH, n, tok)])  # noqa: E731
    assert not reg(None) and code(chain) == 73
    refused = {
        "another workflow file": dict(job_workflow_ref="drexthealpha/knos-oidc-rotate/.github/workflows/other.yml@refs/heads/main"),
        "another repository": dict(job_workflow_ref="evil/knos-oidc-rotate/.github/workflows/rotate.yml@refs/heads/main"),
        "another commit of the workflow": dict(job_workflow_sha="2" * 40),
        "a self-hosted runner": dict(runner_environment="self-hosted"),
        "an audience naming another key": dict(aud=oidc.rotate_audience(GH, n + 2)),
        "an audience naming another issuer": dict(aud=oidc.rotate_audience(GL, n)),
    }
    for what, over in refused.items():
        assert not reg(attest(**over)), f"{what}: accepted"
        assert code(chain) == 74, f"{what}: {chain.err}"
    # a GitLab-signed token cannot add a key
    gl = signing_key(4096)
    tok = chain.verify(sign_jwt(gl, {"iss": oidc.ISSUERS[GL], "exp": NOW + 300, "aud": oidc.rotate_audience(GH, n),
                                     "job_workflow_ref": ROTATE_REF, "job_workflow_sha": TEST_ROTATE_SHA,
                                     "runner_environment": "github-hosted"}), GL, modulus(gl))
    assert not reg(tok) and code(chain) == 74
    # an expired attestation
    tok = attest()
    chain.warp(300 + oidc.LATE)
    assert not reg(tok) and code(chain) == 75
    chain.warp(-(300 + oidc.LATE))
    # a token account that is not verified yet, and an account of another program
    tid = chain.write(sign_jwt(signer, github_claims(aud=oidc.rotate_audience(GH, n), job_workflow_ref=ROTATE_REF, job_workflow_sha=TEST_ROTATE_SHA)))
    assert not reg(oidc.token_pda(chain.payer.pubkey(), tid)) and code(chain) == 73
    assert not reg(chain.payer.pubkey()) and code(chain) == 73
    # the real thing, relayed 59 minutes after the token's own five-minute life ended
    tok = attest()
    chain.warp(300 + oidc.LATE - 60)
    assert reg(tok), chain.err
    chain.warp(-(300 + oidc.LATE - 60))
    assert chain.send([oidc.key_params_ix(chain.payer.pubkey(), GH, n)]), chain.err
    assert chain.verify(sign_jwt(new, github_claims()), GH, n) is not None, chain.err
    # the same key cannot be registered twice
    assert not reg(attest()) and code(chain) == 67


def test_a_token_account_belongs_to_its_payer_and_closes_with_its_rent(chain):
    key, n = signing_key(), modulus(signing_key())
    alice, bob = chain.fund(), chain.fund()
    jwt = sign_jwt(key, github_claims(aud="knos:pay:1:9"))
    tid = chain.write(jwt, alice)
    kp = oidc.key_pda(GH, n)
    # bob cannot step or close alice's account (the address is derived from the payer)
    from solders.instruction import AccountMeta, Instruction
    atok = oidc.token_pda(alice.pubkey(), tid)
    forged = Instruction(oidc.OIDC_ID, b"\x01" + tid + bytes([8]), [AccountMeta(bob.pubkey(), True, False), AccountMeta(atok, False, True), AccountMeta(kp, False, False)])
    assert not chain.send([forged], bob) and code(chain) == 67
    forged = Instruction(oidc.OIDC_ID, b"\x02" + tid, [AccountMeta(bob.pubkey(), True, True), AccountMeta(oidc.token_pda(alice.pubkey(), tid), False, True)])
    assert not chain.send([forged], bob) and code(chain) == 67
    assert chain.send([oidc.step_ix(alice.pubkey(), tid, kp, 8)], alice) and chain.send([oidc.step_ix(alice.pubkey(), tid, kp, 8)], alice)
    tok = oidc.token_pda(alice.pubkey(), tid)
    assert oidc.read_token(chain.data(tok)).verified
    # a verified account is final: no more writes, no more steps
    assert not chain.send([oidc.write_ixs(alice.pubkey(), tid, jwt)[0]], alice) and code(chain) == 69
    assert not chain.send([oidc.step_ix(alice.pubkey(), tid, kp, 8)], alice) and code(chain) == 69
    before = chain.svm.get_balance(alice.pubkey())
    assert chain.send([oidc.close_ix(alice.pubkey(), tid)], alice)
    assert chain.data(tok) is None and chain.svm.get_balance(alice.pubkey()) > before
    # steps in a different split still verify (any number of squarings per call, 16 in all)
    tid = chain.write(jwt, bob)
    for sq in (1, 5, 0, 7, 16):
        assert chain.send([oidc.step_ix(bob.pubkey(), tid, kp, sq)], bob), chain.err
    assert oidc.read_token(chain.data(oidc.token_pda(bob.pubkey(), tid))).verified
    # a step under one key cannot be finished under another
    k2 = oidc.jwks_keys(json.loads((FIX / "github_jwks_2026-10-02.json").read_text()))[0][1]
    tid = chain.write(sign_jwt(key, github_claims(aud="knos:pay:1:10")), bob)
    assert chain.send([oidc.step_ix(bob.pubkey(), tid, kp, 8)], bob)
    assert not chain.send([oidc.step_ix(bob.pubkey(), tid, oidc.key_pda(GH, k2), 8)], bob) and code(chain) == 68


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
        claims = github_claims(aud="knos:" + "".join(rng.choice("abcdef0123456789:") for _ in range(rng.randrange(1, 200))),
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
