"""`knos keys` says what each key is: "ready" only for a key the verifier would accept now; for any other, why not and
when it can be used. It ends 0 when the only keys that cannot be used are another issuer's waiting out their delay."""
from __future__ import annotations

import base64

import pytest

from knos import cli
from knos.settle import relay as relay1
from knos.settle.v2 import oidc
from knos.settle.v2 import relay as relay2

NOW = 1_790_000_000
N_GITHUB, N_GITLAB = (1 << 2047) + 11, (1 << 2047) + 22


def jwk(n: int, kid: str) -> dict:
    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid, "e": "AQAB",
            "n": base64.urlsafe_b64encode(n.to_bytes(256, "big")).rstrip(b"=").decode()}


def key(issuer: int, *, state: int = 1, active_at: int = NOW - 3600, expires_at: int = NOW + 29 * 86_400, approved: bool = True,
        revoked: bool = False, genesis: bool = False) -> oidc.Key:
    return oidc.Key(state=state, issuer=issuer, bits=2048, active_at=active_at, expires_at=expires_at, approved=approved, revoked=revoked, genesis=genesis)


@pytest.fixture
def keys(monkeypatch, capsys):
    """`knos keys` over these keys (GitHub's N_GITHUB, GitLab's N_GITLAB; None: not on chain)."""
    class Ledger:
        def now(self):
            return NOW

    def run(github: oidc.Key | None, gitlab: oidc.Key | None) -> tuple[int, list[str]]:
        held = [(oidc.key_pda(i, n), k, n) for i, n, k in ((oidc.GITHUB, N_GITHUB, github), (oidc.GITLAB, N_GITLAB, gitlab)) if k]
        monkeypatch.setattr(cli, "_ledger", lambda: Ledger())
        monkeypatch.setattr(relay2, "keys", lambda ledger: held)
        monkeypatch.setattr(relay1, "fetch_jwks", lambda issuer: {"keys": [jwk({oidc.GITHUB: N_GITHUB, oidc.GITLAB: N_GITLAB}[issuer], "kid")]})
        capsys.readouterr()
        rc = cli.main(["keys"])
        return rc, capsys.readouterr().out.splitlines()
    return run


def test_a_key_that_cannot_be_used_yet_is_not_ready_and_says_when(keys):
    rc, lines = keys(key(oidc.GITHUB, genesis=True), key(oidc.GITLAB, active_at=NOW + 3 * 3600))
    gitlab = next(x for x in lines if x.startswith("GitLab"))
    assert "  ready  " not in gitlab and f"not usable yet: approved, usable from {cli._when(NOW + 3 * 3600)}" in gitlab, gitlab
    assert next(x for x in lines if x.startswith("GitHub")).split("  ")[2] == "ready"
    # and the command does not call that a fault: GitHub's keys all verify
    assert rc == 0
    assert lines[-2] == f"GitLab's key kid is waiting out its delay: it can be used from {cli._when(NOW + 3 * 3600)}."
    assert lines[-1] == "Every key GitHub publishes today (1) verifies on chain. 1 of another issuer's is waiting out its delay, as listed above."


def test_a_new_key_not_yet_approved_says_both_things_it_waits_for(keys):
    rc, lines = keys(key(oidc.GITHUB, genesis=True), key(oidc.GITLAB, approved=False, active_at=NOW + 86_400))
    gitlab = next(x for x in lines if x.startswith("GitLab"))
    assert f"not usable yet: the guardian has not approved it, and its delay ends {cli._when(NOW + 86_400)}" in gitlab
    assert rc == 0 and "once the guardian has approved it." in lines[-2]
    # past its delay and still not approved: that is the guardian's to do, and it is a fault until done
    rc, lines = keys(key(oidc.GITHUB, genesis=True), key(oidc.GITLAB, approved=False))
    assert "not usable yet: the guardian has not approved it" in next(x for x in lines if x.startswith("GitLab")) and rc == 1


def test_a_github_key_that_cannot_be_used_fails_even_when_it_is_only_waiting(keys):
    rc, lines = keys(key(oidc.GITHUB, active_at=NOW + 3600), key(oidc.GITLAB))
    assert rc == 1 and "not usable yet: approved, usable from" in next(x for x in lines if x.startswith("GitHub"))
    assert lines[-1].startswith("GitHub's key kid: ") and "waiting out" not in " ".join(lines)


@pytest.mark.parametrize("gitlab, said, rc", [
    (key(oidc.GITLAB), "ready", 0),
    (key(oidc.GITLAB, state=0), "registered, its parameters not sent yet (anyone can send them)", 1),
    (key(oidc.GITLAB, revoked=True), "revoked, never usable again", 1),
    (key(oidc.GITLAB, expires_at=NOW - 60), f"expired {cli._when(NOW - 60)}", 1),
    (None, None, 1),
])
def test_every_other_state_is_worded_and_fails_unless_ready(keys, gitlab, said, rc):
    got, lines = keys(key(oidc.GITHUB, genesis=True), gitlab)
    assert got == rc
    if said:
        assert next(x for x in lines if x.startswith("GitLab")).split("  ")[2] == said
    else:
        assert lines[-1].startswith("GitLab's key kid: this signing key is not on chain yet")


def test_a_403_from_github_gets_the_rate_limit_hint_wherever_github_is_asked(monkeypatch):
    import io
    import urllib.error

    from knos import ghwords

    def refusing(code):
        def urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, "rate limit exceeded", {}, io.BytesIO(b""))
        return urlopen
    for code in (403, 429):
        monkeypatch.setattr(cli.urllib.request, "urlopen", refusing(code))
        with pytest.raises(cli.Stop) as stopped:
            cli._github("users/mona")
        assert stopped.value.said == f"GitHub refused users/mona (HTTP {code}); set GH_TOKEN to lift its rate limit."
    monkeypatch.setattr(cli.urllib.request, "urlopen", refusing(404))
    with pytest.raises(cli.Stop, match="GitHub has nothing at users/mona."):
        cli._github("users/mona")
    monkeypatch.setattr(cli.urllib.request, "urlopen", refusing(502))
    with pytest.raises(cli.Stop, match="GitHub did not answer for users/mona: HTTP Error 502"):
        cli._github("users/mona")
    # the same words from a wrapper that only kept the status in its message, and from the MCP server
    assert ghwords.failed("repos/o/r", OSError("HTTP 403 for repos/o/r")) == "GitHub refused repos/o/r (HTTP 403); set GH_TOKEN to lift its rate limit."
    assert ghwords.failed("repos/o/r", OSError("connection refused\nTraceback ...")) == "GitHub did not answer for repos/o/r: connection refused."
