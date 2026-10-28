"""Milestone evidence checks, sign-in, and the new HTTP routes without escrow keys (no network, no chain)."""
import base64
import hashlib
import io
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from knos_wanted import auth, preorder, server
from knos_wanted.qloo_mcp import InProcess, Qloo
from knos_wanted.qloo_rest import Client

REC = {"claim_id": "knos-idea:" + "a" * 32}


def page(body: bytes):
    return lambda req, timeout=None: io.BytesIO(body)


def ok_host(host):
    return None


def test_evidence_must_contain_the_claim_id():
    ev, body = preorder.verify(REC, "https://maker.example/p", opener=page(b"<p>knos-idea:" + b"a" * 32 + b"</p>"), resolve=ok_host)
    assert ev["contains_claim_id"] and ev["sha256"] == hashlib.sha256(body).hexdigest()
    with pytest.raises(preorder.NotVerified, match="does not contain"):
        preorder.verify(REC, "https://maker.example/p", opener=page(b"nothing here"), resolve=ok_host)


@pytest.mark.parametrize("url", ["http://maker.example/p", "https://user:pw@maker.example/", "https://maker.example:8443/x", "ftp://x/y", ""])
def test_evidence_url_shape(url):
    with pytest.raises(preorder.NotVerified):
        preorder.fetch_evidence(url, opener=page(b"x"), resolve=ok_host)


def test_evidence_private_addresses_refused():
    with pytest.raises(preorder.NotVerified, match="private"):
        preorder.fetch_evidence("https://localhost/x", opener=page(b"x"))


def test_evidence_size_limit():
    with pytest.raises(preorder.NotVerified, match="larger"):
        preorder.fetch_evidence("https://maker.example/p", opener=page(b"x" * (preorder.MAX_EVIDENCE + 1)), resolve=ok_host)


def test_sessions_and_guest_label():
    s = auth.guest("ada@example.com")
    assert s["kind"] == "guest" and s["label"] == "Guest " + s["sub"][6:10] and "@" not in s["label"]   # never what was typed
    assert auth.who("Bearer " + s["token"])["sub"] == s["sub"]
    assert auth.who("Bearer " + s["token"][:-2] + "xx") is None and auth.who(None) is None
    assert auth.who("Bearer " + s["token"], now=s["exp"] + 1) is None
    assert auth.config()["email_provider"] is False


def test_google_token_checked_against_client_id(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    info = {"aud": "cid.apps.googleusercontent.com", "iss": "accounts.google.com", "exp": "9999999999", "sub": "42",
            "email": "a@b.c", "email_verified": "true"}
    op = lambda url, timeout=None: io.BytesIO(json.dumps(info).encode())   # noqa: E731
    assert auth.google("x" * 40, opener=op)["sub"] == "google:42"
    info["aud"] = "other"
    with pytest.raises(auth.AuthError, match="another app"):
        auth.google("x" * 40, opener=op)
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    with pytest.raises(auth.AuthError, match="not configured"):
        auth.google("x" * 40, opener=op)


def test_passkey_register_and_login():
    ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")
    from cryptography.hazmat.primitives import hashes, serialization
    key = ec.generate_private_key(ec.SECP256R1())
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    origin, rp = "http://localhost:8080", "localhost"
    cid = auth.b64u(b"cred-1")

    def cd(kind):
        return auth.b64u(json.dumps({"type": kind, "challenge": auth.challenge(), "origin": origin}).encode())
    s = auth.register({"id": cid, "clientDataJSON": cd("webauthn.create"), "publicKey": auth.b64u(spki), "alg": -7}, origin, "Ada")
    assert s["sub"] == auth.identity(spki) and s["kind"] == "passkey"
    cdj = cd("webauthn.get")
    ad = hashlib.sha256(rp.encode()).digest() + b"\x05" + b"\x00\x00\x00\x01"
    sig = key.sign(ad + hashlib.sha256(base64.urlsafe_b64decode(cdj + "==")).digest(), ec.ECDSA(hashes.SHA256()))
    got = auth.login({"id": cid, "clientDataJSON": cdj, "authenticatorData": auth.b64u(ad), "signature": auth.b64u(sig)}, origin, rp)
    assert got["sub"] == s["sub"]
    with pytest.raises(auth.AuthError):          # the challenge was spent
        auth.login({"id": cid, "clientDataJSON": cdj, "authenticatorData": auth.b64u(ad), "signature": auth.b64u(sig)}, origin, rp)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("KNOS_WANTED_REFEREE_KEYS", raising=False)
    state = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None), Client(key="", base="https://example.test", folder=tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, path, body=None, token=None):
    h = {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})}
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_check_without_key_cannot_decide_and_preorder_is_gated(app):
    st, r = call(app, "/api/check", {"idea": "A smart water bottle that glows to remind you to drink", "place": "Lagos", "picked": True})
    assert st == 200 and r["decision"]["verdict"] == "CANNOT_DECIDE" and r["decision"]["target_units"] is None
    assert call(app, "/api/check", {"idea": "mail me at jane@example.com about a bottle"})[0] == 400
    assert call(app, "/api/preorder", {"report": r["hash"], "units": 5})[0] == 401
    tok = call(app, "/api/auth/guest", {"label": "ada"})[1]["token"]
    st, e = call(app, "/api/preorder", {"report": r["hash"], "units": 5}, tok)
    assert st in (400, 503)
    st, s = call(app, "/api/status")
    assert s["preorders"]["available"] is False and s["preorders"]["why"] == "holding money is unavailable on this server"
    assert s["qloo_rest"]["rest"] is False and s["qloo_rest"]["reason"] == "no Qloo API key on this server"
    assert call(app, "/api/report?hash=" + r["hash"])[1]["hash"] == r["hash"]


def test_preorder_refuses_reports_that_are_not_open():
    with pytest.raises((ValueError, preorder.Unavailable)):
        preorder.lock({"hash": "0" * 64, "decision": {"verdict": "REFUSE"}, "label": "LIVE"}, 5, "guest: x")


def test_a_maker_can_repost_evidence_ten_times_an_hour_per_commitment(app):
    tok = call(app, "/api/auth/guest", {"label": "maker"})[1]["token"]
    one, two = "1" * 44, "2" * 44
    codes = [call(app, "/api/milestone", {"commitment": one, "evidence_url": "https://x.example/"}, tok)[0] for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429           # unknown commitment (400) until the per-commitment cap
    assert call(app, "/api/milestone", {"commitment": two, "evidence_url": "https://x.example/"}, tok)[0] == 400


def test_preflight_builds_the_real_preorder_transaction_and_reports_the_simulation(monkeypatch):
    pytest.importorskip("solders")
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

    keys = [list(bytes(Keypair())) for _ in range(3)]
    monkeypatch.setenv("KNOS_WANTED_REFEREE_KEYS", json.dumps(keys))
    monkeypatch.setenv("KNOS_WANTED_DEVNET_KEYPAIR", json.dumps(list(bytes(Keypair()))))
    monkeypatch.setenv("KNOS_WANTED_MINT", str(Pubkey.from_string("So11111111111111111111111111111111111111112")))

    class Led:
        url = "https://api.devnet.solana.com"

        def account(self, addr):
            return None
    seen = {}

    def sim(led, ixs, payer, signers):
        seen["n"] = len(ixs)
        return {"err": {"InstructionError": [3, {"Custom": 1}]}, "logs": ["Program log: Error: insufficient funds"]}
    monkeypatch.setattr(preorder, "_simulate", sim)
    ok, why = preorder.preflight(Led())
    assert not ok and "devnet simulation failed" in why and "insufficient funds" in why and seen["n"] == 4   # 2 ATAs, mint, fund
    monkeypatch.setattr(preorder, "_simulate", lambda *a: {"err": None, "unitsConsumed": 4242})
    ok, why = preorder.preflight(Led())
    assert ok and "4242" in why
    st = preorder.preflight_status(force=True, led=Led())
    assert st["available"] is True and "simulateTransaction" in st["preflight"]
    monkeypatch.setattr(preorder, "_simulate", lambda *a: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'yaml'")))
    st = preorder.preflight_status(force=True, led=Led())
    assert st["available"] is False and "ModuleNotFoundError" in st["why"]
    monkeypatch.delenv("KNOS_WANTED_REFEREE_KEYS")
    assert preorder.preflight_status(force=True)["available"] is False


def test_raw_errors_never_reach_the_user(app, monkeypatch):
    from knos_wanted import preorder as po
    tok = call(app, "/api/auth/guest", {"label": "x"})[1]["token"]
    monkeypatch.setattr(po, "load", lambda order: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'yaml'")))
    st, e = call(app, "/api/milestone", {"commitment": "1" * 44, "evidence_url": "https://x.example/"}, tok)
    assert st == 502 and "yaml" not in e["error"] and "ModuleNotFoundError" not in e["error"] and e["ref"]


def test_the_real_preorder_transactions_fit_with_a_50_byte_margin_for_the_largest_inputs():
    pytest.importorskip("solders")
    sizes = preorder.largest_preorder_txs()
    assert sizes["preorder"] <= preorder.TX_BUDGET == 1182 and sizes["preflight"] <= 1182 and sizes["blink"] <= 1182, sizes


def test_preflight_never_puts_the_mint_creation_in_the_simulated_transaction(monkeypatch):
    pytest.importorskip("solders")
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

    monkeypatch.setenv("KNOS_WANTED_REFEREE_KEYS", json.dumps([list(bytes(Keypair())) for _ in range(3)]))
    monkeypatch.setenv("KNOS_WANTED_DEVNET_KEYPAIR", json.dumps(list(bytes(Keypair()))))
    monkeypatch.delenv("KNOS_WANTED_MINT", raising=False)
    made = []

    def mint(led=None, create=True):
        if not create:
            raise preorder.escrow.EscrowUnavailable("no test mint yet")
        made.append(1)
        return Pubkey.from_string("So11111111111111111111111111111111111111112")
    monkeypatch.setattr(preorder.escrow, "mint", mint)

    class Led:
        url = "https://api.devnet.solana.com"

        def account(self, addr):
            return None
    sims = []
    monkeypatch.setattr(preorder, "_simulate", lambda led, ixs, payer, signers: sims.append((len(ixs), len(signers))) or {"err": None})
    ok, why = preorder.preflight(Led())
    assert ok and made == [1] and sims == [(4, 1)]          # the mint was made apart; the simulated tx: 2 ATAs, top-up, order
    monkeypatch.setattr(preorder, "tx_size", lambda *a: 1200)
    ok, why = preorder.preflight(Led())
    assert not ok and "1200 bytes" in why
