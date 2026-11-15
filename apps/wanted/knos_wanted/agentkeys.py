"""Agent keys: a capped, revocable credential a signed-in human makes for an outside AI agent.

    POST /api/agent/keys {label, max_claims, max_spend_units, days, payout_wallet} -> the key, shown ONCE
         "knos_ak_<id>_<secret>" (secret: 32 random bytes, urlsafe); Knos keeps only sha256(secret)
    GET  /api/agent/keys          the owner's keys and their counters, never a secret
    POST /api/agent/keys/revoke   {id}: the key and every access token made from it stop at once

The key is also an OAuth 2.0 client (RFC 6749 4.4, client credentials): POST /oauth/token with client_id = the key's id
and client_secret = its secret (form body or HTTP Basic) gives a one-hour Bearer access token, scope knos.solve. The
token is HMAC-signed and names its key, so each use reads the key again: a revoked or expired key kills its tokens.
The metadata is published at /.well-known/oauth-authorization-server (RFC 8414) and /.well-known/oauth-protected-resource
(RFC 9728), and the A2A Agent Card at /.well-known/agent-card.json names the same flow.

Caps, counted on the key itself (valley._save: on disk, and on devnet with the projects, so they survive a restart):
claims over max_claims are refused at claim; a payout over max_spend_units (test units paid to the key's payout wallet)
is refused before release. An agent key pays only its payout_wallet. Devnet test money only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from . import auth, valley

PREFIX = "knos_ak_"
TOKEN_PREFIX = "knos_at_"
TOKEN_S = 3600
SCOPE = "knos.solve"
MAX_CLAIMS, MAX_SPEND, MAX_DAYS = 50, 10_000, 90
QLOO_CALLS = 100           # the qloo_* tools an agent key may call over the hosted MCP, in its whole life: its own budget
KIND = "agentkeys"
PUBLIC = "https://knos.onrender.com"
_KEY = re.compile(r"knos_ak_([0-9a-f]{16})_([A-Za-z0-9_-]{43})")
_lock = threading.RLock()


class Dead(auth.AuthError):
    """A key Knos knows, but revoked or expired: the caller is told which."""


def _sha(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _int(v, lo: int, hi: int, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise valley.Refused(f"{what}: a whole number from {lo:,} to {hi:,}")
    return v


def public(rec: dict, now: float | None = None) -> dict:
    """A key as its owner sees it: caps, counters and state; never the secret or its hash."""
    now = time.time() if now is None else now
    state = "revoked" if rec.get("revoked") else "expired" if rec["expires_s"] <= now else "active"
    return {k: rec.get(k) for k in ("id", "label", "owner_label", "payout_wallet", "max_claims", "max_spend_units", "claims_used",
                                    "units_spent", "calls", "created", "expires", "revoked")} | {"state": state, "money": "devnet test units"}


def create(user: dict | None, label: str, max_claims, max_spend_units, days, payout_wallet: str, now: float | None = None) -> dict:
    """A new key for the signed-in human `user`. The full key is in this answer only."""
    from solders.pubkey import Pubkey
    if not user or not user.get("sub"):
        raise auth.AuthError("sign in first: a person makes an agent key (passkey, SSO, Google or a guest label)")
    if user.get("kind") == "agent":
        raise auth.AuthError("an agent key cannot make another key: its human does")
    label = " ".join(str(label or "").split())[:60]
    if len(label) < 2:
        raise valley.Refused("label: what the agent is (2 to 60 characters)")
    max_claims = _int(max_claims, 1, MAX_CLAIMS, "max_claims")
    max_spend_units = _int(max_spend_units, 0, MAX_SPEND, "max_spend_units")
    days = _int(days, 1, MAX_DAYS, "days")
    try:
        Pubkey.from_string(str(payout_wallet))
    except ValueError:
        raise valley.Refused("payout_wallet: a Solana devnet address (the only wallet this key is paid at)") from None
    if str(payout_wallet) in valley._referee_keys():
        raise valley.Refused("a referee's key cannot be a payee")
    now = time.time() if now is None else now
    kid, secret = valley._id("agentkey", user["sub"]), secrets.token_urlsafe(32)
    rec = {"id": kid, "label": label, "owner": str(user["sub"])[:120], "owner_label": str(user.get("label") or "")[:80],
           "payout_wallet": str(payout_wallet), "max_claims": max_claims, "max_spend_units": max_spend_units,
           "claims_used": 0, "units_spent": 0, "calls": 0, "secret_sha256": _sha(secret),
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "created_s": int(now),
           "expires": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + days * 86_400)), "expires_s": int(now + days * 86_400),
           "revoked": None, "attempts": []}
    with _lock:
        valley._save(KIND, kid, rec)
    return {**public(rec, now), "key": f"{PREFIX}{kid}_{secret}", "client_id": kid,
            "shown": "once: Knos keeps only its sha256; store it now", "token_endpoint": "/oauth/token"}


def keys(user: dict | None) -> list[dict]:
    if not user or user.get("kind") == "agent":
        raise auth.AuthError("sign in first: the person who made the keys lists them")
    return [public(r) for r in valley._all(KIND) if r.get("owner") == str(user.get("sub"))]


def revoke(user: dict | None, kid: str) -> dict:
    if not user or user.get("kind") == "agent":
        raise auth.AuthError("sign in first: the person who made the key revokes it")
    with _lock:
        rec = valley._load(KIND, str(kid))
        if rec.get("owner") != str(user.get("sub")):
            raise valley.Refused("only the person who made this key revokes it")
        if not rec.get("revoked"):
            rec["revoked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            valley._save(KIND, rec["id"], rec)
    return public(rec)


def _live(rec: dict, now: float | None = None) -> dict:
    if rec.get("revoked"):
        raise Dead(f"agent key {rec['id']} was revoked by its owner at {rec['revoked']}: it and its tokens are refused")
    if rec["expires_s"] <= (time.time() if now is None else now):
        raise Dead(f"agent key {rec['id']} expired at {rec['expires']}: its owner makes a new one")
    return rec


def _check_secret(kid: str, secret: str) -> dict | None:
    rec = valley._safe_load(KIND, kid) if re.fullmatch(r"[0-9a-f]{16}", str(kid or "")) else None
    if rec is None or not hmac.compare_digest(_sha(str(secret or "")), rec.get("secret_sha256", "")):
        return None
    return rec


# ---- OAuth 2.0 client credentials (RFC 6749 4.4) ---------------------------------------------------------------------
def _sign(raw: str) -> str:
    return auth.b64u(hmac.new(auth._SECRET, b"agent-token:" + raw.encode(), hashlib.sha256).digest())


def token(form: dict, basic: str | None = None, now: float | None = None) -> tuple[int, dict, dict]:
    """(status, body, headers) of POST /oauth/token. Errors are RFC 6749 5.2's; a client that authenticated with HTTP
    Basic and failed is answered 401 with WWW-Authenticate."""
    one = lambda k: str((form.get(k) or [""])[0] if isinstance(form.get(k), list) else form.get(k) or "")  # noqa: E731
    cid, secret, via = one("client_id"), one("client_secret"), "client_secret_post"
    if basic and basic.startswith("Basic "):
        try:
            import urllib.parse
            pair = base64.b64decode(basic[6:].strip(), validate=True).decode()
            cid, _, secret = pair.partition(":")
            cid, secret = urllib.parse.unquote_plus(cid), urllib.parse.unquote_plus(secret)
            via = "client_secret_basic"
        except (ValueError, UnicodeDecodeError):
            return 400, {"error": "invalid_request", "error_description": "the Basic credentials are not base64 of id:secret"}, {}
    if one("grant_type") != "client_credentials":
        return 400, {"error": "unsupported_grant_type", "error_description": "grant_type=client_credentials only"}, {}
    scope = one("scope")
    if scope and set(scope.split()) - {SCOPE}:
        return 400, {"error": "invalid_scope", "error_description": f"the one scope is {SCOPE}"}, {}
    rec = _check_secret(cid, secret)
    fail = {"WWW-Authenticate": 'Basic realm="knos"'} if via == "client_secret_basic" else {}
    if rec is None:
        return 401, {"error": "invalid_client", "error_description": "unknown client_id or wrong client_secret"}, fail
    try:
        _live(rec, now)
    except Dead as why:
        return 401, {"error": "invalid_client", "error_description": str(why)}, fail
    now = time.time() if now is None else now
    exp = int(min(now + TOKEN_S, rec["expires_s"]))
    raw = auth.b64u(json.dumps({"kid": rec["id"], "exp": exp, "n": secrets.token_hex(6)}, sort_keys=True).encode())
    return 200, {"access_token": TOKEN_PREFIX + raw + "." + _sign(raw), "token_type": "Bearer", "expires_in": exp - int(now),
                 "scope": SCOPE}, {"Pragma": "no-cache"}


def _from_token(tok: str, now: float | None = None) -> dict | None:
    raw, _, sig = tok[len(TOKEN_PREFIX):].partition(".")
    if not sig or not hmac.compare_digest(sig, _sign(raw)):
        return None
    try:
        body = json.loads(auth.unb64u(raw))
    except ValueError:
        return None
    if body.get("exp", 0) <= (time.time() if now is None else now):
        raise Dead("this access token expired: ask POST /oauth/token for a new one")
    return valley._safe_load(KIND, str(body.get("kid")))


def as_user(rec: dict) -> dict:
    """The agent as the rest of the app sees a signed-in maker: its own sub, its key's caps and payout wallet."""
    return {"sub": "agentkey:" + rec["id"], "kind": "agent", "label": f"{rec['label']} (agent key {rec['id'][:6]} of {rec['owner_label'] or 'its owner'})"[:80],
            "agent_key": rec["id"], "owner": rec["owner"], "payout_wallet": rec["payout_wallet"]}


def principal(header: str | None, now: float | None = None, count: bool = True) -> dict | None:
    """Who a Bearer header speaks for: an agent (its key, or an access token made from it) or a human session. None
    when there is no credential; Dead when it names a revoked or expired key."""
    if not header or not header.startswith("Bearer "):
        return None
    cred = header[7:].strip()
    rec = None
    if cred.startswith(TOKEN_PREFIX):
        rec = _from_token(cred, now)
    elif cred.startswith(PREFIX):
        m = _KEY.fullmatch(cred)
        rec = _check_secret(m.group(1), m.group(2)) if m else None
    else:
        return auth.who(header, now)
    if rec is None:
        return None
    _live(rec, now)
    if count:
        with _lock:                                  # a usage line for the owner: how often the agent wrote
            got = valley._load(KIND, rec["id"])
            got["calls"] = int(got.get("calls") or 0) + 1
            got["last_call"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            valley._save(KIND, rec["id"], got)
    return as_user(rec)


# ---- the caps ---------------------------------------------------------------------------------------------------------
def take_claim(kid: str) -> dict:
    """Count one claim before it is made (refused over max_claims); give_back undoes it when the claim then fails."""
    with _lock:
        rec = _live(valley._load(KIND, kid))
        if rec["claims_used"] >= rec["max_claims"]:
            raise valley.Refused(f"agent key {kid}: its claim cap is reached ({rec['claims_used']} of {rec['max_claims']})")
        rec["claims_used"] += 1
        return valley._save(KIND, kid, rec)


def give_back(kid: str) -> None:
    with _lock:
        rec = valley._load(KIND, kid)
        rec["claims_used"] = max(0, rec["claims_used"] - 1)
        valley._save(KIND, kid, rec)


def note_attempt(kid: str, pid: str, key: str, attempt: str) -> None:
    with _lock:
        rec = valley._load(KIND, kid)
        rec.setdefault("attempts", []).append({"project": pid, "milestone": key, "attempt": attempt})
        rec["attempts"] = rec["attempts"][-200:]
        valley._save(KIND, kid, rec)


def can_spend(kid: str, units: int) -> dict:
    """A payout of `units` test units fits what the key may still be paid; else refused (before any money moves)."""
    rec = _live(valley._load(KIND, kid))
    if rec["units_spent"] + int(units) > rec["max_spend_units"]:
        raise valley.Refused(f"agent key {kid}: a payout of {units} test units is over its spend cap "
                             f"({rec['units_spent']} of {rec['max_spend_units']} used)")
    return rec


def take_qloo(kid: str) -> dict:
    """Count one qloo_* call on this key's own budget (refused once QLOO_CALLS are used): the public MCP lends no
    one Knos's Qloo key, and a key's calls never come out of the others'."""
    with _lock:
        rec = _live(valley._load(KIND, kid))
        used = int(rec.get("qloo_calls") or 0)
        if used >= QLOO_CALLS:
            raise valley.Refused(f"agent key {kid}: its Qloo calls are used ({used} of {QLOO_CALLS})")
        rec["qloo_calls"] = used + 1
        return valley._save(KIND, kid, rec)


def spent(kid: str, units: int) -> None:
    with _lock:
        rec = valley._load(KIND, kid)
        rec["units_spent"] = int(rec["units_spent"]) + int(units)
        valley._save(KIND, kid, rec)


# ---- what an outside agent reads first --------------------------------------------------------------------------------
def needs(name: str, base: str | None = None) -> str:
    """The MCP error of a write tool called without a credential: how to get one."""
    b = (base or PUBLIC).rstrip("/")
    return (f"{name} writes: send Authorization: Bearer <token> in the HTTP header. An agent: an OAuth 2.0 access token "
            f"(POST {b}/oauth/token, grant_type=client_credentials, your agent key's id and secret) or the agent key itself; "
            f"a person makes the key at POST /api/agent/keys. A person: the session token knos_sign_in returns. "
            f"How: {b}/.well-known/oauth-protected-resource")


def server_metadata(base: str) -> dict:
    """RFC 8414: this server is its own authorization server, for client credentials only."""
    b = base.rstrip("/")
    return {"issuer": b, "token_endpoint": f"{b}/oauth/token", "grant_types_supported": ["client_credentials"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"], "response_types_supported": [],
            "scopes_supported": [SCOPE], "service_documentation": "https://github.com/drexthealpha/Knos/blob/main/docs/reference/A2A.md"}


def resource_metadata(base: str) -> dict:
    """RFC 9728: the MCP endpoint is the protected resource; its write tools need a Bearer token."""
    b = base.rstrip("/")
    return {"resource": f"{b}/mcp", "authorization_servers": [b], "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"],
            "resource_name": "Knos MCP (devnet, test money)",
            "resource_documentation": "https://github.com/drexthealpha/Knos/blob/main/docs/reference/A2A.md"}


def card(base: str) -> dict:
    """The A2A 1.0 Agent Card of the hosted app: its interface is the MCP endpoint (JSON-RPC over HTTP), its security the
    OAuth 2.0 client-credentials flow of an agent key."""
    from . import agent
    b = base.rstrip("/")
    skill = lambda i, n, d, t, ex: {"id": i, "name": n, "description": d, "tags": t, "examples": ex,  # noqa: E731
                                    "inputModes": ["application/json"], "outputModes": ["application/json"]}
    return {
        "name": "Knos",
        "description": ("Knos: open research milestones on test money; a referee checks the work before anything is released "
                        "(Solana devnet). The interface is MCP (JSON-RPC over HTTP, MCP " + agent.PROTOCOL +
                        "), not A2A's SendMessage; write tools take an OAuth 2.0 token from an agent key a person caps and can revoke."),
        "supportedInterfaces": [{"url": f"{b}/mcp", "protocolBinding": "MCP", "protocolVersion": "1.0"}],
        "provider": {"organization": "Knos", "url": "https://github.com/drexthealpha/Knos"},
        "version": agent._knos_version(),
        "documentationUrl": "https://github.com/drexthealpha/Knos/blob/main/docs/reference/A2A.md",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
        "securitySchemes": {"agent_key": {"oauth2SecurityScheme": {
            "description": "An agent key (made by a signed-in person, with claim and spend caps) is the OAuth 2.0 client",
            "flows": {"clientCredentials": {"tokenUrl": f"{b}/oauth/token",
                                            "scopes": {SCOPE: "claim milestones, submit to the referee, be paid at the key's payout wallet within its caps"}}},
            "oauth2MetadataUrl": f"{b}/.well-known/oauth-authorization-server"}}},
        "securityRequirements": [{"schemes": {"agent_key": {"list": [SCOPE]}}}],
        "skills": [
            skill("find-work", "Find funded work", "Open rounds and milestones with test money held until the check passes (knos_tasks, knos_projects).",
                  ["work", "held-money", "milestones"], ['{"tool": "knos_tasks"}']),
            skill("claim-milestone", "Claim a milestone", "Takes a milestone; an agent key is paid only at its payout wallet (knos_project_claim).",
                  ["claim", "milestone"], ['{"tool": "knos_project_claim", "project": "<id>", "milestone": "<key>"}']),
            skill("submit-to-referee", "Submit to the sealed referee",
                  "Submits code to a referee-judged milestone; a verdict that meets the target releases the held money with no human step "
                  "(knos_milestone_submit).", ["referee", "submit", "payout"],
                  ['{"tool": "knos_milestone_submit", "project": "<id>", "milestone": "<key>", "code": "<train.py>"}']),
            skill("check-brief", "Check a brief", "Whether a brief is Ready to fund: measurable targets, a verifier, a deadline (knos_ready).",
                  ["ready", "brief"], ['{"tool": "knos_ready", "brief": {"milestones": []}}']),
        ],
    }
