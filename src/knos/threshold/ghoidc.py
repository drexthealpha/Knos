"""Referee host 2 (GitHub Actions) proves who it is with a GitHub Actions OIDC token: no founder-made token anywhere.

.github/workflows/referee.yml runs on a cron (every 5 minutes) and on workflow_dispatch with `permissions: id-token:
write`. It also has a repository_dispatch trigger (host 1 wakes it when a session opens), but EVENTS leaves that event
out, so the posts of a run started that way are refused (docs/reference/REFEREE_FROST.md says so). For every post to
the app server it asks the runner for a fresh ID token (audience AUDIENCE) and sends it with the post; the app server (knos_wanted.referee) verifies it here before it accepts host 2's commitments or share:

    RS256 under a key of GitHub's published JWKS (the issuer's discovery document -> jwks_uri)
    iss              https://token.actions.githubusercontent.com
    aud              knos-referee
    exp / nbf / iat  in time (60 s skew)
    repository       drexthealpha/Knos, repository_id 1353152983, repository_owner_id 142920951 (a renamed or
                     re-created repository of the same name has another id)
    workflow_ref     drexthealpha/Knos/.github/workflows/referee.yml@refs/heads/main (and job_workflow_ref the same)
    ref              refs/heads/main;  event_name schedule or workflow_dispatch

The post is still signed with host 2's transport key as well (knos.threshold.auth): the token says the post comes
from that workflow on main; the transport signature binds it to this session and this body.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

from .attest import _b64, _rsa_verify

ISSUER = "https://token.actions.githubusercontent.com"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
AUDIENCE = "knos-referee"
REPOSITORY = "drexthealpha/Knos"
REPOSITORY_ID = "1353152983"            # gh api repos/drexthealpha/Knos (read 18 Oct 2026)
OWNER_ID = "142920951"
WORKFLOW_REF = f"{REPOSITORY}/.github/workflows/referee.yml@refs/heads/main"
EVENTS = ("schedule", "workflow_dispatch")
GH_HOST = 2                             # knos.threshold.HOSTS[2] == "gh"
SKEW_S = 60
KEYS_TTL_S = 3600

_keys: dict = {"at": 0.0, "set": None}
_keys_lock = threading.Lock()


class GithubOidcError(PermissionError):
    pass


def jwks(fetch=None) -> dict:
    """GitHub's signing keys: discovery document -> jwks_uri -> keys (cached for an hour; re-read on an unknown kid)."""
    get = fetch or (lambda u: json.loads(urllib.request.urlopen(u, timeout=10).read()))  # noqa: S310 - fixed https URLs
    disc = get(DISCOVERY)
    if disc.get("issuer") != ISSUER:
        raise GithubOidcError("the discovery document names another issuer")
    return get(disc["jwks_uri"])


def _cached_keys(kid: str, fetch=None) -> dict:
    with _keys_lock:
        ks = _keys["set"]
        fresh = time.time() - _keys["at"] < KEYS_TTL_S
        if ks is None or not fresh or not any(k.get("kid") == kid for k in ks.get("keys", [])):
            ks = jwks(fetch)
            _keys.update(at=time.time(), set=ks)
        return ks


def verify(token: str, *, keys: dict | None = None, now: float | None = None, audience: str = AUDIENCE,
           repository: str = REPOSITORY, repository_id: str = REPOSITORY_ID, owner_id: str = OWNER_ID,
           workflow_ref: str = WORKFLOW_REF, fetch=None) -> dict:
    """The token's claims when every check passes; GithubOidcError naming the first one that fails."""
    try:
        h64, p64, s64 = str(token).split(".")
        head, claims, sig = json.loads(_b64(h64)), json.loads(_b64(p64)), _b64(s64)
    except (ValueError, AttributeError, TypeError):
        raise GithubOidcError("github oidc: not a JWT") from None
    if head.get("alg") != "RS256":
        raise GithubOidcError("github oidc: the token is not RS256")
    keyset = keys if keys is not None else _cached_keys(str(head.get("kid")), fetch)
    jwk = next((k for k in keyset.get("keys", []) if k.get("kid") == head.get("kid")), None)
    if jwk is None or not _rsa_verify(jwk, f"{h64}.{p64}".encode(), sig):
        raise GithubOidcError("github oidc: the signature does not verify with GitHub's published key")
    t = time.time() if now is None else now
    if claims.get("iss") != ISSUER:
        raise GithubOidcError("github oidc: iss is not GitHub Actions")
    aud = claims.get("aud")
    if (aud if isinstance(aud, list) else [aud]) != [audience]:
        raise GithubOidcError("github oidc: aud is not " + audience)
    if not (claims.get("exp", 0) + SKEW_S > t >= claims.get("nbf", claims.get("iat", t + 10 * SKEW_S)) - SKEW_S):
        raise GithubOidcError("github oidc: the token is expired or not yet valid")
    if claims.get("repository") != repository or str(claims.get("repository_id")) != repository_id \
            or str(claims.get("repository_owner_id")) != owner_id:
        raise GithubOidcError("github oidc: not the repository " + repository)
    if claims.get("workflow_ref") != workflow_ref or claims.get("job_workflow_ref", workflow_ref) != workflow_ref:
        raise GithubOidcError("github oidc: not " + workflow_ref)
    if claims.get("ref") != "refs/heads/main":
        raise GithubOidcError("github oidc: not the main branch")
    if claims.get("event_name") not in EVENTS:
        raise GithubOidcError("github oidc: event_name is not schedule or workflow_dispatch")
    return claims


def request_token(audience: str = AUDIENCE, env=None, opener=None) -> str:
    """Inside a GitHub Actions job with `id-token: write`: a fresh ID token for `audience` (never printed)."""
    env = os.environ if env is None else env
    url, bearer = env.get("ACTIONS_ID_TOKEN_REQUEST_URL"), env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not bearer:
        raise GithubOidcError("not in a GitHub Actions job with permissions id-token: write")
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(url + sep + "audience=" + urllib.parse.quote(audience),
                                 headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json",
                                          "User-Agent": "knos-referee-frost"})
    with (opener or urllib.request.urlopen)(req, timeout=15) as r:  # noqa: S310 - the runner's own https endpoint
        return json.loads(r.read())["value"]
