"""test_outside_counter (unit half): outside crossings and commitments are counted from the store and nothing else;
the operator's key, automated clients and Knos or test guest sessions are left out; the counter equals its rows."""
import urllib.request

from test_product_routes import app, call  # noqa: F401 - the fixture

from knos_wanted import outside, own_wallets

BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def post(base, path, body, headers):
    import json
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def test_outside_counter(app, monkeypatch, tmp_path):  # noqa: F811
    from knos_wanted import escrow
    base, _ = app
    monkeypatch.setattr(escrow, "_state_dir", lambda: tmp_path)
    monkeypatch.setenv("KNOS_ADMIN_KEY", "k" * 40)
    assert call(base, "/api/outside")[1]["rows"] == 0                                    # nothing seeded
    post(base, "/api/cross", {"idea": "a plant-based burger chain"}, {"User-Agent": BROWSER})          # a person: counted
    post(base, "/api/cross", {"idea": "a plant-based burger chain"}, {"User-Agent": "python-urllib/3.12"})  # a script: not
    post(base, "/api/cross", {"idea": "a plant-based burger chain"}, {"User-Agent": "Mozilla/5.0 HeadlessChrome/130"})  # CI browser: not
    post(base, "/api/cross", {"idea": "a plant-based burger chain"}, {"User-Agent": BROWSER, "X-Knos-Admin": "k" * 40})  # operator: not
    tok = call(base, "/api/auth/guest", {"label": "demand_live --lock proof run"})[1]["token"]
    post(base, "/api/cross", {"idea": "a plant-based burger chain"}, {"User-Agent": BROWSER, "Authorization": "Bearer " + tok})  # test guest
    t = call(base, "/api/outside")[1]
    rows = call(base, "/api/outside/rows")[1]["rows"]
    assert t["crossings"] == 1 and t["commitments"] == 0 and t["rows"] == len(rows) == 1 and rows[0]["kind"] == "crossing"
    assert set(rows[0]) == {"kind", "at", "ref", "via"}                                   # no personal data kept
    outside.CTX.headers = None
    assert outside.note("commitment", "O" * 44, "milestone funding") is False             # no request: nothing counted
    outside.begin({"User-Agent": BROWSER})
    assert outside.note("commitment", "O" * 44, "milestone funding") is True
    assert outside.note("commitment", "O" * 44, "milestone funding") is False             # one row per order
    assert call(base, "/api/outside")[1]["commitments"] == 1
    own = sorted(own_wallets.WALLETS)[0]
    assert outside.note("commitment", "P" * 44, "milestone funding", own) is False        # Knos's own wallet: not counted
    from knos_wanted import valley
    valley._save("orders", "Q" * 44, {"order": "Q" * 44, "funder": own, "status": "locked"})
    valley._save("outside", "day-2026-10-26", {"day": "2026-10-26", "rows": [
        {"kind": "commitment", "at": "2026-10-26T12:10:30Z", "ref": "Q" * 44, "via": "milestone funding"}]})
    assert call(base, "/api/outside")[1]["commitments"] == 1                              # an old own row is left out on read


def test_own_wallets_match_the_repository_list():
    import json
    from pathlib import Path
    repo = json.loads((Path(__file__).resolve().parents[3] / "scripts/own_github_ids.json").read_text(encoding="utf-8"))
    assert set(repo["wallets"]) == own_wallets.WALLETS
