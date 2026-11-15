"""Single sign-on for the self-host bundle: OpenID Connect, written out with the standard library (docs/reference/SELFHOST.md).

    [sso] in knos.toml      who the provider is, which email domains and groups may sign in, and each role's groups
    keys.sso_session        a file of 32 or more random characters: it signs the session cookie (site and record read it)
    keys.sso_client_secret  the client secret, when the provider gave one (else the client is public: PKCE alone)

THE FLOW (OpenID Connect Core 1.0, the authorization code flow, with PKCE, RFC 7636, method S256):

    GET  /sso/login?next=/x   reads the provider's discovery document, keeps state, nonce and the PKCE verifier in a
                              short sealed cookie, and sends the browser to the provider
    GET  /sso/callback        checks the state, trades the code (and the verifier) for an ID token at the token
                              endpoint, checks the token against the provider's published keys (JWKS: RS256 or ES256),
                              its issuer, audience, expiry and nonce, then the domain and groups, and sets the session
    GET  /sso/me              who is signed in, the role, and the form token /sso/act asks for
    POST /sso/act             {"action": "approve" | "export", "subject": "...", "sha256": "..."}: one audit line, with
                              the signed-in person; an approver or an admin only
    GET  /sso/audit           the audit log and whether its chain holds; an admin only
    GET  /sso/logout          forgets the session here (the provider may still remember the person)

ROLES. viewer < approver < admin. A person's role is the highest whose groups (the `groups` claim, or the claim
[sso] groups_claim names) they are in; `default_role` is the role of a person from an allowed domain in no listed
group (none: refused). With `domains`, the email must be verified and its domain listed exactly.

THE AUDIT LOG lives in the memory engine (knos.proof.history), never in a side file: one entity a line, each line
carrying the sha256 of the line before it, and the head in a state document. `Audit.check` finds a removed or edited
line. Sign-ins, approvals and exports are written; a refused request is not.

Tested with a fake provider only (tests/test_sso.py, keys made in the test). No real provider has been tried.
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
import urllib.parse
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from typing import Any, Callable

ROLES = ("viewer", "approver", "admin")                    # each can do what the one before it can
ACTIONS = {"approve": "approver", "export": "approver"}    # what /sso/act writes, and the least role that may
FIELDS = {"issuer", "client_id", "redirect", "domains", "groups_claim", "default_role", "hours", "scopes", *ROLES}
SESSION, LOGIN = "knos_session", "knos_login"              # the cookies
SIGNED_IN = "knos_signed_in"               # no secret: tells the page's script that sign-in is on here, so the approver writes the audit log
ALGS = ("RS256", "ES256")                                  # what an ID token may be signed with; never "none", never a shared secret
LEEWAY = 60                                                # seconds of clock difference allowed on exp and iat
MAX_BODY, MAX_TOKEN, MAX_FETCH = 4096, 16384, 1 << 20
_CATEGORY, _HEAD = "sso-audit", "sso-audit-head"
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
_LOOPBACK = ("127.0.0.1", "localhost", "[::1]")

Fetch = Callable[[str, bytes | None, dict[str, str]], tuple[int, bytes]]


class Refused(Exception):
    """A sign-in or a request that is refused: the message is one plain line, safe to show."""


def _safe_url(url: object) -> bool:
    """https, or http to this machine only (a provider in a test)."""
    if not isinstance(url, str) or len(url) > 2000:
        return False
    u = urllib.parse.urlsplit(url)
    return bool(u.netloc) and (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")))


def errors_of(body: object) -> list[str]:
    """What is wrong with an [sso] table (knos.selfhost.check adds these to its own)."""
    if not isinstance(body, dict):
        return ["[sso] is a table"]
    out = [f"sso.{k} is not a setting of sso (it has {', '.join(sorted(FIELDS))})" for k in body if k not in FIELDS]
    if not _safe_url(body.get("issuer")):
        out.append("sso.issuer must be your provider's issuer URL (https://...), exactly as it states it")
    cid = body.get("client_id")
    if not isinstance(cid, str) or not 0 < len(cid) <= 200:
        out.append("sso.client_id must be the client id your provider gave this deployment")
    red = body.get("redirect")
    if not _safe_url(red) or not str(red).split("?")[0].endswith("/sso/callback"):
        out.append("sso.redirect must be this site's own address ending in /sso/callback (https://...)")
    domains = body.get("domains", [])
    if not isinstance(domains, list) or not all(isinstance(d, str) and _DOMAIN.fullmatch(d) for d in domains):
        out.append("sso.domains must list email domains in lower case, like \"example.com\"")
        domains = []
    groups = []
    for role in ROLES:
        g = body.get(role, [])
        if not isinstance(g, list) or not all(isinstance(x, str) and 0 < len(x) <= 200 for x in g):
            out.append(f"sso.{role} must list the provider's group names whose members get the role {role}")
        else:
            groups += g
    claim = body.get("groups_claim", "groups")
    if not isinstance(claim, str) or not re.fullmatch(r"[A-Za-z0-9_:/.-]{1,100}", claim):
        out.append("sso.groups_claim is the name of the ID token's claim that lists groups")
    default = body.get("default_role")
    if default is not None and default not in ROLES:
        out.append(f"sso.default_role must be one of {', '.join(ROLES)}")
    if default is not None and not domains:
        out.append("sso.default_role needs sso.domains: else anyone your provider knows would get that role")
    if not domains and not groups:
        out.append("[sso] must say who may sign in: sso.domains, or groups in sso.viewer, sso.approver or sso.admin")
    hours = body.get("hours", 8)
    if not isinstance(hours, int) or isinstance(hours, bool) or not 1 <= hours <= 24:
        out.append("sso.hours (how long a session lasts) must be a whole number from 1 to 24")
    scopes = body.get("scopes", ["openid", "email", "profile"])
    if not isinstance(scopes, list) or "openid" not in scopes or not all(isinstance(s, str) and re.fullmatch(r"[\x21\x23-\x5b\x5d-\x7e]+", s) for s in scopes):
        out.append("sso.scopes must be a list of scopes that includes \"openid\"")
    return out


@dataclass
class Config:
    issuer: str
    client_id: str
    redirect: str
    session_key: bytes
    secret: str | None = None
    domains: tuple[str, ...] = ()
    groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    groups_claim: str = "groups"
    default_role: str | None = None
    hours: int = 8
    scopes: tuple[str, ...] = ("openid", "email", "profile")

    @property
    def secure(self) -> bool:
        return self.redirect.startswith("https://")

    @property
    def origin(self) -> str:
        u = urllib.parse.urlsplit(self.redirect)
        return f"{u.scheme}://{u.netloc}"


def config_of(body: dict, session_key: str, secret: str | None = None) -> Config:
    """A Config from a checked [sso] table and the two key files' text."""
    bad = errors_of(body)
    if bad:
        raise Refused(bad[0])
    if len(session_key.strip()) < 32:
        raise Refused("keys.sso_session must hold 32 or more random characters")
    return Config(issuer=body["issuer"], client_id=body["client_id"], redirect=body["redirect"], session_key=session_key.strip().encode(),
                  secret=(secret or "").strip() or None, domains=tuple(body.get("domains", [])),
                  groups={r: tuple(body.get(r, [])) for r in ROLES}, groups_claim=body.get("groups_claim", "groups"),
                  default_role=body.get("default_role"), hours=int(body.get("hours", 8)), scopes=tuple(body.get("scopes", ["openid", "email", "profile"])))


# -- the provider ---------------------------------------------------------------------------------------------------------

def http_fetch(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    """One request (GET, or POST when `data`): (status, body), at most 1 MB, 10 s."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=data, headers=dict(headers or {}), method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:     # noqa: S310 - the URL passed _safe_url
            return r.status, r.read(MAX_FETCH + 1)[:MAX_FETCH]
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_FETCH)


def _json(status: int, raw: bytes, what: str) -> dict:
    if status != 200:
        raise Refused(f"the provider's {what} answered {status}")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused(f"the provider's {what} is not JSON") from None
    if not isinstance(doc, dict):
        raise Refused(f"the provider's {what} is not a JSON object")
    return doc


class Provider:
    """The provider's discovery document and published keys, read when first needed. Keys are read again when a token
    names a key id not seen yet (a rotation), at most once a minute."""

    def __init__(self, issuer: str, fetch: Fetch | None = None, clock: Callable[[], float] = time.time):
        self.issuer, self.fetch, self.clock = issuer, fetch or http_fetch, clock
        self._meta: dict | None = None
        self._jwks: dict | None = None
        self._read_at = -1e18
        self._lock = threading.Lock()

    def meta(self) -> dict:
        if self._meta is None:
            url = self.issuer.rstrip("/") + "/.well-known/openid-configuration"
            doc = _json(*self.fetch(url, None, {"Accept": "application/json"}), "discovery document")
            if doc.get("issuer") != self.issuer:
                raise Refused("the discovery document names another issuer than sso.issuer")
            for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not _safe_url(doc.get(k)):
                    raise Refused(f"the discovery document's {k} is not an https address")
            methods = doc.get("code_challenge_methods_supported")
            if methods is not None and "S256" not in methods:
                raise Refused("the provider does not take PKCE with S256")
            algs = doc.get("id_token_signing_alg_values_supported")
            if algs is not None and not set(algs) & set(ALGS):
                raise Refused("the provider signs ID tokens with none of RS256, ES256")
            self._meta = doc
        return self._meta

    def keys(self, kid: object) -> dict:
        with self._lock:
            known = self._jwks is not None and any(isinstance(k, dict) and k.get("kid") == kid for k in self._jwks.get("keys", []))
            if not known and self.clock() - self._read_at >= 60:
                doc = _json(*self.fetch(self.meta()["jwks_uri"], None, {"Accept": "application/json"}), "key set (JWKS)")
                if not isinstance(doc.get("keys"), list):
                    raise Refused("the provider's key set has no keys")
                self._jwks, self._read_at = doc, self.clock()
            return self._jwks or {"keys": []}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce() -> tuple[str, str]:
    """(verifier, S256 challenge): RFC 7636, 4.1 and 4.2."""
    verifier = _b64(secrets.token_bytes(32))
    return verifier, _b64(hashlib.sha256(verifier.encode()).digest())


def verify_id_token(token: str, cfg: Config, provider: Provider, nonce: str | None, now: float) -> dict:
    """The claims of an ID token, checked as OpenID Connect Core 1.0 section 3.1.3.7 says, or Refused."""
    from . import standalone_verify
    if not isinstance(token, str) or len(token) > MAX_TOKEN or token.count(".") != 2:
        raise Refused("the provider sent no ID token")
    try:
        head = json.loads(_unb64(token.split(".")[0]))
    except (ValueError, UnicodeDecodeError):
        raise Refused("the ID token's header is not JSON") from None
    if not isinstance(head, dict) or head.get("alg") not in ALGS:
        raise Refused("the ID token is not signed with RS256 or ES256")
    jwks = provider.keys(head.get("kid"))
    strong = [k for k in jwks.get("keys", []) if isinstance(k, dict) and (k.get("kty") != "RSA" or len(_unb64(str(k.get("n", "")))) >= 256)]
    _h, claims, why = standalone_verify.read_token(token, {"keys": strong})
    if why:
        raise Refused("the ID token's signature does not check against the provider's published keys")
    if claims.get("iss") != cfg.issuer:
        raise Refused("the ID token is from another issuer")
    aud = claims.get("aud")
    auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
    if cfg.client_id not in auds:
        raise Refused("the ID token is for another client")
    if ("azp" in claims or len(auds) > 1) and claims.get("azp") != cfg.client_id:
        raise Refused("the ID token was given to another client (azp)")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp <= now - LEEWAY:
        raise Refused("the ID token has expired")
    if not isinstance(iat, (int, float)) or isinstance(iat, bool) or iat > now + LEEWAY:
        raise Refused("the ID token is issued in the future: check this machine's clock")
    if nonce is not None and not (isinstance(claims.get("nonce"), str) and hmac.compare_digest(claims["nonce"], nonce)):
        raise Refused("the ID token's nonce is not the one this sign-in sent")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise Refused("the ID token names nobody (no sub)")
    return claims


def role_of(cfg: Config, claims: dict) -> str:
    """The role a person gets, or Refused saying why none."""
    if cfg.domains:
        email = claims.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise Refused("your provider sent no email address, and this deployment admits people by email domain")
        if claims.get("email_verified") is not True:
            raise Refused("your email address is not verified at your provider")
        if email.rsplit("@", 1)[1].lower() not in cfg.domains:
            raise Refused("your email domain is not one this deployment admits")
    got = claims.get(cfg.groups_claim, [])
    have = {g for g in got if isinstance(g, str)} if isinstance(got, list) else set()
    for role in reversed(ROLES):
        if have & set(cfg.groups.get(role, ())):
            return role
    if cfg.default_role:
        return cfg.default_role
    raise Refused("you are in none of the groups this deployment admits")


def at_least(role: object, need: str) -> bool:
    return role in ROLES and ROLES.index(str(role)) >= ROLES.index(need)


# -- sealed cookies -------------------------------------------------------------------------------------------------------

def seal(key: bytes, body: dict) -> str:
    """`body` with its HMAC-SHA256 under the session key: readable, not changeable."""
    raw = _b64(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return raw + "." + _b64(hmac.new(key, b"knos-sso/1\x00" + raw.encode(), hashlib.sha256).digest())


def unseal(key: bytes, text: str | None, now: float) -> dict | None:
    """The body of a sealed value, or None when it is missing, changed or past its `exp`."""
    if not text or len(text) > 4096 or text.count(".") != 1:
        return None
    raw, mac = text.split(".")
    want = _b64(hmac.new(key, b"knos-sso/1\x00" + raw.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, want):
        return None
    try:
        body = json.loads(_unb64(raw))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or not isinstance(body.get("exp"), (int, float)) or body["exp"] <= now:
        return None
    return body


def cookies_of(headers: dict[str, str]) -> dict[str, str]:
    c: SimpleCookie = SimpleCookie()
    try:
        c.load(headers.get("cookie", ""))
    except CookieError:
        return {}
    return {k: m.value for k, m in c.items()}


# -- the audit log ---------------------------------------------------------------------------------------------------------

def _line_hash(line: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in line.items() if k != "hash"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Audit:
    """Who signed in, approved and exported: a hash-chained log in the memory engine. `store`: a knos.proof.history
    store (SibylStore.local(...) in the container)."""

    def __init__(self, store: Any):
        self.store = store
        self._lock = threading.Lock()

    def add(self, who: dict, action: str, subject: str = "", sha256: str = "", at: float | None = None) -> dict:
        with self._lock:
            head = self.store.state(_HEAD) or {"seq": -1, "hash": "0" * 64}
            seq, prev = int(head["seq"]) + 1, str(head["hash"])
            while self.store.get(_CATEGORY, f"{seq:010d}"):          # a line written before its head was: the chain goes on from it
                found = self.store.get(_CATEGORY, f"{seq:010d}")
                seq, prev = seq + 1, str(found.get("hash", ""))
            line = {"seq": seq, "at": int(at if at is not None else time.time()), "action": action, "sub": str(who.get("sub", "")),
                    "email": str(who.get("email", "")), "role": str(who.get("role", "")), "iss": str(who.get("iss", "")),
                    "subject": subject, "sha256": sha256, "prev": prev}
            line["hash"] = _line_hash(line)
            self.store.put(_CATEGORY, f"{seq:010d}", line)
            self.store.set_state(_HEAD, {"seq": seq, "hash": line["hash"]})
            return line

    def lines(self) -> list[dict]:
        return sorted(self.store.all(_CATEGORY), key=lambda x: int(x.get("seq", 0)))

    def check(self) -> list[str]:
        """What is wrong with the chain: [] when every line follows the one before it and the head is the last."""
        problems, prev = [], "0" * 64
        lines = self.lines()
        for i, line in enumerate(lines):
            if line.get("seq") != i:
                problems.append(f"line {i} is missing (found {line.get('seq')})")
                break
            if line.get("prev") != prev or line.get("hash") != _line_hash(line):
                problems.append(f"line {i} was changed")
                break
            prev = line["hash"]
        head = self.store.state(_HEAD)
        if lines and not problems and (head.get("seq") != len(lines) - 1 or head.get("hash") != prev):
            problems.append("the head does not name the last line: a line was removed")
        return problems


# -- the gate ---------------------------------------------------------------------------------------------------------------

def _answer(status: int, body: object, headers: list[tuple[str, str]] | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
    raw = json.dumps(body).encode()
    return status, [("Content-Type", "application/json"), ("Cache-Control", "no-store"), *(headers or [])], raw


def _local(path: str) -> str:
    """A path on this site to go back to after signing in: never another host."""
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "\\" in path or len(path) > 300 or path.startswith("/sso/"):
        return "/"
    return path


class Gate:
    """Sign-in for one deployment. The site asks `route` for /sso/... and `guard` for everything else; the record API
    asks `who`. `audit`: an Audit, or None where nothing is written (the record API)."""

    def __init__(self, cfg: Config, provider: Provider | None = None, audit: Audit | None = None, clock: Callable[[], float] = time.time):
        self.cfg, self.audit, self.clock = cfg, audit, clock
        self.provider = provider or Provider(cfg.issuer, clock=clock)

    def _cookie(self, name: str, value: str, age: int, path: str = "/", script: bool = False) -> tuple[str, str]:
        """A Set-Cookie header; HttpOnly unless `script` (only SIGNED_IN, which holds no secret, is read by the page)."""
        return ("Set-Cookie", f"{name}={value}; Path={path}; Max-Age={age}" + ("" if script else "; HttpOnly") + "; SameSite=Lax" + ("; Secure" if self.cfg.secure else ""))

    def who(self, headers: dict[str, str]) -> dict | None:
        """The signed-in person ({sub, iss, email, name, role, form, exp}) from the session cookie, or None."""
        h = {str(k).lower(): str(v) for k, v in headers.items()}
        got = unseal(self.cfg.session_key, cookies_of(h).get(SESSION), self.clock())
        return got if got and got.get("role") in ROLES else None

    def guard(self, method: str, path: str, headers: dict[str, str]) -> tuple[int, list[tuple[str, str]], bytes] | None:
        """None when a signed-in person may have this page; else the answer: a GET goes to sign in, anything else is 401."""
        if self.who(headers) is not None:
            return None
        if method in ("GET", "HEAD"):
            return 302, [("Location", "/sso/login?" + urllib.parse.urlencode({"next": _local(path)})), ("Cache-Control", "no-store")], b""
        return _answer(401, {"error": "sign in first", "login": "/sso/login"})

    def route(self, method: str, target: str, headers: dict[str, str], body: bytes = b"") -> tuple[int, list[tuple[str, str]], bytes]:
        """One /sso/... request: (status, headers, body). Every refusal is one plain line."""
        h = {str(k).lower(): str(v) for k, v in headers.items()}
        path, _, query = target.partition("?")
        q = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
        try:
            if path == "/sso/login" and method == "GET":
                return self._login(q)
            if path == "/sso/callback" and method == "GET":
                return self._callback(q, h)
            if path == "/sso/logout" and method == "GET":
                return _answer(200, {"signed_out": True, "note": "signed out here; your provider may still keep you signed in"},
                               [self._cookie(SESSION, "", 0), self._cookie(SIGNED_IN, "", 0, script=True)])
            if path == "/sso/me" and method == "GET":
                me = self.who(h)
                if me is None:
                    return _answer(401, {"signed_in": False, "login": "/sso/login"})
                return _answer(200, {"signed_in": True, "sub": me["sub"], "email": me.get("email", ""), "name": me.get("name", ""), "role": me["role"],
                                     "form": me["form"], "can": {a: at_least(me["role"], r) for a, r in ACTIONS.items()} | {"audit": me["role"] == "admin"}})
            if path == "/sso/act" and method == "POST":
                return self._act(h, body)
            if path == "/sso/audit" and method == "GET":
                me = self.who(h)
                if me is None:
                    return _answer(401, {"error": "sign in first", "login": "/sso/login"})
                if me["role"] != "admin":
                    return _answer(403, {"error": "only an admin reads the audit log"})
                if self.audit is None:
                    return _answer(404, {"error": "this server keeps no audit log"})
                return _answer(200, {"lines": self.audit.lines(), "problems": self.audit.check()})
        except Refused as why:
            return _answer(403, {"error": str(why)})
        if path in ("/sso/login", "/sso/callback", "/sso/logout", "/sso/me", "/sso/act", "/sso/audit"):
            return _answer(405, {"error": f"{method} is not served here"})
        return _answer(404, {"error": "no such sign-in page"})

    def _login(self, q: dict[str, str]) -> tuple[int, list[tuple[str, str]], bytes]:
        meta = self.provider.meta()
        verifier, challenge = pkce()
        state, nonce = _b64(secrets.token_bytes(24)), _b64(secrets.token_bytes(24))
        pending = seal(self.cfg.session_key, {"state": state, "nonce": nonce, "verifier": verifier, "next": _local(q.get("next", "/")),
                                              "exp": int(self.clock()) + 600})
        ask = {"response_type": "code", "client_id": self.cfg.client_id, "redirect_uri": self.cfg.redirect, "scope": " ".join(self.cfg.scopes),
               "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
        url = meta["authorization_endpoint"]
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(ask)
        return 302, [("Location", url), ("Cache-Control", "no-store"), self._cookie(LOGIN, pending, 600, "/sso/")], b""

    def _callback(self, q: dict[str, str], h: dict[str, str]) -> tuple[int, list[tuple[str, str]], bytes]:
        now = self.clock()
        pending = unseal(self.cfg.session_key, cookies_of(h).get(LOGIN), now)
        if pending is None:
            raise Refused("this sign-in was not started here, or took over 10 minutes: start again at /sso/login")
        if not hmac.compare_digest(q.get("state", ""), str(pending.get("state", ""))):
            raise Refused("the provider sent back another sign-in's state")
        if q.get("error"):
            raise Refused(f"the provider refused the sign-in: {q['error'][:100]}")
        code = q.get("code", "")
        if not code or len(code) > 2000:
            raise Refused("the provider sent back no code")
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.cfg.redirect, "code_verifier": pending["verifier"]}
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        if self.cfg.secret:       # client_secret_basic (RFC 6749, 2.3.1): both parts form-encoded first
            pair = f"{urllib.parse.quote_plus(self.cfg.client_id)}:{urllib.parse.quote_plus(self.cfg.secret)}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            form["client_id"] = self.cfg.client_id
        got = _json(*self.provider.fetch(self.provider.meta()["token_endpoint"], urllib.parse.urlencode(form).encode(), headers), "token endpoint")
        claims = verify_id_token(got.get("id_token", ""), self.cfg, self.provider, pending["nonce"], now)
        role = role_of(self.cfg, claims)
        me = {"sub": claims["sub"], "iss": claims["iss"], "email": str(claims.get("email", ""))[:200], "name": str(claims.get("name", ""))[:200],
              "role": role, "form": _b64(secrets.token_bytes(18)), "exp": int(now) + self.cfg.hours * 3600}
        if self.audit is not None:
            self.audit.add(me, "sign-in", at=now)
        return 302, [("Location", pending["next"]), ("Cache-Control", "no-store"), self._cookie(SESSION, seal(self.cfg.session_key, me), self.cfg.hours * 3600),
                     self._cookie(SIGNED_IN, "1", self.cfg.hours * 3600, script=True), self._cookie(LOGIN, "", 0, "/sso/")], b""

    def _act(self, h: dict[str, str], body: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
        me = self.who(h)
        if me is None:
            return _answer(401, {"error": "sign in first", "login": "/sso/login"})
        if h.get("origin") and h["origin"] != self.cfg.origin:
            return _answer(403, {"error": "this request came from another site"})
        if not hmac.compare_digest(h.get("x-knos-form", ""), str(me["form"])):
            return _answer(403, {"error": "the form token is missing or old: read it from /sso/me"})
        if not h.get("content-type", "").startswith("application/json") or len(body) > MAX_BODY:
            return _answer(400, {"error": f"send JSON of {MAX_BODY} bytes at most"})
        try:
            doc = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return _answer(400, {"error": "the body is not JSON"})
        action = doc.get("action") if isinstance(doc, dict) else None
        if action not in ACTIONS:
            return _answer(400, {"error": f"action is one of {', '.join(ACTIONS)}"})
        subject, digest = doc.get("subject"), doc.get("sha256", "")
        if not isinstance(subject, str) or not 0 < len(subject) <= 200 or not subject.isprintable():
            return _answer(400, {"error": "subject names what was approved or exported (200 characters at most)"})
        if not isinstance(digest, str) or (digest and not re.fullmatch(r"[0-9a-f]{64}", digest)):
            return _answer(400, {"error": "sha256, when given, is 64 hex characters"})
        if not at_least(me["role"], ACTIONS[action]):
            return _answer(403, {"error": f"your role is {me['role']}: to {action} you need {ACTIONS[action]} or admin"})
        if self.audit is None:
            return _answer(404, {"error": "this server keeps no audit log"})
        return _answer(200, {"written": self.audit.add(me, action, subject, digest, self.clock())})


def gate_of(config: dict, base: Any = None, store: Any = None, provider: Provider | None = None, clock: Callable[[], float] = time.time) -> Gate | None:
    """The Gate a checked knos.toml asks for (None without [sso]). Reads keys.sso_session and keys.sso_client_secret.
    `store`: the memory store the audit log lives in (None: no audit log, as on the record API)."""
    from pathlib import Path
    body = config.get("sso")
    if body is None:
        return None
    keys = config.get("keys", {})

    def read(name: str) -> str | None:
        if not keys.get(name):
            return None
        p = Path(keys[name])
        p = p if p.is_absolute() or base is None else Path(base) / p
        try:
            return p.read_text(encoding="utf-8")
        except OSError as why:
            raise Refused(f"keys.{name}: {keys[name]} cannot be read ({why.strerror})") from None

    session = read("sso_session")
    if session is None:
        raise Refused("[sso] needs keys.sso_session")
    cfg = config_of(body, session, read("sso_client_secret"))
    return Gate(cfg, provider, Audit(store) if store is not None else None, clock)
