"""The agent's live crossing, its memory (Sibyl), MCP over HTTP, the Blink, sign-in providers, factoring and the price
tier, on SYNTHETIC fixtures (no network, no chain)."""
import io
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from test_check import IDEA, FakeQloo

from knos_wanted import agent, auth, blink, check, research, server
from knos_wanted.qloo_mcp import InProcess, Qloo

CARD = {"hash": "c" * 64, "title": "A synthetic landmark paper", "year": 2016, "cited_by_count": 5000, "retraction": {"retracted": False},
        "nobel": None, "proven_result": {"quote": "We present a sensor.", "source": "https://doi.org/10.0/x"}, "topics": ["Sweat"],
        "product": IDEA, "product_source": "synthetic", "field": "Engineering", "topic": "Wearables", "ids": {"doi": "10.0/x"}}


@pytest.fixture
def st(monkeypatch):
    s = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None), FakeQloo())
    monkeypatch.setattr(research, "research_card", lambda ref, product=None, **k: {**CARD, "product": product or CARD["product"]})
    return s


def test_the_crossing_streams_steps_sets_the_plan_and_remembers(st):
    job = agent.start(st, ref="10.0/x", place="Lagos", wait=True)
    assert job["status"] == "done", job.get("error")
    kinds = [s["kind"] for s in job["steps"]]
    assert kinds[0] == "memory" and "paper" in kinds and kinds.count("qloo") >= 8 and "decision" in kinds
    q = [s for s in job["steps"] if s["kind"] == "qloo"]
    assert all(s["tool"].startswith("GET /") and s["effect"] and s["output"] for s in q)          # every Qloo step: call, output, effect
    assert any(s["title"].startswith("launch cities") for s in q) and any("semantic" in s["title"] for s in q)
    rep = st.report(job["report"])
    plan = rep["decision"]["plan"]
    assert plan["tier"] in ("budget", "mid", "premium") and plan["unit_price"] in (1, 2, 4) and plan["where"] and plan["who"]["age"]
    assert plan["escrow_target"] == plan["target_units"] * plan["unit_price"]
    titles = [s["title"] for s in job["steps"]]
    assert "WHO: the target audience" in titles and "PRICE: the tier" in titles and "HELD: target and reserve" in titles
    again = agent.start(st, ref="10.0/x", place="Lagos", wait=True)                 # Sibyl: the agent's memory of this paper
    remembered = next(s for s in again["steps"] if s["title"] == "the agent remembers this paper")   # after the HOT plan step (round 9B)
    assert "decision OPEN" in remembered["output"]


def test_price_tier_from_spending_segments():
    seg = lambda n, lift, premium: {"name": n, "lift": lift, "premium": premium, "src": 3}   # noqa: E731
    # the spending-habit segments scored like the audience: a premium segment's lift minus Discount Shoppers'
    assert check.price_tier([seg("Gourmand Fine Dining", 0.02, True), seg("Discount Shoppers", 0.0, False)])["tier"] == "premium"
    assert check.price_tier([seg("Gourmand Fine Dining", -0.01, True), seg("Discount Shoppers", 0.0, False)])["tier"] == "budget"
    assert check.price_tier([seg("Gourmand Fine Dining", 0.001, True), seg("Discount Shoppers", 0.0, False)])["tier"] == "mid"
    # without both lifts, the places' median price level decides
    assert check.price_tier([seg("Discount Shoppers", 0.0, False)], [3, 4, 2])["tier"] == "premium"
    assert check.price_tier([], [1, 1, 2])["tier"] == "budget" and check.price_tier([]) is None
    assert check.price_tier([seg("Gourmand Fine Dining", 0.02, True), seg("Discount Shoppers", 0.0, False)], [3, 4, 2])["venue_check"] == "agrees"


@pytest.fixture
def http(st):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(st))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", st
    httpd.shutdown()


def post(base, path, body, headers=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=30) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def test_mcp_over_http_lists_and_calls(http):
    base, _ = http
    c, init, _ = post(base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert c == 200 and init["result"]["protocolVersion"] and init["result"]["capabilities"]["tools"]
    assert post(base, "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
    c, lst, _ = post(base, "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in lst["result"]["tools"]]
    assert names[:3] == ["knos_cross", "knos_research_card", "knos_demand_check"] and len(names) >= 10   # roles 1-5 covered (round 9)
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "knos_cross", "arguments": {"ref": "10.0/x"}}}
    c, no, h = post(base, "/mcp", call)                      # a crossing writes: it needs a credential in the header (T12)
    assert no["result"]["isError"] and "resource_metadata" in h["WWW-Authenticate"]
    tok = auth.guest("tester")["token"]
    c, x, _ = post(base, "/mcp", call, {"Authorization": "Bearer " + tok})
    sc = x["result"]["structuredContent"]
    assert sc["status"] == "done" and sc["decision"]["verdict"] == "OPEN" and len(sc["steps"]) > 10
    assert get(base, "/mcp")[0] == 200         # a discovery document (name, transport, where to POST tools/list)


def test_the_live_crossing_over_the_web_api(http):
    base, st = http
    c, j, _ = post(base, "/api/cross", {"ref": "10.0/x"})
    assert c == 200 and j["id"]
    for _ in range(300):                       # up to 30 s: four test workers share this machine
        c, p, _ = get(base, f"/api/cross?id={j['id']}&since=0")
        if p["status"] != "running":
            break
        import time
        time.sleep(0.1)
    assert p["status"] == "done" and p["total"] == len(p["steps"]) and p["report"]


def test_the_blink(http):
    base, st = http
    job = agent.start(st, ref="10.0/x", wait=True)
    c, rules, h = get(base, "/actions.json")
    assert c == 200 and rules["rules"][0]["pathPattern"] == "/api/actions/**" and h["Access-Control-Allow-Origin"] == "*"
    c, a, h = get(base, f"/api/actions/preorder?report={job['report']}")
    assert c == 200 and a["type"] == "action" and a["links"]["actions"][0]["href"].endswith("&units=5") and h["X-Action-Version"]
    assert "set by Qloo" in a["description"] and h["X-Blockchain-Ids"].startswith("solana:")
    c, e, _ = post(base, f"/api/actions/preorder?report={job['report']}&units=5", {"account": "So11111111111111111111111111111111111111112"})
    assert c == 400 and "holding money is unavailable" in e["message"]                          # no escrow keys in tests: refused plainly


def test_solana_pay_funds_a_milestone_from_any_wallet(http):
    from knos_wanted import blink
    base, st = http
    link = blink.pay_link(base, "prj_x", "m1", 7)
    assert link.startswith("solana:http") and "%3Fproject%3Dprj_x%26milestone%3Dm1%26units%3D7" in link   # the spec's URL-encoded link
    c, g, h = get(base, "/api/pay/fund?project=prj_x&milestone=m1&units=7")
    assert c == 200 and g["label"] and g["icon"].endswith("/static/icon.svg") and h["Access-Control-Allow-Origin"] == "*"
    c, e, _ = post(base, "/api/pay/fund?project=prj_x&milestone=m1&units=7", {"account": "So11111111111111111111111111111111111111112"})
    assert c == 400 and e["message"]                                                   # an unknown project is refused plainly


def test_sign_in_providers_switch_on_with_their_keys(monkeypatch):
    for k in ("GOOGLE_CLIENT_ID", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET", "RESEND_API_KEY", "KNOS_WANTED_EMAIL_FROM"):
        monkeypatch.delenv(k, raising=False)
    cfg = auth.config()
    assert cfg["google_client_id"] is None and cfg["orcid"] is False and cfg["email_provider"] is False
    with pytest.raises(auth.AuthError, match="ORCID sign-in is not configured"):
        auth.orcid_authorize("https://knos.example/auth/orcid/callback")
    monkeypatch.setenv("ORCID_CLIENT_ID", "APP-X")
    monkeypatch.setenv("ORCID_CLIENT_SECRET", "s")
    url = auth.orcid_authorize("https://knos.example/auth/orcid/callback")
    assert url.startswith("https://orcid.org/oauth/authorize?") and "scope=%2Fauthenticate" in url
    state = url.split("state=")[1]
    ok = lambda req, timeout=None: io.BytesIO(json.dumps({"orcid": "0000-0002-1825-0097", "name": "Josiah Carberry"}).encode())  # noqa: E731
    s = auth.orcid_callback("code", state, "https://knos.example/auth/orcid/callback", opener=ok)
    assert s["sub"] == "orcid:0000-0002-1825-0097" and s["kind"] == "orcid"
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("KNOS_WANTED_EMAIL_FROM", "Knos <signin@knos.example>")
    sent = {}

    def mail(req, timeout=None):
        sent["body"] = json.loads(req.data)
        return io.BytesIO(b"{}")
    assert auth.email_link("ada@example.com", "https://knos.example", opener=mail)["sent"]
    tok = sent["body"]["text"].split("#magic=")[1].split()[0]
    s = auth.email_verify(tok)
    assert s["label"] == "Email " + s["sub"][6:10] and "@" not in s["label"]                 # never the address itself
    with pytest.raises(auth.AuthError, match="already used"):
        auth.email_verify(tok)
    assert auth.config()["orcid"] and auth.config()["email_provider"]


def test_factoring_is_signed_by_passkeys_and_nothing_is_simulated(monkeypatch, tmp_path):
    """The 0.4.0 offer recorded a SIMULATED Assign; factoring is now real and every step needs a passkey
    (knos_wanted.wallets; the chain flow is tests/test_passkey_money_app.py). What is refused here, before any chain."""
    import pytest

    from knos_wanted import preorder, wallets
    assert not hasattr(blink, "factor")
    rec = {"order": "So11111111111111111111111111111111111111112", "units": 10, "unit_price": 2, "status": "locked",
           "maker_wallet": "4dFAUoXNDbmPCJ1CPCFyaJqLW5WWY3i2TE3VKEdSbC31", "doc": {"payee": {"payee_id": 10 ** 15 + 7}},
           "report": "b" * 64, "claim_id": "knos-idea:" + "0" * 32}
    preorder._save(rec)
    guest = {"sub": "guest:abc", "kind": "guest", "label": "g"}
    with pytest.raises(wallets.NeedPasskey):
        wallets.quote(None, guest, rec["order"], 9000, "knos.dev")
    with pytest.raises(wallets.NeedPasskey):
        wallets.prepare_accept(None, guest, rec["order"], "q1")
    from knos_wanted import auth
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    spki = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    sub = auth.identity(spki)
    auth._remember(sub, auth.b64u(b"cred-1"), spki)
    with pytest.raises(ValueError, match="receivable wallet"):       # a pre-order not paid to a maker's passkey wallet
        wallets.quote(None, {"sub": sub, "kind": "passkey", "label": "l"}, rec["order"], 9000, "knos.dev")
    assert preorder.load(rec["order"]).get("factoring") is None        # nothing recorded off-program

