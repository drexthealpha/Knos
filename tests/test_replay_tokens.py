"""scripts/replay_tokens.py: the token file's format, how tokens get into it, and the replay that verifies each one on
the verifier's own code with the clock at its `iat`. The tokens here are signed by the test keys and verified by the
test build of knos-oidc, which trusts them; the released build trusts GitHub's keys only, so a real file can only be
replayed against it with tokens GitHub signed. GitHub's API and the key-set endpoint are fakes."""
from __future__ import annotations

import base64
import json
import sys

import pytest

pytest.importorskip("solders.litesvm")

from _settle import FIX, NOW, b64, github_claims, gitlab_claims, modulus, sign_jwt, signing_key  # noqa: E402

from knos.proof import ghrelay  # noqa: E402
from knos.settle.v2 import oidc, pay  # noqa: E402

sys.path.insert(0, str(FIX.parents[1] / "scripts"))
import drills  # noqa: E402
import replay_tokens  # noqa: E402

BUILD = FIX / "knos_oidc_v2_test.so"
TERMS = pay.terms_json({"checks": [], "mode": "merge", "v": 1})
DAY = 86_400


def jwks(bits: int, kid: str) -> dict:
    return {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": kid, "n": b64(oidc.modulus_bytes(modulus(signing_key(bits))))}]}


GH, GL = jwks(2048, "gh-1"), jwks(4096, "gl-1")


def github(iat: int, repo: str = "octo/widgets", aud: str = "knos2:pay:1:2:3", **over) -> str:
    claims = github_claims(aud=aud, iat=iat, nbf=iat - 600, exp=iat + 300, jti=f"t{iat}{repo}", repository=repo, **over)
    return sign_jwt(signing_key(), claims, header={"typ": "JWT", "alg": "RS256", "kid": "gh-1"})


def gitlab(iat: int) -> str:
    return sign_jwt(signing_key(4096), gitlab_claims(aud="knos-verify", iat=iat, nbf=iat - 5, exp=iat + 300), header={"typ": "JWT", "alg": "RS256", "kid": "gl-1"})


def spoiled(jwt: str) -> str:
    head, body, sig = jwt.split(".")
    return f"{head}.{body}.{sig[:20]}{'A' if sig[20] != 'A' else 'B'}{sig[21:]}"


def write(path, rows: list[tuple[str, dict]]):
    path.write_text("".join(json.dumps({"token": jwt, "jwks": doc}) + "\n" for jwt, doc in rows), encoding="utf-8")
    return path


def comment(number: int, body: str, created: str = "2026-10-03T10:00:00Z") -> dict:
    return {"issue_url": f"https://api.github.com/repos/octo/widgets/issues/{number}", "body": body, "created_at": created, "user": {"login": "github-actions[bot]"}}


def test_every_token_is_verified_on_chain_code_with_the_clock_at_its_issue_time(tmp_path):
    """Tokens of two repositories and two issuers, issued over 40 days: each is written and stepped under the key of
    its day, and the counts are by repository and by key."""
    rows = [(github(NOW), GH), (github(NOW + 3 * DAY), GH), (github(NOW + 40 * DAY, "octo/gadgets"), GH), (gitlab(NOW + DAY), GL),
            (github(NOW - 400 * DAY, "octo/gadgets"), GH)]                           # long expired by any clock but its own
    said: list[str] = []
    good, by_repo, by_key = replay_tokens.verify(drills.corpus(write(tmp_path / "t.jsonl", rows)), {"knos_oidc": BUILD.read_bytes()}, said.append)
    assert (good, said) == (5, [])
    assert by_repo == {"octo/widgets": 2, "octo/gadgets": 2, "my-group/my-project": 1}
    assert sorted(by_key.values()) == [1, 4] and {k.split(" (")[0] for k in by_key} == {"token.actions.githubusercontent.com 2048-bit key gh-1", "gitlab.com 4096-bit key gl-1"}


def test_a_token_that_does_not_verify_is_said_and_the_run_exits_1(tmp_path):
    stranger = jwks(4096, "gh-1")                                                    # a key set that names another key under the token's kid
    rows = [(github(NOW), GH), (spoiled(github(NOW + 1)), GH), (github(NOW + 2), stranger), (github(NOW + 3), {"keys": []}),
            (sign_jwt(signing_key(4096), github_claims(iat=NOW + 4, exp=NOW + 304), header={"typ": "JWT", "alg": "RS256", "kid": "gl-1"}), GL)]
    said: list[str] = []
    path = write(tmp_path / "t.jsonl", rows)
    assert replay_tokens.main(["--corpus", str(path), "--oidc", str(BUILD)], say=said.append) == 1
    fails = [s for s in said if s.startswith("FAIL")]
    assert len(fails) == 4 and "1 of 5 tokens verified" in "\n".join(said)
    assert fails[0].endswith("the key its header names did not sign it") and fails[1].endswith("the key its header names did not sign it")
    assert "is not in the key set captured with it" in fails[2]
    assert "is not one this build takes with no attestation" in fails[3]             # GitLab's test key, offered as a GitHub key
    assert replay_tokens.main(["--corpus", str(write(tmp_path / "none.jsonl", [])), "--oidc", str(BUILD)], say=said.append) == 1     # nothing verified is not a pass


def test_the_default_verifier_is_the_one_the_cluster_holds(tmp_path):
    from test_drills import Rpc
    rpc, said = Rpc(), []
    path = write(tmp_path / "t.jsonl", [(github(NOW), GH), (github(NOW + 60, "octo/gadgets"), GH)])
    assert replay_tokens.main(["--corpus", str(path), "--rpc", "http://cluster"], call=rpc, say=said.append) == 0
    assert said[0].startswith(f"knos_oidc {pay.IDS['knos_oidc']} as http://cluster holds it, sha256 with trailing zeros trimmed {drills.mc.elf_hash(BUILD.read_bytes())}")
    assert said[1] == "2 of 2 tokens verified on chain code, each with the clock at its issue time and the key set of its day"
    assert said[2] == "  by repository: octo/gadgets 1; octo/widgets 1" and said[3].startswith("  by key: token.actions.githubusercontent.com 2048-bit key gh-1 (sha256 ")


def test_capture_keeps_only_tokens_a_published_key_signed_with_the_key_set_and_the_terms(tmp_path):
    fund = github(NOW + 10, aud=pay.fund_audience(7, 5_000_000, pay.MERGE, pay.terms_hash(TERMS), pay.faucet_balance_pda(424242)))
    proof, old, forged = github(NOW + 500), sign_jwt(signing_key(), github_claims(iat=NOW - 900, exp=NOW - 600), header={"alg": "RS256", "kid": "rotated-out"}), spoiled(github(NOW + 7))
    comments = [comment(9, ghrelay.token_comment("proof", proof)), comment(7, ghrelay.token_comment("fund", fund, TERMS)),
                comment(7, ghrelay.token_comment("proof", forged)), comment(7, ghrelay.token_comment("proof", old)),
                comment(7, "thanks! knos-proof: not.a.token"), comment(3, ghrelay.token_comment("proof", github(NOW - 5 * DAY)), "2026-09-01T00:00:00Z")]
    asked: list[str] = []

    def getter(path: str):
        asked.append(path)
        return comments

    said: list[str] = []
    rows = replay_tokens.capture("octo/widgets", "2026-10-01", getter, lambda issuer: {oidc.GITHUB: GH, oidc.GITLAB: GL}[issuer], said.append)
    assert asked == ["repos/octo/widgets/issues/comments?sort=created&direction=desc&per_page=100"]
    assert [(r["kind"], r["source"], r.get("terms")) for r in rows] == [("fund", "https://github.com/octo/widgets/issues/7", TERMS.decode()),
                                                                        ("proof", "https://github.com/octo/widgets/issues/9", None)]     # oldest first
    assert all(r["jwks"] == GH and r["posted"] == "2026-10-03T10:00:00Z" for r in rows)
    assert said == ["octo/widgets: 2 tokens a published key signed; 2 left out (no key of the issuer's set signed them)"]
    # the file: one token a line, appended once however often the capture runs, and readable by the replay and by the drills
    path = tmp_path / "tokens.jsonl"
    assert (replay_tokens.append(path, rows), replay_tokens.append(path, rows)) == (2, 0)
    got = drills.corpus(path)
    assert [(t.kind, t.terms, t.kid, t.c["repository"]) for t in got] == [("fund", TERMS, "gh-1", "octo/widgets"), ("pay", None, "gh-1", "octo/widgets")]
    assert replay_tokens.verify(got, {"knos_oidc": BUILD.read_bytes()}, said.append)[0] == 2


def test_a_token_whose_key_the_issuer_no_longer_publishes_is_kept_with_the_key_set_committed_on_2_oct(tmp_path, monkeypatch):
    committed = tmp_path / "github.json"
    committed.write_text(json.dumps(jwks(2048, "gh-old")), encoding="utf-8")
    monkeypatch.setitem(replay_tokens.FIXTURES, oidc.GITHUB, committed)
    jwt = sign_jwt(signing_key(), github_claims(iat=NOW, exp=NOW + 300), header={"alg": "RS256", "kid": "gh-old"})
    rows = replay_tokens.capture("octo/widgets", "", lambda path: [comment(1, ghrelay.token_comment("proof", jwt))], lambda issuer: {"keys": []}, lambda line: None)
    assert [r["jwks"]["keys"][0]["kid"] for r in rows] == ["gh-old"]


def test_the_command_line_captures_into_a_file_and_says_how_many(tmp_path):
    out, said = tmp_path / "tokens.jsonl", []
    body = ghrelay.token_comment("proof", github(NOW))
    monkey = lambda issuer: GH  # noqa: E731
    replay_tokens.relay.fetch_jwks, kept = monkey, replay_tokens.relay.fetch_jwks
    try:
        assert replay_tokens.main(["--capture", "octo/widgets", "--out", str(out)], getter=lambda path: [comment(4, body)], say=said.append) == 0
    finally:
        replay_tokens.relay.fetch_jwks = kept
    assert said[-1] == f"1 new tokens appended to {out}" and base64.urlsafe_b64decode(json.loads(out.read_text())["token"].split(".")[0] + "==")
