"""Asking about work held by a reversed decision has to say so.

`decide.supersede` marks everything reasoned from a changed decision as
suspect, and two of the three paths that matter already acted on it: the guard
refuses the edit, the gate refuses the purchase. The third is the one an agent
uses most - it asks - and that path said nothing.

So an agent that tried to change the file was stopped, and an agent that only
read about it was handed the withdrawn wording and reasoned from it. Held work
is exactly the work nobody thinks to revisit, which is how one changed
decision becomes a pile of work built on it.

Deliberately a notice and not a refusal. A claim is somebody else's work and
knos declines to be the source; this is not withheld from anyone, it is stale,
and an agent that cannot see the old wording cannot work out what changed.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone

import pytest

from knos import decide, mcp
from knos.memory import TOPIC, Memory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def reversed_decision(knos_home, repo, monkeypatch):
    """A decision changed, and one thing that was reasoned from it."""
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, "the risk guard",
                       {"note": "refuses unknown assets", "when": _now()[:10]})
        mem.note_thing(TOPIC, "the risk guard tests",
                       {"note": "assume unknown assets are refused",
                        "when": _now()[:10]})
        decide.supersede(mem, "the risk guard",
                         "unknown assets pass with a warning", "you", _now())
    monkeypatch.chdir(repo)
    return repo


@pytest.mark.critical
def test_asking_about_held_work_says_it_is_held(reversed_decision) -> None:
    said = mcp.about("the risk guard tests")

    assert said.startswith("Held back."), said[:120]
    assert "was changed by you" in said
    assert "refuses unknown assets" in said, "it has to say what it used to be"
    assert "knos reconsider" in said, "a notice without the way out is half a notice"


@pytest.mark.critical
def test_searching_for_held_work_says_it_too(reversed_decision) -> None:
    """The busier of the two tools, and the one an agent reaches for first."""
    said = mcp.search("the risk guard tests")

    assert "Held back." in said, said[:200]


def test_work_nobody_reversed_is_answered_plainly(reversed_decision) -> None:
    """The notice must not become furniture on every answer."""
    said = mcp.about("something nobody has touched")

    assert "Held back." not in said


def test_the_answer_is_still_there_underneath(reversed_decision) -> None:
    """A notice, not a refusal.

    Unlike a claim, this is not somebody else's to give. An agent that cannot
    see the old wording cannot work out what changed, and the point is to make
    it look rather than to make it blind.
    """
    said = mcp.about("the risk guard tests")

    assert "Held back." in said
    assert len(said) > 200, "the notice replaced the answer instead of leading it"


def test_it_stops_saying_so_once_somebody_has_looked(reversed_decision) -> None:
    with Memory(reversed_decision) as mem:
        decide.reconsider(mem, "the risk guard tests", "you", _now())

    assert "Held back." not in mcp.about("the risk guard tests")


@pytest.mark.critical
def test_it_dies_with_the_store(reversed_decision) -> None:
    from knos import paths

    assert "Held back." in mcp.about("the risk guard tests")

    paths.store_for(reversed_decision).unlink()

    assert "Held back." not in mcp.about("the risk guard tests")
