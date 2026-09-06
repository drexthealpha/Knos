"""Reversing a decision, and everything that rested on it.

A claim is about who is moving right now. A decision is about what was
settled, and it is the more dangerous of the two because it goes stale in
silence. These tests pin the consequence: when a decision is reversed, the
work reasoned from it is held - the edit is refused, the purchase is refused,
and it stays that way until somebody says they have looked.

The asymmetry is the point. Reversing costs one command. Reconsidering costs
one command. Carrying on without looking is the only expensive path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from knos import decide, gate, guard, paths
from knos.memory import TOPIC, Memory

GUARD = "the risk guard"
TESTS = "the risk guard tests"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _two_decisions(repo) -> None:
    """One decision, and a second thing on the same subject reasoned from it."""
    now = _now()
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, GUARD, {"note": "refuses unknown assets", "when": now[:10]})
        mem.note_thing(TOPIC, TESTS, {"note": "assume unknown are refused", "when": now[:10]})


@pytest.mark.critical
def test_reversing_a_decision_taints_what_rested_on_it(knos_home, repo) -> None:
    """The blast radius. A decision rarely stands alone."""
    _two_decisions(repo)
    with Memory(repo) as mem:
        hit = decide.supersede(mem, GUARD, "unknown assets pass with a warning", "you", _now())

    assert hit["superseded"] == [GUARD]
    assert TESTS in hit["suspect"], "the thing on the same subject was not held"


@pytest.mark.critical
def test_a_reversed_decision_refuses_the_edit(knos_home, repo) -> None:
    """Not a warning on the way past. The edit does not happen."""
    _two_decisions(repo)
    target = repo / "risk_guard.py"
    target.write_text("def check(a):\n    return True\n", encoding="utf-8")

    assert guard.check(repo, str(target), "Cursor").allow is True

    with Memory(repo) as mem:
        decide.supersede(mem, GUARD, "unknown assets pass with a warning", "you", _now())

    verdict = guard.check(repo, str(target), "Cursor")
    assert verdict.allow is False
    assert "was changed by" in verdict.reason
    assert "knos reconsider" in verdict.reason, "a refusal must say how to clear it"


def test_a_reversed_decision_refuses_to_spend(knos_home, repo) -> None:
    """The same held-back state reaches the money."""
    _two_decisions(repo)
    with Memory(repo) as mem:
        decide.supersede(mem, GUARD, "unknown assets pass with a warning", "you", _now())

    said = gate.decide(repo, TESTS, TESTS)
    assert said["verdict"] == "suspect"
    assert "was changed by" in said["answer"]


def test_reconsidering_lets_the_work_continue(knos_home, repo) -> None:
    _two_decisions(repo)
    target = repo / "risk_guard.py"
    target.write_text("x = 1\n", encoding="utf-8")

    with Memory(repo) as mem:
        decide.supersede(mem, GUARD, "unknown assets pass with a warning", "you", _now())
    assert guard.check(repo, str(target), "Cursor").allow is False

    with Memory(repo) as mem:
        assert decide.reconsider(mem, TESTS, "you", _now()) is True

    assert guard.check(repo, str(target), "Cursor").allow is True


def test_the_old_wording_is_archived_not_deleted(knos_home, repo) -> None:
    """"Why did we do it that way" has to survive the answer changing."""
    _two_decisions(repo)
    with Memory(repo) as mem:
        decide.supersede(mem, GUARD, "unknown assets pass with a warning", "you", _now())

    import sqlite3

    conn = sqlite3.connect(paths.store_for(repo))
    kept = conn.execute("select count(*) from archived_entities").fetchone()[0]
    conn.close()
    assert kept >= 1, "the superseded decision was dropped rather than archived"


def test_the_new_wording_replaces_the_old_one_under_the_same_name(knos_home, repo) -> None:
    _two_decisions(repo)
    with Memory(repo) as mem:
        decide.supersede(mem, GUARD, "unknown assets pass with a warning", "you", _now())
    with Memory(repo) as mem:
        now = mem.thing(TOPIC, GUARD)
    assert "pass with a warning" in str((now or {}).get("body", {}).get("note", ""))


def test_an_unrelated_decision_is_not_held(knos_home, repo) -> None:
    """The blast radius has to have an edge, or every reversal freezes the repo."""
    now = _now()
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, GUARD, {"note": "refuses unknown assets", "when": now[:10]})
        mem.note_thing(TOPIC, "the invoice importer", {"note": "batches by day", "when": now[:10]})
        hit = decide.supersede(mem, GUARD, "passes with a warning", "you", now)

    assert "the invoice importer" not in hit["suspect"]
    with Memory(repo) as mem:
        assert decide.is_suspect(mem, "the invoice importer") is None


def test_deleting_the_store_ends_the_hold(knos_home, repo) -> None:
    """Load-bearing, for this too."""
    _two_decisions(repo)
    target = repo / "risk_guard.py"
    target.write_text("x = 1\n", encoding="utf-8")
    with Memory(repo) as mem:
        decide.supersede(mem, GUARD, "unknown assets pass with a warning", "you", _now())
    assert guard.check(repo, str(target), "Cursor").allow is False

    paths.store_for(repo).unlink()

    assert guard.check(repo, str(target), "Cursor").allow is True
    with Memory(repo) as mem:
        assert decide.suspects(mem) == []
