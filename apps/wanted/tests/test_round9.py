"""Round 9A: six roles on one page — the funder and contributor endpoints, the agent door for roles 1-5, the
language file, and the first-load budget. SYNTHETIC fixtures; no network, no chain."""
import hashlib
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from test_check import IDEA, FakeQloo

from knos_wanted import agent, server, tasks
from knos_wanted.qloo_mcp import InProcess, Qloo

STATIC = Path(server.__file__).parent / "static"


@pytest.fixture
def app():
    st = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None), FakeQloo())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(st))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", st
    httpd.shutdown()


def call(base, path, body=None, tok=None, headers=None):
    h = {"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {}), **(headers or {})}
    req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if (r.headers.get("Content-Type") or "").startswith("application/json") else raw), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def test_the_verify_page_and_the_app_page_are_served(app):
    base, _ = app
    st, page, h = call(base, "/verify")
    assert st == 200 and b"How we verify" in page and b"review_evidence" in page and b"no real funds" in page
    st, page, _ = call(base, "/app/")
    for needle in (b"Knos", b"not a sales forecast", b"not a prediction about one person", b'id="lang"',
                   b"v-fund", b"v-contribute", b"v-agents", b"/verify"):
        assert needle in page, needle
    assert b"Knos Wanted" not in page


def test_funder_and_task_endpoints_are_gated_and_honest(app):
    base, _ = app
    assert call(base, "/api/fund", {"report": "0" * 64, "units": 5})[0] == 401            # money: sign in first
    assert call(base, "/api/task/submit", {"round": "x", "code": "print(1)" * 3})[0] == 401
    tok = call(base, "/api/auth/guest", {"label": "f"})[1]["token"]
    st, e, _ = call(base, "/api/fund", {"report": "0" * 64, "units": 5}, tok)
    assert st == 400 and "unknown report" in e["error"]
    st, got, _ = call(base, "/api/tasks")
    assert st == 200 and "test money" in got["note"]
    assert got["rounds"] and got["rounds"][0]["demo"] is True              # an empty server seeds the demo round (round 10)
    st, e, _ = call(base, "/api/task/submit", {"round": "x", "code": "short", "name": "a"}, tok)
    assert st == 400 and "10 to 100,000" in e["error"]


def test_paging_on_the_buyer_and_funder_lists(app):
    base, st = app
    agent.JOBS.clear()
    for i in range(4):
        agent.JOBS[f"j{i}"] = {"id": f"j{i}", "status": "done", "steps": [], "started": float(i), "report": None, "idea": f"i{i}", "ref": None}
    s, got, _ = call(base, "/api/crossings?take=2&offset=1")
    assert s == 200 and len(got["crossings"]) == 2 and got["take"] == 2 and got["offset"] == 1
    assert [c["id"] for c in got["crossings"]] == ["j2", "j1"]                            # newest first, then the page
    s, got, _ = call(base, "/api/commitments?take=3&offset=0")
    assert s == 200 and got["take"] == 3


MONEY_TOOLS = {"knos_sign_in", "knos_preorder", "knos_evidence", "knos_task_submit"}


def test_mcp_covers_the_roles_with_a_confirm_convention(app):
    base, _ = app
    s, lst, _ = call(base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in lst["result"]["tools"]}
    assert {"knos_cross", "knos_research_card", "knos_demand_check", "knos_crossings", "knos_milestones", "knos_tasks",
            "knos_memory_recall"} | MONEY_TOOLS <= names
    for t in lst["result"]["tools"]:
        if t["name"] in MONEY_TOOLS:
            assert t["description"].endswith("ask your human first.") and "test money" in t["description"] and len(t["description"]) < 160
        if t["name"] in MONEY_TOOLS - {"knos_sign_in"}:          # a person's session, or a Bearer header alone (T12)
            assert "session" in t["inputSchema"]["properties"] and "session" not in t["inputSchema"]["required"]
    s, x, _ = call(base, "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "knos_preorder", "arguments": {"report": "0" * 64, "units": 5, "session": "bad"}}})
    sc = x["result"]
    assert sc.get("isError") and "knos_sign_in" in sc["content"][0]["text"]
    s, si, _ = call(base, "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                   "params": {"name": "knos_sign_in", "arguments": {"label": "e2e human"}}})
    tok = si["result"]["structuredContent"]["token"]
    assert tok and si["result"]["structuredContent"]["label"].startswith("Guest ")
    s, tk, _ = call(base, "/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "knos_tasks", "arguments": {}}})
    assert tk["result"]["structuredContent"]["rounds"][0]["demo"] is True
    s, page, h = call(base, "/mcp", None, headers={"Accept": "text/html"})
    assert s == 200 and b"Model Context Protocol" in page and b"knos_sign_in" in page


def test_every_language_covers_the_english_keys_and_arabic_is_rtl():
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    langs = re.findall(r"^  (\w\w): \{", js, re.M)
    assert set(langs) == {"en", "fr", "es", "pt", "ar", "hi", "zh"}
    blocks = {m.group(1): m.group(2) for m in re.finditer(r"^  (\w\w): \{(.*?)^  \},?$", js, re.M | re.S)}
    keys = {lang: set(re.findall(r"^\s{4}(\w+):", body, re.M)) for lang, body in blocks.items()}
    for lang in langs:
        assert keys[lang] == keys["en"], (lang, keys["en"] ^ keys[lang])
    assert 'rtl: ["ar"]' in js
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'dir = I.rtl.includes(LANG) ? "rtl" : "ltr"' in app and "knos.lang" in app


def test_first_load_is_under_200_kb():
    total = sum((STATIC / f).stat().st_size for f in ("index.html", "style.css", "app.js", "i18n.js", "icon.svg"))
    assert total < 200_000, total


def test_the_pages_home_links_the_app_prominently():
    web = Path(server.__file__).resolve().parents[3] / "web"
    views = (web / "views.js").read_text(encoding="utf-8")
    # the site declares the app as a page added by name (its link under More, its section, its lazy module)
    assert 'apps: { file: "./apps.js", draw: "renderApps", nav: "Research products" }' in views
    mod = (web / "apps.js").read_text(encoding="utf-8")
    assert "export function renderApps" in mod and 'href="wanted.html"' in mod and "https://knos.onrender.com/app/" in mod
    assert "healthz" in mod and "test money" in mod and "click" in mod   # on press: straight to the app when awake; the wake page otherwise


def test_an_empty_server_seeds_one_demo_round_and_judges_a_submission(monkeypatch, tmp_path):
    monkeypatch.delenv("KNOS_GAME_DIR", raising=False)
    monkeypatch.setenv("KNOS_WANTED_STATE", str(tmp_path / "state"))           # Render's wiped /data
    got = tasks.listing()
    r = got["rounds"][0]
    assert r["demo"] is True and r["id"].startswith("knos-demo-") and "DEMO ROUND" in r["label"] and "test money" in r["label"]
    code = "def propose(task, history):\n    return {\"params\": {\"n_estimators\": 40}}\n"
    out = tasks.submit(r["id"], "stranger", code, "guest: stranger")
    assert out["result"].get("decision") in ("accepted", "failed", "refused") and "referee" in out["note"]
    assert tasks.listing()["rounds"][0]["id"] == r["id"]                       # one open demo round at a time, not two
    assert (Path(server.__file__).resolve().parents[3] / "examples" / "autoresearch" / "task.json").exists()
    docker = (Path(server.__file__).resolve().parents[2] / "wanted" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY examples/autoresearch" in docker                              # the image carries the demo task


def test_a_contributors_train_py_reaches_the_referee_and_may_be_resubmitted(monkeypatch, tmp_path):
    monkeypatch.delenv("KNOS_GAME_DIR", raising=False)
    monkeypatch.setenv("KNOS_WANTED_STATE", str(tmp_path / "state"))
    r = tasks.listing()["rounds"][0]
    s = r["submit"]
    assert s["file"] == "train.py" and s["readme"].endswith("examples/autoresearch/README.md") and s["attempts_per_round"] >= 2
    base = (Path(server.__file__).resolve().parents[3] / "examples" / "autoresearch" / "train.py").read_text(encoding="utf-8")
    better = base.replace("'linear'", "'square'", 1).replace("'standardize': False", "'standardize': True", 1)
    assert better != base
    out = tasks.submit(r["id"], "  Ada  Lovelace ", better, "guest: ada", sub="guest-ada")
    assert out["name"] == "Ada Lovelace"
    assert out["result"]["sha256"] == out["submitted_sha256"] == hashlib.sha256(better.encode()).hexdigest()
    assert out["result"]["decision"] == "scored" and out["result"]["n"] == 1, out
    again = tasks.submit(r["id"], "Ada Lovelace", base, "guest: ada", sub="guest-ada")   # a second attempt, same player
    assert again["result"]["n"] == 2 and again["result"]["sha256"] == hashlib.sha256(base.encode()).hexdigest()
    seen = json.dumps([out, again, tasks.listing()])
    assert '"key"' not in seen and "suffix" not in seen                         # the player key and the sealed part stay on the server


def test_the_signin_sheet_and_the_noise_toggle_are_on_the_page():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="signinClose"' in page
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "#signin:not([hidden])" in css and "position: fixed" in css
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Show all Qloo matches" in js and "left out: " in js and 'put("ok"' in js and 'put("err"' in js


def test_persona_keeps_the_products_kind_and_shelves_the_noise():
    from knos_wanted import check
    rep = check.demand_check(IDEA, client=FakeQloo())
    assert all(p["on_kind"] for p in rep["persona"]) and len(rep["persona_all"]) >= len(rep["persona"])


def test_release_findings_version_fee_funder_label_and_translations():
    import knos
    from knos_wanted import preorder
    init = agent.mcp(None, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    root = Path(knos.__file__).resolve().parents[2]
    want = (re.search(r'(?m)^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8")).group(1)
            if (root / "src" / "knos").is_dir() and (root / "pyproject.toml").is_file() else knos.version())
    assert init["result"]["serverInfo"]["version"] == want                    # the package's own version, never a hand-written number
    assert init["result"]["serverInfo"]["version"] != "0.3.34"
    # the fee on what the order holds: 48 units at 2 test units each settle 96
    f48 = preorder.fee_line(48, 2)
    assert f48["on_amount"] == 96 and f48["on_this_preorder"] == preorder.fee_line(96, 1)["on_this_preorder"]
    # a funder's money is its own escrow, labelled as funder money; a pre-order stays a pre-order
    assert "funder" in preorder.FUNDER_VIA and "held for this milestone" in preorder.FUNDER_VIA
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "viaLabel(c)" in js and "factorNote(" not in js
    i18n = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert "same devnet escrow" not in i18n
    for key in ("skip:", "factoring_sim:", "factoring_ready:", "via_preorder:", "via_funder:", "via_blink:"):
        assert i18n.count(key) == 7, key                                      # every language
    assert 'data-i18n="skip"' in (STATIC / "index.html").read_text(encoding="utf-8")
