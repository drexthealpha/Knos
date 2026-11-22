"""The six idea tools of `knos mcp`: listed ONLY when the operator opts in (KNOS_MCP_TOOLS=ideas), so the default
tool list stays as tests/test_mcp.py pins it; read-only; a source's own words only inside `untrusted`. Offline."""
from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from knos import ideas, mcp
from knos.ideas import K, tools, wanted as W

FIXTURE = Path(__file__).parent / "fixtures" / "ideas" / "recorded-fixture.json"
NAMES = [t["name"] for t in tools.MCP_TOOLS]
TRIAL, PAPER = "NCT04718792", "arxiv:1606.00335"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for k in ideas.ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no live API call in tests")))
    monkeypatch.setenv(ideas.FIXTURES_ENV, str(FIXTURE))


@pytest.fixture()
def opted_in(monkeypatch):
    monkeypatch.setenv(tools.OPT_IN_ENV, "verify," + tools.OPT_IN_WORD)


def listed() -> list[str]:
    return [t["name"] for t in mcp.Server()._list({})[K.tools]]


def call(name: str, args: dict) -> dict:
    return mcp.Server()._call({K.name: name, "arguments": args})


def test_the_default_list_is_unchanged_and_the_idea_tools_are_opt_in(monkeypatch):
    assert len(NAMES) == 6 and not set(NAMES) & {t["name"] for t in mcp.TOOLS}
    assert listed() == [t["name"] for t in mcp.TOOLS]
    monkeypatch.setenv(tools.OPT_IN_ENV, tools.OPT_IN_WORD)
    assert listed() == [t["name"] for t in mcp.TOOLS] + NAMES


def test_without_the_opt_in_an_idea_tool_is_unknown():
    with pytest.raises(mcp.Refused):
        call(NAMES[0], {"ref": PAPER})


def test_the_idea_tools_are_read_only_and_keep_source_words_in_untrusted(opted_in):
    got = {t["name"]: t for t in mcp.Server()._list({})[K.tools]}
    for name in NAMES:
        assert got[name]["annotations"]["readOnlyHint"] is True
        assert "sends nothing" in got[name]["description"].lower()
    r = call(NAMES[0], {"ref": PAPER})
    assert r[K.isError] is False
    sc = r[K.structuredContent]
    assert K.statement not in sc[K.claim]
    assert sc[K.untrusted][K.statement].startswith("Dynamic electrical behavior")
    w = call(NAMES[4], {"ref": TRIAL, "units": 10, "price": 4})[K.structuredContent]
    assert [s[K.oracle] for s in w[K.stages]] == [W.ORACLE.trial_registered, W.ORACLE.results_posted, W.ORACLE.referee_pass]
    assert w["sends"] == "nothing"
    assert w["demand"][K.mode] == W.MONEY
    assert "knos idea commit" in w["lock_with"]
    ch = call(NAMES[5], {"ref": TRIAL, K.oracle: W.ORACLE.results_posted})[K.structuredContent]
    assert ch[K.met] is False
    assert call(NAMES[0], {"ref": "myspace:1"})[K.isError] is True
    who = call(NAMES[3], {"who": "orcid:0000-0002-1825-0097"})[K.structuredContent]
    assert who[K.untrusted][K.name] == "Josiah Carberry"
    assert K.name not in who
