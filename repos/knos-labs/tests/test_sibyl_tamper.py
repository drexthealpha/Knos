"""Tampering caught once is a required check from then on, for that repo and for that agent, kept in Sibyl."""

from __future__ import annotations

import pytest

from knos.proof import claims, engine, history


class _Fake:
    """Stands in for MemoryClient when sibyl_memory_client is not installed."""

    def __init__(self):
        self.rows = {}

    def set_entity(self, category, name, body, status=None):
        self.rows[(category, name)] = {"category": category, "name": name, "status": status, "body": body}
        return self.rows[(category, name)]

    def list_entities(self, category=None, status=None, limit=100):
        return [r for (c, _n), r in self.rows.items() if (category is None or c == category)
                and (status is None or r["status"] == status)][:limit]

    def learn(self):
        raise RuntimeError("free tier")


@pytest.fixture()
def store(tmp_path):
    try:
        from sibyl_memory_client import MemoryClient
        client = MemoryClient.local(str(tmp_path / "sibyl.db"), tenant_id="repo")
    except ImportError:
        client = _Fake()
    return history.SibylStore(client)


def test_learn_tamper_stores_the_tamper_and_scoped_rules(store):
    made = history.learn_tamper(store, "/w/acme/widget", "codex@host", "deleted-tests", "tests/test_x.py removed")
    assert {r["scope"] for r in made} == {"repo", "agent"}
    t = store.all("tamper")
    assert len(t) == 1 and t[0]["pattern"] == "deleted-tests" and "test_x.py" in t[0]["evidence"]
    keyed = {(r["scope"], r.get(r["scope"])) for r in history.required_for(store, "widget", "codex@host")}
    assert keyed == {("repo", "widget"), ("agent", "codex@host")}


def test_required_for_the_repo_or_the_agent_and_no_one_else(store):
    history.learn_tamper(store, "acme/widget", "codex@host", "skip-markers", "@pytest.mark.skip added")
    history.learn_tamper(store, "acme/widget", "codex@host", "skip-markers", "@pytest.mark.skip added")  # idempotent
    assert history.tamper_checks_required(store, "widget", None) == {"tamper:skip-markers"}
    assert history.tamper_checks_required(store, "C:\\src\\other", "codex@host") == {"tamper:skip-markers"}
    assert history.tamper_checks_required(store, "other", "claude@host") == set()
    assert len([r for r in history.rules(store) if r.get("when") == "tamper"]) == 2


def test_tamper_rules_do_not_leak_into_kind_rules(store):
    history.learn_tamper(store, "widget", "codex", "conftest-exit", "conftest.py calls os._exit(0)")
    assert history.required(store, {"done", "tests"}) == set()


def test_engine_needs_the_tamper_check_and_fails_closed(store, tmp_path):
    repo = tmp_path / "widget"
    repo.mkdir()
    history.learn_tamper(store, repo, "codex", "forged-report", "junit.xml written by hand")
    names, learned = engine.needed(claims.read("Done: tests pass"), {}, store, repo)
    assert "tamper:forged-report" in names and "tamper:forged-report" in learned
    names, _ = engine.needed(claims.read("Done: tests pass"), {}, store, tmp_path / "elsewhere", "codex")
    assert "tamper:forged-report" in names
    names, _ = engine.needed(claims.read("Done: tests pass"), {}, store, tmp_path / "elsewhere", "claude")
    assert "tamper:forged-report" not in names
    r = engine.run_check("tamper:forged-report", repo, claims.read("Done"), {}, None, store)
    assert not r.ok and "forged-report" in r.detail
    ok = engine.run_check("tamper:forged-report", repo, claims.read("Done"), {},
                          {"tamper:forged-report": lambda *_: engine.checks.Result("tamper:forged-report", True, "")},
                          store)
    assert ok.ok


def test_null_store_learns_nothing():
    s = history.NullStore()
    history.learn_tamper(s, "widget", "codex", "deleted-tests", "x")
    assert history.tamper_checks_required(s, "widget", "codex") == set()
