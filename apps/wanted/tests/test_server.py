import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from knos_wanted import server


@pytest.fixture
def app():
    state = server.State()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    httpd.shutdown()


def call(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, raw if not r.headers.get("Content-Type", "").startswith("application/json") else json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_page_and_status(app):
    base, _ = app
    st, page = call(base, "/app/")
    assert st == 200 and b"Knos" in page and b"not a sales forecast" in page
    assert b"Knos Wanted" not in page                     # no sub-brand: it is Knos's demand check
    st, s = call(base, "/api/status")
    assert st == 200 and s["mode"] == "offline" and s["label"] == "OPEN SIGNALS" and s["cluster"] == "devnet"
    assert s["deps"]["open_signals"]["state"] == "not asked"
    assert "_API_KEY" not in json.dumps(s)
    st, _ = call(base, "/static/app.js")
    assert st == 200
    assert call(base, "/static/../server.py")[0] == 404




def test_the_check_and_privacy_over_http(app):
    base, state = app
    st, e = call(base, "/api/check", {"idea": "a bottle, mail jane@example.com"})
    assert st == 400 and "no personal data" in e["error"]
    st, r = call(base, "/api/check", {"idea": "Vegan street food truck for students in Lagos", "place": "Lagos"})
    assert st == 200 and state.known(r["hash"]) and r["decision"]["verdict"] == "CANNOT_DECIDE"   # no source asked in tests
    assert r["story"]["sentence"] == "No signal yet" and "record" in r
    for gone in ("/api/maker/start", "/api/buyer/start"):
        assert call(base, gone, {"idea": "x"})[0] == 404


def test_preorder_needs_a_known_report(app):
    base, _ = app
    for path in ("/api/preorder/demo", "/api/preorder/faucet", "/api/preorder/tx", "/api/preorder/submit"):
        assert call(base, path, {"hash": "0" * 64})[0] == 401          # anonymous: no money and no faucet
    from knos_wanted import auth
    tok = auth.guest("t")["token"]
    req = urllib.request.Request(base + "/api/preorder/demo", data=json.dumps({"hash": "0" * 64}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok})
    try:
        urllib.request.urlopen(req, timeout=30)
        raise AssertionError("an unknown report was accepted")
    except urllib.error.HTTPError as e:
        assert e.code in (400, 503)


def test_rate_limit(app, monkeypatch):
    base, _ = app
    monkeypatch.setitem(server.LIMITS, "check", (2, 600))
    codes = [call(base, "/api/check", {"idea": "Board game cafe in Paris", "picked": True})[0] for _ in range(3)]
    assert codes == [200, 200, 429]


def test_presence_and_draft_autosave_never_use_up_the_persons_limit(app, monkeypatch):
    base, _ = app
    monkeypatch.setitem(server.LIMITS, "product", (2, 600))
    monkeypatch.setitem(server.LIMITS, "live", (50, 600))
    for _ in range(5):                                    # cursors every 15 s: their own bucket
        assert call(base, "/api/presence", {"page": "a" * 16, "me": "m1", "x": 0.1, "y": 0.2})[0] == 200
    brief = {"milestones": [{"name": "x", "target": "1 test", "verifier": {"check": "ci"}, "deadline_days": 1}]}
    codes = [call(base, "/api/ready", {"brief": brief})[0] for _ in range(3)]
    assert codes == [200, 200, 429]                       # the person's own steps keep their full limit


def test_the_front_door_may_read_the_check(app):
    base, _ = app
    req = urllib.request.Request(base + "/api/status", headers={"Origin": "https://drexthealpha.github.io"})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert json.loads(r.read())["label"] == "OPEN SIGNALS"
        assert r.headers.get("Access-Control-Allow-Origin") == "https://drexthealpha.github.io"
    other = urllib.request.Request(base + "/api/status", headers={"Origin": "https://evil.example"})
    with urllib.request.urlopen(other, timeout=30) as r:
        assert r.headers.get("Access-Control-Allow-Origin") is None
