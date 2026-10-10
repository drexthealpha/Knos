"""Single sign-on for the self-host bundle (knos.sso): a local fake provider, its keys made here from fixed numbers,
signs the ID tokens. The whole flow runs over the loopback once (sign in, approve, export, read the audit log); the
rest calls the gate directly. No real provider is asked anything, and nothing leaves this machine."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knos import record_api, selfhost, sso
from knos.standalone_verify import SHA256_INFO, G, N, ec_mul

NOW = 1_790_000_000                  # a fixed clock: the provider and the gate read the same one
CLIENT = "knos-selfhost"
SESSION_KEY = "s" * 16 + "e" * 16 + "fixed-test-session-key"
# RSA-2048, made once for this file and written down so every run signs with the same key (never used elsewhere)
RSA_N = int(
    "b762f7e3324b2ba6108a5089c938ebd3288466276989b68e2990d71f3ba98ed188a2b10eb8b0c740da553585fd3497d630c9"
    "9acc3859be0c73ebd71aa873233972ba17bdc4ded576bc54aa4d92fa5af27fd808e20e21bc3b6efc8850a3ae92ebf1e803fc"
    "5249d5fda11ce89effe2a3eeb0d71aa73f95067ad06ebfb65ae7299e2101aadb6e6cc291f8167e62df797f3f3e1878acfb7f"
    "713bb3102d1f0e9f5880333c9c29021568c26bf1f58885cf93bec3aec12b4588644bc8e852c714b91b2a28931f27fd77005c"
    "5ac6c0cd853b219ca72737f4c3eef1da85d8362613cca05857fe9c122034f261549d261b06401035e8f63291487742dce522"
    "0d947e7415d9", 16)
RSA_D = int(
    "95ba14324769e06561b3cc35f338aa32692e5049757d9eb34b749a6f41c31a7c3156c3c10542302cdf161af11edec5e97743"
    "e34341eee3a03f351b1704d99cb4d6dae16f6b41947fb11c5f3f9ef5113454f509aba7661bcd5abc8c7f6a64aa4841e5f0fb"
    "1e2472b6f5c8289548cebe91af88b09644ef63aefa66b1d82d37f75d64a620d8b46000ae04bbed8344f0ad2e4bbb121ced3b"
    "4cb5c6a11d24872452ea754f8bfb218674d0bc429517ac39647471041afd6fc7c4b6e26fa47935b30337d552b47c1167dce9"
    "ba47eb8ac5833a868ba0c01635ba12fa5ebe6765c28fab3023ac2b8cf6aff20066980aef8149aec8fbc8af5c1bfe49e203db"
    "8e2249c8501", 16)
RSA_E = 65537
EC_D = int.from_bytes(hashlib.sha256(b"knos sso test ES256 key").digest(), "big") % N     # a fixed P-256 private key
EC_Q = ec_mul(EC_D, G)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(claims: dict, alg: str = "RS256", kid: str | None = None, d: int = RSA_D) -> str:
    """A JWT signed with the fixed keys: RS256 by RFC 8017 8.2.1, ES256 with a nonce derived from the key and message."""
    head = {"alg": alg, "typ": "JWT", "kid": kid or ("rsa-1" if alg == "RS256" else "ec-1")}
    signed = (b64(json.dumps(head).encode()) + "." + b64(json.dumps(claims).encode())).encode()
    digest = hashlib.sha256(signed).digest()
    if alg == "RS256":
        k = (RSA_N.bit_length() + 7) // 8
        em = b"\x00\x01" + b"\xff" * (k - 3 - len(SHA256_INFO) - 32) + b"\x00" + SHA256_INFO + digest
        sig = pow(int.from_bytes(em, "big"), d, RSA_N).to_bytes(k, "big")
    elif alg == "ES256":
        z = int.from_bytes(digest, "big")
        nonce = int.from_bytes(hashlib.sha256(EC_D.to_bytes(32, "big") + digest).digest(), "big") % N
        point = ec_mul(nonce, G)
        assert point is not None
        r = point[0] % N
        s = pow(nonce, N - 2, N) * (z + r * EC_D) % N
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        sig = b""
    return signed.decode() + "." + b64(sig)


class FakeIdP:
    """An OpenID Connect provider in a few lines: discovery, JWKS, an authorize page that signs in `self.person` at
    once, and a token endpoint that checks the PKCE verifier against the challenge."""

    def __init__(self, issuer: str = "http://127.0.0.1:9", alg: str = "RS256"):
        self.issuer, self.alg = issuer, alg
        self.person: dict = {"sub": "u-1", "email": "ana@example.com", "email_verified": True, "name": "Ana", "groups": ["finance-approvers"]}
        self.codes: dict[str, dict] = {}
        self.extra: dict = {}            # claims a test changes in the next token
        self.meta_extra: dict = {}
        self.seen_forms: list[dict] = []

    def jwks(self) -> dict:
        return {"keys": [{"kty": "RSA", "kid": "rsa-1", "alg": "RS256", "use": "sig", "n": b64(RSA_N.to_bytes(256, "big")), "e": "AQAB"},
                         {"kty": "EC", "kid": "ec-1", "crv": "P-256", "x": b64(EC_Q[0].to_bytes(32, "big")), "y": b64(EC_Q[1].to_bytes(32, "big"))}]}

    def meta(self) -> dict:
        return {"issuer": self.issuer, "authorization_endpoint": self.issuer + "/authorize", "token_endpoint": self.issuer + "/token",
                "jwks_uri": self.issuer + "/jwks", "code_challenge_methods_supported": ["S256"], "id_token_signing_alg_values_supported": ["RS256", "ES256"],
                **self.meta_extra}

    def authorize(self, q: dict) -> str:
        code = b64(hashlib.sha256(json.dumps(q, sort_keys=True).encode()).digest())
        self.codes[code] = q
        return q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q["state"]})

    def token(self, form: dict) -> tuple[int, bytes]:
        self.seen_forms.append(form)
        q = self.codes.pop(form.get("code", ""), None)
        if q is None or form.get("redirect_uri") != q["redirect_uri"]:
            return 400, b'{"error": "invalid_grant"}'
        if b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != q["code_challenge"] or q["code_challenge_method"] != "S256":
            return 400, b'{"error": "invalid_grant", "error_description": "PKCE"}'
        claims = {"iss": self.issuer, "aud": q["client_id"], "iat": NOW, "exp": NOW + 300, "nonce": q["nonce"], **self.person, **self.extra}
        return 200, json.dumps({"id_token": sign(claims, self.alg), "token_type": "Bearer"}).encode()

    def fetch(self, url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
        path = url[len(self.issuer):]
        if path == "/.well-known/openid-configuration":
            return 200, json.dumps(self.meta()).encode()
        if path == "/jwks":
            return 200, json.dumps(self.jwks()).encode()
        if path == "/token" and data is not None:
            return self.token(dict(urllib.parse.parse_qsl(data.decode())))
        return 404, b"{}"


class MemStore:
    """The memory engine's store surface the audit log uses, in a dict (one test runs the real engine)."""

    def __init__(self):
        self.ents: dict[tuple[str, str], dict] = {}
        self.st: dict[str, dict] = {}

    def put(self, category, name, body):
        self.ents[(category, name)] = json.loads(json.dumps(body))

    def get(self, category, name):
        return self.ents.get((category, name), {})

    def all(self, category):
        return [b for (c, _n), b in sorted(self.ents.items()) if c == category]

    def state(self, key):
        return self.st.get(key, {})

    def set_state(self, key, body):
        self.st[key] = dict(body)


SSO = {"issuer": "http://127.0.0.1:9", "client_id": CLIENT, "redirect": "https://knos.example.com/sso/callback", "domains": ["example.com"],
       "viewer": ["finance-readers"], "approver": ["finance-approvers"], "admin": ["knos-admins"]}


def make(idp: FakeIdP | None = None, store=None, **over) -> tuple[sso.Gate, FakeIdP]:
    idp = idp or FakeIdP()
    cfg = sso.config_of({**SSO, "issuer": idp.issuer, **over}, SESSION_KEY)
    return sso.Gate(cfg, sso.Provider(idp.issuer, idp.fetch, clock=lambda: NOW), sso.Audit(store if store is not None else MemStore()), clock=lambda: NOW), idp


def cookies(headers: list[tuple[str, str]]) -> dict[str, str]:
    out = {}
    for k, v in headers:
        if k == "Set-Cookie":
            name, _, rest = v.partition("=")
            out[name] = rest.split(";")[0]
    return out


def sign_in(gate: sso.Gate, idp: FakeIdP, tamper=None) -> tuple[int, dict, dict]:
    """The browser's part, by hand: login, the provider's page, the callback. Returns (status, cookies, body)."""
    status, h, _ = gate.route("GET", "/sso/login?next=/%23approve", {})
    assert status == 302
    login = cookies(h)[sso.LOGIN]
    url = dict(h)["Location"]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert q["code_challenge_method"] == "S256" and q["client_id"] == CLIENT and "openid" in q["scope"].split()
    back = idp.authorize(q)
    target = "/sso/callback?" + urllib.parse.urlsplit(back).query
    if tamper:
        target, login = tamper(target, login)
    status, h, raw = gate.route("GET", target, {"Cookie": f"{sso.LOGIN}={login}"})
    return status, {**cookies(h), "Location": dict(h).get("Location", "")}, json.loads(raw) if raw else {}


def session_of(gate, idp, **person) -> str:
    idp.person.update(person)
    status, got, body = sign_in(gate, idp)
    assert status == 302, body
    return got[sso.SESSION]


def act(gate, session, action="approve", subject="INV-2026-09 lines 1-3", form=None, **h):
    me = json.loads(gate.route("GET", "/sso/me", {"Cookie": f"{sso.SESSION}={session}"})[2])
    headers = {"Cookie": f"{sso.SESSION}={session}", "Content-Type": "application/json", "X-Knos-Form": me["form"] if form is None else form, **h}
    status, _h, raw = gate.route("POST", "/sso/act", headers, json.dumps({"action": action, "subject": subject, "sha256": "ab" * 32}).encode())
    return status, json.loads(raw)


# -- the flow ---------------------------------------------------------------------------------------------------------------

def test_sign_in_sets_a_session_with_the_role_from_groups():
    gate, idp = make()
    status, got, _ = sign_in(gate, idp)
    assert status == 302 and got["Location"] == "/#approve"
    me = gate.who({"Cookie": f"{sso.SESSION}={got[sso.SESSION]}"})
    assert me is not None and me["role"] == "approver" and me["email"] == "ana@example.com" and me["exp"] == NOW + 8 * 3600
    assert got[sso.LOGIN] == ""                                      # the pending sign-in is forgotten
    form = idp.seen_forms[-1]
    assert form["grant_type"] == "authorization_code" and form["client_id"] == CLIENT and len(form["code_verifier"]) >= 43


def test_sign_in_tells_the_page_by_a_cookie_with_no_secret_and_sign_out_clears_it():
    gate, idp = make()
    status, got, _ = sign_in(gate, idp)
    assert status == 302 and got[sso.SIGNED_IN] == "1"      # the approver reads it, and writes its audit lines (web/approver.js ssoOf)
    marker, session = gate._cookie(sso.SIGNED_IN, "1", 60, script=True)[1], gate._cookie(sso.SESSION, "x", 60)[1]
    assert "HttpOnly" not in marker and "HttpOnly" in session          # the session stays out of the page's reach
    status, h, _ = gate.route("GET", "/sso/logout", {"Cookie": f"{sso.SESSION}={got[sso.SESSION]}"})
    assert cookies(h)[sso.SIGNED_IN] == "" and cookies(h)[sso.SESSION] == ""


def test_es256_tokens_are_checked_too():
    gate, idp = make(FakeIdP(alg="ES256"))
    assert sign_in(gate, idp)[0] == 302


def test_client_secret_is_sent_as_basic_auth():
    idp = FakeIdP()
    sent = []

    def fetch(url, data=None, headers=None):
        sent.append(headers or {})
        return idp.fetch(url, data, headers)
    cfg = sso.config_of({**SSO, "issuer": idp.issuer}, SESSION_KEY, "a secret/with+signs\n")
    gate = sso.Gate(cfg, sso.Provider(idp.issuer, fetch, clock=lambda: NOW), None, clock=lambda: NOW)
    assert sign_in(gate, idp)[0] == 302
    basic = [h["Authorization"] for h in sent if "Authorization" in h]
    assert basic == ["Basic " + base64.b64encode(b"knos-selfhost:a+secret%2Fwith%2Bsigns").decode()]
    assert "client_id" not in idp.seen_forms[-1]


@pytest.mark.parametrize("extra, said", [
    ({"nonce": "another"}, "nonce"),
    ({"aud": "someone-else"}, "another client"),
    ({"aud": [CLIENT, "other"]}, "azp"),
    ({"azp": "other"}, "azp"),
    ({"iss": "https://evil.example"}, "another issuer"),
    ({"exp": NOW - 61}, "expired"),
    ({"iat": NOW + 61}, "future"),
    ({"email_verified": False}, "not verified"),
    ({"email": "ana@example.org"}, "domain"),
    ({"email": "ana@sub.example.com"}, "domain"),
    ({"groups": ["finance-readers-not"]}, "none of the groups"),
])
def test_a_bad_token_or_person_is_refused(extra, said):
    gate, idp = make()
    idp.extra = extra
    status, got, body = sign_in(gate, idp)
    assert status == 403 and said in body["error"], body
    assert sso.SESSION not in got


def _swap_token(idp: FakeIdP, change):
    real = idp.token

    def token(form):
        status, raw = real(form)
        doc = json.loads(raw)
        doc["id_token"] = change(doc["id_token"])
        return status, json.dumps(doc).encode()
    idp.token = token        # type: ignore[method-assign]


@pytest.mark.parametrize("change, said", [
    (lambda t: ".".join([t.split(".")[0], b64(json.dumps({**json.loads(base64.urlsafe_b64decode(t.split(".")[1] + "==")), "groups": ["knos-admins"]}).encode()),
                         t.split(".")[2]]), "signature"),                                              # a claim changed after signing
    (lambda t: ".".join([b64(b'{"alg":"none","kid":"rsa-1"}'), t.split(".")[1], ""]), "RS256 or ES256"),
    (lambda t: ".".join([b64(b'{"alg":"HS256","kid":"rsa-1"}'), *t.split(".")[1:]]), "RS256 or ES256"),
    (lambda t: ".".join([b64(b'{"alg":"RS256","kid":"rsa-2"}'), *t.split(".")[1:]]), "signature"),     # a key the provider does not publish
    (lambda t: "not a token", "no ID token"),
])
def test_a_forged_token_is_refused(change, said):
    gate, idp = make()
    _swap_token(idp, change)
    status, _got, body = sign_in(gate, idp)
    assert status == 403 and said in body["error"], body


def test_a_token_signed_by_another_key_is_refused():
    gate, idp = make()
    _swap_token(idp, lambda t: sign(json.loads(base64.urlsafe_b64decode(t.split(".")[1] + "==")), d=RSA_D - 2))
    status, _got, body = sign_in(gate, idp)
    assert status == 403 and "signature" in body["error"]


@pytest.mark.parametrize("tamper, said", [
    (lambda target, login: (target.replace("state=", "state=x"), login), "state"),
    (lambda target, login: (target, ""), "not started here"),
    (lambda target, login: (target, login[:-2] + ("AA" if not login.endswith("AA") else "BB")), "not started here"),
    (lambda target, login: (target.replace("code=", "error=access_denied&code="), login), "refused the sign-in"),
])
def test_the_callback_refuses_a_sign_in_it_did_not_start(tamper, said):
    gate, idp = make()
    status, _got, body = sign_in(gate, idp, tamper)
    assert status == 403 and said in body["error"], body


def test_discovery_is_checked():
    idp = FakeIdP()
    idp.meta_extra = {"issuer": "https://other.example"}
    gate, _ = make(idp)
    assert gate.route("GET", "/sso/login", {})[0] == 403
    idp = FakeIdP()
    idp.meta_extra = {"code_challenge_methods_supported": ["plain"]}
    status, _h, raw = make(idp)[0].route("GET", "/sso/login", {})
    assert status == 403 and "S256" in json.loads(raw)["error"]


def test_next_never_leaves_the_site():
    gate, _idp = make()
    for bad in ("//evil.example/", "https://evil.example/", "/\\evil.example", "/sso/logout"):
        _s, h, _ = gate.route("GET", "/sso/login?" + urllib.parse.urlencode({"next": bad}), {})
        pending = sso.unseal(gate.cfg.session_key, cookies(h)[sso.LOGIN], NOW)
        assert pending is not None and pending["next"] == "/", bad


# -- roles, actions and the audit log ----------------------------------------------------------------------------------

def test_roles_decide_who_approves_exports_and_reads_the_log():
    store = MemStore()
    gate, idp = make(store=store, default_role="viewer")
    viewer = session_of(gate, idp, sub="v", email="vic@example.com", groups=[])
    approver = session_of(gate, idp, sub="a", email="ana@example.com", groups=["finance-approvers"])
    admin = session_of(gate, idp, sub="z", email="zoe@example.com", groups=["finance-readers", "knos-admins"])
    assert act(gate, viewer)[0] == 403
    assert act(gate, viewer, "export")[0] == 403
    status, body = act(gate, approver)
    assert status == 200 and body["written"]["email"] == "ana@example.com" and body["written"]["action"] == "approve"
    assert act(gate, admin, "export")[0] == 200
    assert act(gate, approver, form="wrong")[0] == 403
    assert act(gate, approver, Origin="https://evil.example")[0] == 403
    assert act(gate, approver, "pay")[0] == 400
    assert gate.route("GET", "/sso/audit", {"Cookie": f"{sso.SESSION}={approver}"})[0] == 403
    status, _h, raw = gate.route("GET", "/sso/audit", {"Cookie": f"{sso.SESSION}={admin}"})
    log = json.loads(raw)
    assert status == 200 and log["problems"] == []
    assert [(ln["action"], ln["email"], ln["role"]) for ln in log["lines"]] == [
        ("sign-in", "vic@example.com", "viewer"), ("sign-in", "ana@example.com", "approver"), ("sign-in", "zoe@example.com", "admin"),
        ("approve", "ana@example.com", "approver"), ("export", "zoe@example.com", "admin")]


def test_audit_chain_finds_an_edit_and_a_removal():
    store = MemStore()
    audit = sso.Audit(store)
    for i in range(3):
        audit.add({"sub": "a", "email": "ana@example.com", "role": "approver"}, "approve", f"INV-{i}", at=NOW + i)
    assert audit.check() == []
    store.ents[("sso-audit", "0000000001")]["subject"] = "INV-9"
    assert audit.check() == ["line 1 was changed"]
    store.ents[("sso-audit", "0000000001")]["subject"] = "INV-1"
    del store.ents[("sso-audit", "0000000002")]
    assert audit.check() == ["the head does not name the last line: a line was removed"]


def test_audit_log_lives_in_the_memory_engine(tmp_path):
    from knos.proof import history
    store = history.SibylStore.local(tmp_path / "m", tenant_id="knos-sso")
    audit = sso.Audit(store)
    audit.add({"sub": "a", "email": "ana@example.com", "role": "approver"}, "approve", "INV-1", "cd" * 32, at=NOW)
    audit.add({"sub": "a", "email": "ana@example.com", "role": "approver"}, "export", "INV-1", at=NOW + 1)
    again = sso.Audit(history.SibylStore.local(tmp_path / "m", tenant_id="knos-sso"))
    assert [ln["action"] for ln in again.lines()] == ["approve", "export"] and again.check() == []


def test_sealed_values_cannot_be_changed_or_outlive_their_expiry():
    key = SESSION_KEY.encode()
    v = sso.seal(key, {"role": "viewer", "exp": NOW + 10})
    assert sso.unseal(key, v, NOW) == {"role": "viewer", "exp": NOW + 10}
    raw, mac = v.split(".")
    forged = b64(json.dumps({"role": "admin", "exp": NOW + 10}).encode())
    assert sso.unseal(key, forged + "." + mac, NOW) is None
    assert sso.unseal(key, v, NOW + 10) is None and sso.unseal(b"another key" * 3, v, NOW) is None


def test_config_errors():
    assert sso.errors_of(SSO) == []
    bad = sso.errors_of({**SSO, "issuer": "http://idp.example.com", "redirect": "https://knos.example.com/", "default_role": "boss", "extra": 1})
    joined = " | ".join(bad)
    for said in ("sso.issuer", "sso.redirect", "sso.default_role must be", "sso.extra is not a setting"):
        assert said in joined, joined
    assert any("anyone your provider knows" in e for e in sso.errors_of({**SSO, "domains": [], "default_role": "viewer"}))
    assert any("who may sign in" in e for e in sso.errors_of({k: v for k, v in SSO.items() if k not in ("domains", "viewer", "approver", "admin")}))
    with pytest.raises(sso.Refused, match="32 or more"):
        sso.config_of(SSO, "short")


# -- the record API and the site --------------------------------------------------------------------------------------------

def test_record_api_private_routes_need_a_session(tmp_path):
    gate, idp = make()
    server = record_api.Server({"lookups": 50}, None, tmp_path, now=lambda: NOW, gate=gate)
    order = "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k"
    for path in ("/records/acme.json", f"/orders/{order}"):
        status, _h, body = server.handle(path, {})
        assert status == 401 and body["login"] == "/sso/login", path
    session = session_of(gate, idp)
    assert server.handle("/records/acme.json", {"Cookie": f"{sso.SESSION}={session}"})[0] == 404       # signed in: no such record
    assert server.handle(f"/orders/{order}", {"cookie": f"{sso.SESSION}={session}"})[0] == 200
    assert server.handle("/lookup/acme", {})[0] == 404                                                  # paid, not signed in: unchanged
    assert record_api.Server({"lookups": 50}, None, tmp_path, now=lambda: NOW).handle(f"/orders/{order}", {})[0] == 200   # no [sso]: public as before


def _http(port: int, method: str, path: str, headers: dict | None = None, body: bytes = b"") -> tuple[int, dict, bytes]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        c.request(method, path, body=body or None, headers=headers or {})
        r = c.getresponse()
        got = {}
        for k, v in r.getheaders():
            got.setdefault(k.lower(), []).append(v)
        return r.status, got, r.read()
    finally:
        c.close()


class _IdPHandler(BaseHTTPRequestHandler):
    idp: FakeIdP

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/authorize":
            self.send_response(302)
            self.send_header("Location", self.idp.authorize(dict(urllib.parse.parse_qsl(query))))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(*self.idp.fetch(self.idp.issuer + path))

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        self._send(*self.idp.fetch(self.idp.issuer + self.path, raw, dict(self.headers.items())))

    def _send(self, status, raw):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def _jar(headers: dict) -> dict:
    out = {}
    for v in headers.get("set-cookie", []):
        name, _, rest = v.partition("=")
        out[name] = rest.split(";")[0]
    return out


def test_whole_flow_over_the_loopback(tmp_path):
    (tmp_path / "index.html").write_text("<title>k</title>", encoding="utf-8")
    idp_http = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (_IdPHandler,), {}))
    idp = FakeIdP(f"http://127.0.0.1:{idp_http.server_address[1]}")
    idp_http.RequestHandlerClass.idp = idp          # type: ignore[attr-defined]
    store = MemStore()
    cfg = sso.config_of({**SSO, "issuer": idp.issuer}, SESSION_KEY)
    gate = sso.Gate(cfg, sso.Provider(idp.issuer, clock=lambda: NOW), sso.Audit(store), clock=lambda: NOW)     # the real fetch, over HTTP
    site = selfhost.serve_site(tmp_path, 0, host="127.0.0.1", gate=gate)
    port = site.server_address[1]
    gate.cfg.redirect = f"http://127.0.0.1:{port}/sso/callback"
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (idp_http, site)]
    for t in threads:
        t.start()
    try:
        status, h, _ = _http(port, "GET", "/index.html")
        assert status == 302 and h["location"] == ["/sso/login?next=%2Findex.html"]
        assert _http(port, "POST", "/index.html")[0] == 401
        status, h, _ = _http(port, "GET", h["location"][0])
        assert status == 302 and h["location"][0].startswith(idp.issuer + "/authorize?")
        login = _jar(h)[sso.LOGIN]
        assert "HttpOnly" in h["set-cookie"][0] and "SameSite=Lax" in h["set-cookie"][0]
        to = urllib.parse.urlsplit(h["location"][0])
        status, h, _ = _http(to.port, "GET", to.path + "?" + to.query)
        back = urllib.parse.urlsplit(h["location"][0])
        status, h, raw = _http(port, "GET", back.path + "?" + back.query, {"Cookie": f"{sso.LOGIN}={login}"})
        assert status == 302 and h["location"] == ["/index.html"], raw
        cookie = {"Cookie": f"{sso.SESSION}={_jar(h)[sso.SESSION]}"}
        status, h, raw = _http(port, "GET", "/index.html", cookie)
        assert status == 200 and raw == b"<title>k</title>" and h["cache-control"] == ["private, no-store"]
        me = json.loads(_http(port, "GET", "/sso/me", cookie)[2])
        assert me["role"] == "approver" and me["can"] == {"approve": True, "export": True, "audit": False}
        for action in ("approve", "export"):
            status, _h, raw = _http(port, "POST", "/sso/act", {**cookie, "Content-Type": "application/json", "X-Knos-Form": me["form"]},
                                    json.dumps({"action": action, "subject": "INV-2026-09"}).encode())
            assert status == 200, raw
        assert [(ln["action"], ln["email"]) for ln in sso.Audit(store).lines()] == [
            ("sign-in", "ana@example.com"), ("approve", "ana@example.com"), ("export", "ana@example.com")]
        status, h, _ = _http(port, "GET", "/sso/logout", cookie)
        assert status == 200 and _jar(h)[sso.SESSION] == ""
    finally:
        for s in (idp_http, site):
            s.shutdown()
            s.server_close()
        for t in threads:
            t.join(5)


# -- the config file ---------------------------------------------------------------------------------------------------------

SELFHOST = """
[chain]
rpc = "https://api.devnet.solana.com"

[keys]
sso_session = "secrets/session"

[sso]
issuer = "https://login.example.com"
client_id = "knos"
redirect = "https://knos.example.com/sso/callback"
domains = ["example.com"]
approver = ["finance-approvers"]
admin = ["knos-admins"]

[record]
offer = "offer.json"

[site]
enabled = true
"""


def test_selfhost_config_with_sso(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "session").write_text(SESSION_KEY, encoding="utf-8")
    (tmp_path / "offer.json").write_text("{}", encoding="utf-8")
    c = selfhost.check(SELFHOST, tmp_path)
    assert c.errors == [] and c.ok(files=True), c.errors
    assert [(r, n) for r, n, _p in selfhost.needs(c)] == [("site", "sso_session"), ("record", "sso_session")]
    said = "\n".join(selfhost.describe(c))
    assert "Sign-in: OpenID Connect through https://login.example.com" in said and "fake provider only" in said
    gate = sso.gate_of(c.config, tmp_path)
    assert gate is not None and gate.cfg.groups["approver"] == ("finance-approvers",) and gate.audit is None
    assert any("needs keys.sso_session" in e for e in selfhost.check(SELFHOST.replace('sso_session = "secrets/session"', ""), tmp_path).errors)
    assert any("sso.issuer" in e for e in selfhost.check(SELFHOST.replace("https://login", "http://login"), tmp_path).errors)
    assert any("read only with [sso]" in e for e in selfhost.check(SELFHOST.split("[sso]")[0] + "[site]\nenabled = true\n", tmp_path).errors)
