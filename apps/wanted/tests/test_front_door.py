"""The front door's list (knos_wanted.front, GET /api/front), the app's home view and one-tap actions, the passkey-only
sign-in, the two-tap receivable sale and the passkey routes of projects. SYNTHETIC fixtures; no network, no chain
(the chain flows are tests/test_passkey_projects_app.py and tests/test_passkey_money_app.py, in LiteSVM)."""
import hashlib
import re
import time

import pytest
from test_round9 import STATIC, app, call  # noqa: F401 - the fixture

from knos_wanted import agent, front, valley

LIVE = "LIVE Qloo data (Qloo REST API, read for this report)"


def _report(st, h, verdict="OPEN", label=LIVE, idea="A fitness watch with a sweat glucose sensor"):
    rep = {"hash": h, "kind": "knos-demand-check", "idea": idea, "label": label,
           "decision": {"verdict": verdict, "target_units": 110, "reserve_units": 48, "plan": {"unit_price": 2, "where": ["Austin"]}},
           "research": {"title": "Fully integrated wearable sensor arrays", "venue": "Nature", "year": 2016}}
    st.keep(rep)
    return rep


def _job(rep, seed=None):
    j = {"id": rep["hash"][:16], "ref": None, "idea": rep["idea"], "status": "done", "steps": [], "started": time.time(), "report": rep["hash"]}
    if seed:
        j["seed"] = seed
    agent.JOBS[j["id"]] = j
    return j


@pytest.fixture(autouse=True)
def fresh():
    agent.JOBS.clear()
    front._seeded.clear()
    yield
    agent.JOBS.clear()
    front._seeded.clear()


def test_the_list_holds_only_open_decisions_on_live_qloo_and_the_seeds_come_first(app):  # noqa: F811
    base, st = app
    seed = _report(st, "a" * 64)
    front._seeded["sweat-glucose-watch"] = {"report": seed["hash"], "state": "open",
                                            "project": front._project_for(seed["hash"], seed["idea"], "hardware_prototype")}
    _job(_report(st, "b" * 64, idea="A cozy game"))
    _job(_report(st, "c" * 64, verdict="REFUSE"))
    _job(_report(st, "d" * 64, label="MOCK (synthetic, not a real API response)"))
    b = front.board(st)
    assert [p["slug"] for p in b["products"]] == ["sweat-glucose-watch", "b" * 16]           # REFUSE and MOCK are never listed
    p = b["products"][0]
    assert p["project"] and p["first_milestone"] and p["maker"] is False and p["backed_units"] == 0 and p["reserve_units"] == 48
    assert p["paper"] == "Nature, 2016" and p["actions"] == {"back": "#back=sweat-glucose-watch", "fund": "#fund=sweat-glucose-watch",
                                                             "contribute": "#contribute=sweat-glucose-watch"}
    assert valley.project(p["project"])["owner"] == front.SEED_OWNER["sub"]
    # the same project is found again, never opened twice
    assert front._project_for(seed["hash"], seed["idea"], "hardware_prototype") == p["project"]
    # one product by slug, by its report, by its first 16 hex; a seed still crossing says so
    assert front.resolve(st, "sweat-glucose-watch")["report"] == "a" * 64 == front.resolve(st, "a" * 64)["report"]
    assert front.resolve(st, "b" * 16)["report"] == "b" * 64
    front._seeded["air-water-bottle"] = {"state": "crossing"}
    got = front.resolve(st, "air-water-bottle")
    assert got["pending"] and got["state"] == "crossing" and front.board(st)["crossing_now"] == ["air-water-bottle"]
    assert front.resolve(st, "nothing-like-it") is None


def test_api_front_answers_github_pages_with_cors(app):  # noqa: F811
    base, st = app
    _job(_report(st, "e" * 64))
    s, b, h = call(base, "/api/front")
    assert s == 200 and h.get("Access-Control-Allow-Origin") == "*" and b["products"][0]["report"] == "e" * 64
    assert "devnet test units" in b["money"]
    s, one, h = call(base, "/api/front?slug=" + "e" * 16)
    assert s == 200 and one["report"] == "e" * 64 and h.get("Access-Control-Allow-Origin") == "*"
    s, _, _ = call(base, "/api/front?slug=nope-nope")
    assert s == 404


def test_seeds_cross_on_live_qloo_and_open_a_project_only_when_open(app, monkeypatch):  # noqa: F811
    base, st = app
    reps = {"sweat-glucose-watch": "OPEN", "air-water-bottle": "REFUSE"}

    def start(state, ref=None, idea=None, place=None, product=None, wait=False):
        slug = next(s["slug"] for s in front.SEEDS if s.get("ref") == ref and s.get("idea") == idea)
        rep = _report(st, hashlib.sha256(slug.encode()).hexdigest(), verdict=reps.get(slug, "OPEN"), idea=product or idea)
        return _job(rep)
    monkeypatch.setattr(agent, "start", start)
    front.ensure_seeded(st, tries=1, wait_s=0)
    got = front.seeded()
    assert got["sweat-glucose-watch"]["state"] == "open" and got["sweat-glucose-watch"]["project"]
    assert got["air-water-bottle"]["state"] == "not open" and "project" not in got["air-water-bottle"]
    assert [p["slug"] for p in front.board(st)["products"]][:3] == ["sweat-glucose-watch", "ai-recipe-planner", "glow-hydration-bottle"]
    monkeypatch.setenv("KNOS_WANTED_SEED", "0")
    assert not front.seeds_on()


def test_the_app_opens_on_the_products_with_one_tap_actions():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '|| "home"' in page and 'id="v-home"' in page and 'id="homeList"' in page
    assert re.search(r'<section id="v-home" class="view"', page) and 'id="v-research" class="view" hidden' in page
    assert 'const VIEWS = ["home",' in js and "#(back|fund|contribute)=" in js and 'location.replace("#buy=" + p.report)' in js
    for key in ("back_btn", "fundm_btn", "contrib_btn"):
        assert f't("{key}")' in js
    # the cards keep their height while the list loads (no layout shift on a phone)
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".hp-card { margin: 0; min-height:" in css and page.count('class="card hp-card sk"') == 3


def test_sign_in_is_a_passkey_for_everyone_and_shows_only_what_works():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    sheet = page[page.index('<section id="signin"'):page.index("</section>", page.index('<section id="signin"'))]
    assert 'id="pkNew"' in sheet and 'id="pkUse"' in sheet and 'id="pkName"' in sheet
    assert " disabled" not in sheet and "Not available" not in sheet and "soon" not in sheet       # no dead buttons
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "accounts.google.com" not in js and "/api/auth/guest" not in js and "/api/auth/email\"" not in js


def test_the_app_keeps_the_valley_flow_and_never_says_assign():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "loadLend" not in js and "lendList" not in page and "/api/factor" not in js     # no lending against pre-orders
    for f in ("index.html", "app.js", "i18n.js", "valley.js", "verify.html"):
        assert not re.search(r"Assign", (STATIC / f).read_text(encoding="utf-8")), f
    import knos_wanted.wallets as w
    assert "Assign" not in (w.__doc__ or "")


def t_of(text, key):
    return f't("{key}")' in text


def test_projects_are_funded_committed_and_claimed_with_the_passkey(app):  # noqa: F811
    base, st = app
    vjs = (STATIC / "valley.js").read_text(encoding="utf-8")
    assert vjs.count("passkey: true") >= 4 and "await walletAccount()" not in vjs.split("// ---- teams")[0]
    s, b, _ = call(base, "/api/project/fund", {"passkey": True, "project": "x" * 16, "milestone": "m", "units": 5})
    assert s == 400 and "passkey" in b["error"]                                            # signed in first, no wallet extension
    pw = (STATIC / "passkey_wallet.js").read_text(encoding="utf-8")
    assert 'step.kind === "project_fund"' in pw and 'step.kind === "amc"' in pw and "data[0] !== 4" in pw
