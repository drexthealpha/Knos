"""H5: seven small holes, one test each.

1. the Hermes write guard refuses ./.github/x and ./.knos/x (the path is normalised, never stripped as characters)
2. OFAC screening fails closed: a list that cannot be had, or a copy older than 7 days, screens nobody, and the payout
   is then held (tests/test_flow_orders.py holds the payout side)
3. knos_game_submit (it runs code) is neither listed nor served by the tokenless HTTP MCP server
4. an unreadable ~/.knos/relay-key.json raises instead of being overwritten with a new key
5. the real token that was refused "token too long" on k0615 pull request 8 (its 31 claims, signed here by a test key)
   is taken by the relay and verified on chain
6. "2016-2018" is a span of years, not a phone number
7. a community garden for military families is not refused
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from knos import chain as knos_chain
from knos import hermes_plugin, mcp_http, ready, refuse, screen
from knos.mcp import GAME_TOOLS, Server
from knos.settle import oidc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "wanted"))


def test_1_hermes_guard_refuses_dot_slash_paths():
    for path in ("./.github/workflows/ci.yml", "./.github/x", "src/../.github/x", "././.github/x"):
        assert (hermes_plugin.refused_write(path) or "").startswith("workflow_edited"), path
    for path in ("./.knos/x", "./.knos/gate.yml", "a/../.knos/seal"):
        assert (hermes_plugin.refused_write(path) or "").startswith("sealed_tests_changed"), path
    assert hermes_plugin.refused_write("./src/github/x.py") is None        # a folder named github is not .github


def test_2_ofac_screening_fails_closed(tmp_path):
    cache, day = tmp_path / "sdn.json", 86_400
    cache.write_text(json.dumps({"fetched": 1_000 * day, "addresses": ["BADbadBADbad1111111111111111111111111111111"]}), encoding="utf-8")
    down = lambda url: (_ for _ in ()).throw(OSError("Network is unreachable"))  # noqa: E731
    ok, why = screen.check("Fine1111111111111111111111111111111111111111", now=(1_000 + 6) * day, get=down, cache=cache)
    assert ok is True and "6 days old" in why                                  # a copy up to a week old still screens
    ok, why = screen.check("Fine1111111111111111111111111111111111111111", now=(1_000 + 8) * day, get=down, cache=cache)
    assert ok is None and why.startswith("not screened") and "8 days old (over 7)" in why
    ok, why = screen.check("Fine1111111111111111111111111111111111111111", now=1, get=down, cache=tmp_path / "none.json")
    assert ok is None and why.startswith("not screened")
    from knos import flow
    import inspect
    src = inspect.getsource(flow._cleared)
    assert "elif clear is None:\n                        c.listed" in src            # held like a listed address, never paid


def test_3_tokenless_http_mcp_hides_the_game_submit(monkeypatch, tmp_path):
    monkeypatch.delenv("KNOS_MCP_HTTP_TOKEN", raising=False)
    monkeypatch.setenv("KNOS_GAME_DIR", str(tmp_path))
    assert "knos_game_submit" in {t["name"] for t in GAME_TOOLS}
    srv = Server()
    assert "knos_game_submit" in {t["name"] for t in srv._list({})["tools"]}     # a server of its own lists it
    httpd = mcp_http.make("127.0.0.1:0", server=srv)
    try:
        names = {t["name"] for t in srv._list({})["tools"]}
        assert "knos_game_submit" not in names and "knos_verify" not in names
        assert "knos_game_submit" not in srv._tools and "knos_game_board" in names
    finally:
        httpd.server_close()


def test_4_an_unreadable_relay_key_is_never_overwritten(monkeypatch, tmp_path):
    monkeypatch.delenv("KNOS_RELAY_KEY", raising=False)
    monkeypatch.delenv("KNOS_MEMBER_KEY", raising=False)
    monkeypatch.setenv("KNOS_HOME", str(tmp_path))
    f = tmp_path / "relay-key.json"
    f.write_text("[1, 2, 3", encoding="utf-8")                                    # there, but not a keypair
    with pytest.raises(RuntimeError, match="cannot be read as a keypair"):
        knos_chain.key()
    assert f.read_text(encoding="utf-8") == "[1, 2, 3"
    f.unlink()
    made = knos_chain.key()                                                        # no file: made once, then read back
    assert knos_chain.key().pubkey() == made.pubkey()


def test_5_the_token_refused_as_too_long_on_k0615_8_is_taken_and_verified():
    claims = json.loads((ROOT / "tests" / "fixtures" / "k0615_8_token_claims.json").read_text(encoding="utf-8"))["claims"]
    assert len(claims) == 31 and len(claims["aud"]) == 220
    from _settle import modulus, sign_jwt, signing_key
    key = signing_key()
    jwt = sign_jwt(key, claims)
    assert 2_000 < len(jwt) <= oidc.MAX_JWT
    ixs = oidc.write_ixs(knos_chain.Keypair().pubkey(), b"\x01" * 32, jwt)
    assert len(ixs) == math.ceil(len(jwt) / oidc.CHUNK)                          # written in chunks, nothing refused for size
    pytest.importorskip("solders.litesvm")
    from _settle import Chain
    c = Chain()
    assert c.register(oidc.GITHUB, modulus(key)), c.err
    tok = c.verify(jwt, oidc.GITHUB, modulus(key), tag="k0615")
    assert tok is not None, c.err
    assert oidc.read_token(c.data(tok)).claims() == claims


def test_6_a_span_of_years_is_not_a_phone_number():
    from knos_wanted import privacy
    for text in ("sales records from 2016-2018 in Lagos", "a study of 1990–2001 harvests", "2019 to 2023 prices"):
        assert privacy.problems(text) == [], text
    for text in ("call +234 803 123 4567", "card 4111 1111 1111 1111", "0803 123 4567"):
        assert privacy.problems(text), text                                     # still refused


def test_7_a_garden_for_military_families_is_not_refused():
    text = "a community garden for military families"
    assert refuse.refused(text) == []
    brief = {"title": text, "milestones": [{"key": "m1", "name": "raised beds built", "target": "12 raised beds planted by the families",
                                            "verifier": {"kind": "human", "check": "photo of the 12 planted beds"}, "deadline_days": 60}]}
    assert ready.check(brief)["label"] != "Refused"
    assert refuse.refused("a drone for the military")[0]["category"] == "military_first"       # the rule itself stays
