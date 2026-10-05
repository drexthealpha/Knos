"""The relay end to end, from token strings alone (LiteSVM): a comment funds a bounty, a merge pays its author's
GitHub account, a sponsor's wallet-funded bounty on the same issue is paid by the same proof, the author claims to an
address, a tests-mode job waits and is settled, an unproven job is refunded, and a new issuer key is added from
GitHub's own attestation. Bad tokens come back as {"ok": False} and move nothing."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from solders.keypair import Keypair  # noqa: E402

from _settle import Chain, ChainLedger, b64, github_claims, modulus, sign_jwt, signing_key  # noqa: E402

from knos.settle import oidc, pay, relay  # noqa: E402

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]

REPO, OWNER, AUTHOR = 5550001, 777, 4242
USDC = 1_000_000
WF = "drexthealpha/Knos"
SHA = "c" * 40


def jwks_of(*keys) -> dict:
    return {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": f"k{i}", "n": b64(oidc.modulus_bytes(modulus(k)))} for i, k in enumerate(keys)]}


@pytest.fixture(scope="module")
def env():
    c = Chain()
    ledger = ChainLedger(c)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    return c, ledger, {oidc.GITHUB: jwks_of(signing_key())}


def token(c: Chain, aud: str, file: str = "prove.yml", **over) -> str:
    now = c.now()
    c._n = getattr(c, "_n", 0) + 1
    claims = github_claims(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"r{c._n}", repository_id=str(REPO), repository_owner_id=str(OWNER),
                           job_workflow_ref=f"{WF}/.github/workflows/{file}@refs/tags/v0.3.10", job_workflow_sha=SHA)
    claims.update(over)
    return sign_jwt(signing_key(), claims, header={"typ": "JWT", "alg": "RS256", "kid": "k0"})


def test_fund_pay_claim_from_tokens_alone(env):
    c, ledger, jwks = env
    go = lambda jwt: relay.submit(ledger, c.payer, jwt, jwks, now=c.now())  # noqa: E731
    # the signing key is a (test) genesis key the chain has not seen: the relay registers it on the way
    r = go(token(c, pay.fund_audience(7, 5 * USDC), file="fund.yml"))
    assert r["ok"] and r["kind"] == "fund" and r["amount"] == 5 * USDC, r
    assert pay.read_job(c.data(pay.job_pda(REPO, 7))).state == "open"
    # a sponsor adds 20 USDC from a wallet to the same issue
    usdc = c.new_mint()
    sponsor = c.fund()
    stok = c.token_account(sponsor.pubkey(), usdc)
    c.mint_to(usdc, stok, 20 * USDC)
    assert c.send([pay.fund_ix(sponsor.pubkey(), stok, usdc, REPO, 7, 20 * USDC, WF, SHA)], sponsor), c.err
    # one merge proof pays both
    r = go(token(c, pay.pay_audience(REPO, 7, AUTHOR, "a" * 40)))
    assert r["ok"] and len(r["paid"]) == 2 and {p["amount"] for p in r["paid"]} == {5 * USDC, 20 * USDC}, r
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, pay.faucet_mint()))) == 4_875_000
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, usdc))) == 19_500_000
    # the same proof again: nothing left to pay
    again = go(token(c, pay.pay_audience(REPO, 7, AUTHOR, "a" * 40)))
    assert not again["ok"] and again["why"].startswith("no bounty is in escrow for this issue") and "sigs" not in again   # refused before any fee
    # the author claims everything, in every mint, to one address
    wallet = Keypair().pubkey()
    r = go(token(c, pay.claim_audience(wallet), file="claim.yml", event_name="workflow_dispatch", actor_id=str(AUTHOR), repository_owner_id=str(AUTHOR)))
    assert r["ok"] and {x["amount"] for x in r["claimed"]} == {4_875_000, 19_500_000}, r
    assert c.balance(pay.ata(wallet, pay.faucet_mint())) == 4_875_000 and c.balance(pay.ata(wallet, usdc)) == 19_500_000
    # the token accounts were closed behind each step: the relayer's rent came back
    assert c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(token(c, "x")))) is None


def test_tests_mode_veto_settle_and_refund(env):
    c, ledger, jwks = env
    go = lambda jwt: relay.submit(ledger, c.payer, jwt, jwks, now=c.now())  # noqa: E731
    checks = bytes([9]) * 32
    c.warp(61)
    assert go(token(c, pay.fund_audience(8, 5 * USDC, pay.TESTS, checks, 3600, 600), file="fund.yml"))["ok"]
    r = go(token(c, pay.pay_audience(REPO, 8, AUTHOR, "b" * 40, checks, pay.TESTS)))
    assert r["ok"] and r["paid"][0]["waits"] == 600, r
    assert pay.read_job(c.data(pay.job_pda(REPO, 8))).state == "proven"
    assert relay.settle_due(ledger, c.payer, c.now()) == []
    # a maintainer's /knos veto
    r = go(token(c, pay.veto_audience(REPO, 8), file="fund.yml", event_name="issue_comment"))
    assert r["ok"] and r["vetoed"], r
    assert pay.read_job(c.data(pay.job_pda(REPO, 8))).vetoes == 1
    c.warp(5)
    assert go(token(c, pay.pay_audience(REPO, 8, AUTHOR, "d" * 40, checks, pay.TESTS)))["ok"]
    c.warp(600)
    assert len(relay.settle_due(ledger, c.payer, c.now())) == 1
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, pay.faucet_mint()))) == 4_875_000
    # an unproven job is refunded to the funding repository owner's GitHub id after its deadline
    c.warp(61)
    assert go(token(c, pay.fund_audience(9, 3 * USDC, pay.MERGE, pay.NO_CHECKS, 600, 0), file="fund.yml"))["ok"]
    assert relay.refund_due(ledger, c.payer, c.now()) == []
    c.warp(601)
    assert len(relay.refund_due(ledger, c.payer, c.now())) == 1
    assert pay.read_due(c.data(pay.due_pda(OWNER, pay.faucet_mint()))) == 3 * USDC


def test_a_new_github_key_arrives_by_githubs_own_attestation(env):
    c, ledger, jwks = env
    new = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    both = {oidc.GITHUB: jwks_of(signing_key(), new)}
    # a token signed by the new key cannot be verified yet: the chain does not trust the key
    claims = github_claims(aud=pay.fund_audience(11, USDC), iat=c.now(), exp=c.now() + 300, repository_id=str(REPO),
                           job_workflow_ref=f"{WF}/.github/workflows/fund.yml@refs/tags/v0.3.10", job_workflow_sha=SHA)
    early = sign_jwt(new, claims, header={"typ": "JWT", "alg": "RS256", "kid": "k1"})
    r = relay.submit(ledger, c.payer, early, both, now=c.now())
    assert not r["ok"] and "73" in r["why"], r
    # the rotate workflow's token, signed by a key the chain already has, names the new key
    att = token(c, oidc.rotate_audience(oidc.GITHUB, modulus(new)), event_name="schedule",
                job_workflow_ref="drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@refs/heads/main", job_workflow_sha="1" * 40)
    r = relay.submit(ledger, c.payer, att, both, now=c.now())
    assert r["ok"] and r["added"], r
    c.warp(61)
    claims.update(iat=c.now(), exp=c.now() + 300, jti="after")
    r = relay.submit(ledger, c.payer, sign_jwt(new, claims, header={"typ": "JWT", "alg": "RS256", "kid": "k1"}), both, now=c.now())
    assert r["ok"], r


def test_bad_tokens_are_reported_not_raised(env):
    c, ledger, jwks = env
    go = lambda jwt: relay.submit(ledger, c.payer, jwt, jwks, now=c.now())  # noqa: E731
    assert go(token(c, "sts.amazonaws.com"))["why"].startswith("not a Knos audience")
    assert go(token(c, pay.fund_audience(1, USDC), exp=c.now() - oidc.LATE - 1))["why"] == "token expired"
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = sign_jwt(stranger, json.loads(json.dumps(github_claims(aud=pay.pay_audience(REPO, 7, AUTHOR, "a" * 40), exp=c.now() + 300))),
                      header={"typ": "JWT", "alg": "RS256", "kid": "k0"})
    r = go(forged)
    assert not r["ok"] and r["why"] == "not from the workflow or the repository the audience names", r   # a read; no fee
    c.warp(61)
    assert go(token(c, pay.fund_audience(40, 5 * USDC), file="fund.yml"))["ok"]
    forged = sign_jwt(stranger, json.loads(json.dumps(github_claims(
        aud=pay.pay_audience(REPO, 40, AUTHOR, "a" * 40), iat=c.now(), exp=c.now() + 300, repository_id=str(REPO),
        job_workflow_ref=f"{WF}/.github/workflows/prove.yml@refs/tags/x", job_workflow_sha=SHA))), header={"typ": "JWT", "alg": "RS256", "kid": "k0"})
    lamports = c.svm.get_balance(c.payer.pubkey())
    r = go(forged)
    assert not r["ok"] and "70" in r["why"], r          # everything looks right, but the signature is not the issuer's
    assert c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(forged))) is None        # and the token account was closed
    assert lamports - c.svm.get_balance(c.payer.pubkey()) < 100_000                      # so the relayer lost fees only
    # someone else's workflow asks GitHub (validly) for a Knos audience: refused by reads, no transaction
    n0 = ledger.n
    other = token(c, pay.pay_audience(REPO, 40, AUTHOR, "a" * 40), job_workflow_ref="evil/repo/.github/workflows/prove.yml@refs/heads/main")
    assert go(other)["why"] == "no open bounty on this issue pins this workflow at this commit" and ledger.n == n0
    assert go(token(c, pay.pay_audience(REPO, 40, AUTHOR, "a" * 40), runner_environment="self-hosted"))["why"] == "not from a GitHub-hosted runner"
    # another amount for an issue that is funded (the very token that funded it would be "already done")
    assert go(token(c, pay.fund_audience(40, 6 * USDC), file="fund.yml"))["why"] == "this issue already has the repository's bounty"
    assert go(token(c, pay.fund_audience(41, 5 * USDC), file="fund.yml"))["why"] == "an older fund token than the repository's last one"
    c.warp(1)
    n0 = ledger.n
    again = go(token(c, pay.fund_audience(41, 5 * USDC), file="fund.yml"))
    assert again == {"ok": False, "kind": "fund", "why": "one funding per repository per minute", "retry": True}
    assert ledger.n == n0
    nothing = go(token(c, pay.claim_audience(Keypair().pubkey()), event_name="workflow_dispatch", actor_id="31", repository_owner_id="31"))
    assert nothing["why"] == "nothing is due to this GitHub account" and ledger.n == n0
    not_owner = go(token(c, pay.claim_audience(Keypair().pubkey()), event_name="workflow_dispatch", actor_id=str(AUTHOR), repository_owner_id="99"))
    assert "by the owner of the repository" in not_owner["why"]
    assert not go("not.a.jwt")["ok"]


def test_the_worker_pass_relays_oldest_first_retries_the_rate_limit_and_cranks(env, monkeypatch, tmp_path):
    """ghrelay.once(): what `knos relay` runs every 10 seconds. Two bounties funded seconds apart in one repository
    are found newest first; both end up funded, in GitHub's order. A payment whose window has passed is released."""
    import time

    from knos.proof import ghrelay
    c, ledger, jwks = env
    c.warp(120)
    first = token(c, pay.fund_audience(51, 5 * USDC, review_s=600), file="fund.yml")
    c.warp(3)
    second = token(c, pay.fund_audience(52, 5 * USDC), file="fund.yml")
    comments = {"octo/widgets": [("fund", 52, second, "github-actions[bot]"), ("fund", 51, first, "github-actions[bot]")]}
    logged: list[str] = []
    monkeypatch.setattr(ghrelay, "discover", lambda since, state: set(comments))
    monkeypatch.setattr(ghrelay, "found", lambda repo, since: comments[repo])
    monkeypatch.setattr(ghrelay, "post_log", logged.extend)
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setattr(ghrelay, "relay_one", lambda ledger, payer, kind, jwt: ghrelay.__dict__["_relay_one"](ledger, payer, kind, jwt))
    monkeypatch.setitem(ghrelay.__dict__, "_relay_one", lambda ledger, payer, kind, jwt: _noted(relay.submit(ledger, payer, jwt, jwks, now=c.now())))

    def _noted(r):
        if r.get("ok"):
            r["note"] = ghrelay.note(r)
        return r
    lines = ghrelay.once(ledger, c.payer, now=time.time())
    assert len(lines) == 1 and " octo/widgets#51 " in lines[0] and " ok " in lines[0]      # the older one, first
    assert pay.read_job(c.data(pay.job_pda(REPO, 51))).state == "open" and c.data(pay.job_pda(REPO, 52)) is None
    assert ghrelay.once(ledger, c.payer, now=time.time()) == []                              # still inside the minute
    c.warp(61)
    lines = ghrelay.once(ledger, c.payer, now=time.time())
    assert len(lines) == 1 and " octo/widgets#52 " in lines[0] and " ok " in lines[0]      # retried, not lost
    assert ghrelay.once(ledger, c.payer, now=time.time()) == []                              # each token once
    # a merge proof for #51 (held 10 minutes), then the crank releases it when the window has passed
    comments["octo/widgets"] = [("proof", 9, token(c, pay.pay_audience(REPO, 51, AUTHOR, "b" * 40)), "github-actions[bot]")]
    due0 = pay.read_due(c.data(pay.due_pda(AUTHOR, pay.faucet_mint())))
    lines = ghrelay.once(ledger, c.payer, now=time.time())
    assert "will be released in 600 s" in lines[0] and pay.read_job(c.data(pay.job_pda(REPO, 51))).state == "proven"
    c.warp(601)
    lines = ghrelay.once(ledger, c.payer, now=time.time())
    assert lines == [next(x for x in lines if x.startswith("knos-relay settle"))]
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, pay.faucet_mint()))) == due0 + 4_875_000
    assert logged and all(x.startswith("knos-relay ") for x in logged)


def test_a_dropped_transaction_is_tried_again_and_a_second_relayer_does_no_harm(env, monkeypatch, tmp_path):
    """What broke on devnet in 0.3.10: two runs carried the same proof at once and both gave up, so the payment waited
    for a fresh token. A failure that says nothing about the token is retried on the next pass; a relayer with its own
    key has its own token account; and whoever comes second finds the work done."""
    import time

    from solders.keypair import Keypair

    from knos import chain
    from knos.proof import ghrelay
    c, ledger, jwks = env
    c.warp(120)
    fund = token(c, pay.fund_audience(61, 5 * USDC), file="fund.yml")
    assert relay.submit(ledger, c.payer, fund, jwks, now=c.now())["ok"]
    # a second relayer with the same fund token finds the bounty already open: done, and nothing to send
    again = relay.submit(ledger, Keypair(), fund, jwks, now=c.now())
    assert again["ok"] and again["already"] and again["sigs"] == [] and again["job"] == str(pay.job_pda(REPO, 61))
    assert ghrelay.log_line("fund", "octo/widgets", 61, fund, {**again, "note": ghrelay.note(again)}).endswith("(another relayer carried it first)")
    proof = token(c, pay.pay_audience(REPO, 61, AUTHOR, "c" * 40))

    class Flaky:
        """The ledger, but the next `fails` sends are refused the way a twin run's interference looks on chain."""
        def __init__(self, fails): self.fails = fails
        def __getattr__(self, name): return getattr(ledger, name)
        def send(self, ixs, payer, signers=None):
            if self.fails:
                self.fails -= 1
                raise chain.RpcError("transaction failed: {'InstructionError': [1, {'Custom': 69}]}")
            return ledger.send(ixs, payer)
    first = relay.submit(Flaky(1), c.payer, proof, jwks, now=c.now())
    assert first == {"ok": False, "why": first["why"], "retry": True, "transient": True, "answered": True} and "'Custom': 69" in first["why"]
    assert not relay.transient(chain.RpcError("transaction failed: {'InstructionError': [0, {'Custom': 86}]}"))   # a real refusal
    assert relay.transient(TimeoutError("sig not confirmed within 60s"))

    comments = {"octo/widgets": [("proof", 9, proof, "github-actions[bot]")]}
    monkeypatch.setattr(ghrelay, "discover", lambda since, state: set(comments))
    monkeypatch.setattr(ghrelay, "found", lambda repo, since: comments[repo])
    monkeypatch.setattr(ghrelay, "post_log", lambda lines: None)
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    flaky = Flaky(2)

    def one(_ledger, payer, kind, jwt):
        r = relay.submit(flaky, payer, jwt, jwks, now=c.now())
        if r.get("ok"):
            r["note"] = ghrelay.note(r)
        return r
    monkeypatch.setattr(ghrelay, "relay_one", one)
    assert ghrelay.once(ledger, c.payer, now=time.time()) == []                 # dropped: no verdict yet, nothing logged
    assert ghrelay.once(ledger, c.payer, now=time.time()) == []
    lines = ghrelay.once(ledger, c.payer, now=time.time())
    assert len(lines) == 1 and " ok " in lines[0]                              # third pass: paid
    assert c.data(pay.job_pda(REPO, 61)) is None and pay.read_due(c.data(pay.due_pda(AUTHOR, pay.faucet_mint()))) >= 4_875_000
    assert json.loads((tmp_path / "ghrelay.json").read_text())["tries"] == {}

    # a second relayer, with a key of its own, arrives late with the same proof: refused by a read, at no cost
    other = Keypair()
    c.airdrop(other.pubkey(), 10**9) if hasattr(c, "airdrop") else c.svm.airdrop(other.pubkey(), 10**9)
    late = relay.submit(ledger, other, proof, jwks, now=c.now())
    assert late == {"ok": False, "kind": "pay", "why": "no bounty is in escrow for this issue (never funded, or already paid or refunded)"}

    # waiting out the one-funding-per-minute limit is not a failure, however many passes it takes
    waits = {"n": 0}

    def limited(_ledger, payer, kind, jwt):
        waits["n"] += 1
        return {"ok": False, "kind": "fund", "why": "one funding per repository per minute", "retry": True}
    monkeypatch.setattr(ghrelay, "relay_one", limited)
    monkeypatch.setattr(ghrelay, "MAX_TRIES", 2)
    comments["octo/widgets"] = [("fund", 63, token(c, pay.fund_audience(63, 5 * USDC), file="fund.yml"), "github-actions[bot]")]
    assert [ghrelay.once(ledger, c.payer, now=time.time()) for _ in range(5)] == [[]] * 5 and waits["n"] == 5
    monkeypatch.setattr(ghrelay, "relay_one", one)
    # a failure that never clears is given up on, out loud
    monkeypatch.setattr(ghrelay, "MAX_TRIES", 2)
    c.warp(61)
    comments["octo/widgets"] = [("fund", 62, token(c, pay.fund_audience(62, 5 * USDC), file="fund.yml"), "github-actions[bot]")]
    flaky.fails = 99
    # on the chain's clock the token is good for another hour and more: the program's refusal ends it all the same
    assert ghrelay.expires(comments["octo/widgets"][0][2]) > c.now() + 3600
    assert ghrelay.once(ledger, c.payer, now=c.now()) == []
    lines = ghrelay.once(ledger, c.payer, now=c.now())
    assert len(lines) == 1 and " fail " in lines[0] and "gave up after 2 passes" in lines[0]


def test_captured_tokens_replay_in_order_with_the_clock_set_to_each(tmp_path):
    """scripts/replay_tokens.py: real tokens against real builds, before anything is deployed."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import replay_tokens
    from _settle import FIX

    def at(t: int, aud: str, file: str, **over) -> str:
        claims = github_claims(aud=aud, iat=t, nbf=t - 600, exp=t + 300, jti=f"x{t}", repository_id=str(REPO),
                               repository_owner_id=str(OWNER), job_workflow_ref=f"{WF}/.github/workflows/{file}@{SHA}",
                               job_workflow_sha=SHA)
        claims.update(over)
        return sign_jwt(signing_key(), claims, header={"typ": "JWT", "alg": "RS256", "kid": "k0"})

    t0 = 1_800_000_000
    dest = Keypair().pubkey()
    tokens = [at(t0, pay.fund_audience(31, 20 * USDC), "fund.yml", actor_id=str(OWNER)),
              at(t0 + 4000, pay.pay_audience(REPO, 31, AUTHOR, "d" * 40), "prove.yml"),
              at(t0 + 9000, pay.claim_audience(dest), "claim.yml", actor_id=str(AUTHOR), repository_owner_id=str(AUTHOR),
                 event_name="workflow_dispatch")]
    said: list[str] = []
    jwks = {oidc.GITHUB: jwks_of(signing_key())}
    assert replay_tokens.replay(tokens, FIX / "knos_oidc_test.so", FIX / "knos_pay_test.so", jwks, said.append), said
    assert sum(x.startswith("ok  ") for x in said) == 3 and any("Sent 19.50" in x for x in said), said
    bad = [at(t0, pay.pay_audience(REPO, 99, AUTHOR, "d" * 40), "prove.yml")]          # no such bounty
    said.clear()
    assert not replay_tokens.replay(bad, FIX / "knos_oidc_test.so", FIX / "knos_pay_test.so", jwks, said.append)
    assert any(x.startswith("FAIL") for x in said)


def test_knos_claim_does_the_five_steps_with_gh_and_waits_for_the_money(env):
    """`knos claim --v1 <address>`: the repository, the workflow file, the run and the wait, with nothing but a gh login."""
    import base64 as b64mod

    from knos import claim as claiming
    c, ledger, jwks = env
    c.warp(200)
    wallet = Keypair().pubkey()
    assert relay.submit(ledger, c.payer, token(c, pay.fund_audience(71, 20 * USDC), file="fund.yml"), jwks, now=c.now())["ok"]
    assert relay.submit(ledger, c.payer, token(c, pay.pay_audience(REPO, 71, AUTHOR, "d" * 40)), jwks, now=c.now())["ok"]
    calls, said, have = [], [], set()
    waiting = pay.read_due(c.data(pay.due_pda(AUTHOR, pay.faucet_mint())))     # this bounty's 19.50 and any earlier test's
    assert waiting >= 19_500_000

    def gh(*args, inp=None):
        calls.append(args)
        if args[:2] == ("api", "user"):
            return json.dumps({"login": "mona", "id": AUTHOR})
        if args[0] == "api" and args[1].startswith("repos/") and "-X" not in args:
            if args[1] not in have:
                raise claiming.Cannot("HTTP 404")
            return "{}"
        if args[:2] == ("repo", "create"):
            have.add(f"repos/{args[2]}")
            return ""
        if args[:3] == ("api", "-X", "PUT"):
            assert b64mod.b64decode(json.loads(inp)["content"]) == claiming.TEMPLATE_V1.read_bytes() and args[3].endswith(claiming.WORKFLOW_V1)
            have.add(args[3])
            return "{}"
        if args[:2] == ("workflow", "run"):
            # GitHub signs; the relayer carries it: here, at once
            r = relay.submit(ledger, c.payer, token(c, pay.claim_audience(wallet), file="knos-claim.yml", event_name="workflow_dispatch",
                                                    actor_id=str(AUTHOR), repository_owner_id=str(AUTHOR)), jwks, now=c.now())
            assert r["ok"], r
            return ""
        raise AssertionError(args)
    got = claiming.claim(str(wallet), gh=gh, ledger=ledger, say=said.append, sleep=lambda s: None)
    assert got["arrived"] and got["created"] and got["repo"] == "mona/knos-claim" and got["due"][0][1] == waiting
    assert said[0] == f"{waiting / 1e6:,.2f} USDC is waiting for mona." and said[-1] == f"Sent {waiting / 1e6:,.2f} USDC to {wallet}."
    assert ("workflow", "run", "knos-claim-v1.yml", "-R", "mona/knos-claim", "-f", f"address={wallet}") in calls
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, pay.faucet_mint()))) == 0
    # nothing due: it says so before touching GitHub any further; a repository someone else owns is refused; so is a bad address
    calls.clear()
    with pytest.raises(claiming.Cannot, match="Nothing is waiting for mona"):
        claiming.claim(str(wallet), gh=gh, ledger=ledger, say=said.append, sleep=lambda s: None)
    assert calls == [("api", "user")]
    with pytest.raises(claiming.Cannot, match="not a Solana address"):
        claiming.claim("0xabc", gh=gh, ledger=ledger)
    # the first deployment's claim workflow has a file of its own (it asks GitHub for a `knos:claim:` token); the one
    # `knos claim` installs for the second deployment is the example, byte for byte
    assert b"audience=knos:claim:$ADDRESS" in claiming.TEMPLATE_V1.read_bytes()
    assert claiming.TEMPLATE.read_bytes() == (ROOT / "examples" / "knos-claim.yml").read_bytes()
