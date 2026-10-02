"""The Python SDK and the LangGraph example: agents beyond code claim generic units and share Sibyl memory."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from knos.sdk import Knos

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_generic_units_are_claimed_and_refused(knos_home, tmp_path):
    a, b = Knos("a", tmp_path), Knos("b", tmp_path)
    assert a.claim("task:invoice-4411")
    assert a.claim("task:invoice-4411")  # its own again: fine
    assert not b.claim("task:invoice-4411") and b.holder == "sdk/a"
    assert b.claim("market:ETH")
    assert a.holder_of("market:ETH") == "sdk/b"
    assert a.release("task:invoice-4411") == 1
    assert b.claim("task:invoice-4411")


def test_memory_is_shared_through_sibyl(knos_home, tmp_path):
    a, b = Knos("a", tmp_path), Knos("b", tmp_path)
    assert a.remember("invoice 4411 was paid twice", about="invoice-4411")
    hits = b.recall("invoice 4411")
    assert any("paid twice" in h["text"] for h in hits), hits


def test_the_langgraph_example_runs_with_scripted_models(knos_home, tmp_path):
    pytest.importorskip("langgraph.graph")
    pytest.importorskip("sibyl_memory_langgraph")
    sys.path.insert(0, str(EXAMPLES))
    try:
        sys.modules.pop("langgraph_team", None)
        import langgraph_team
        got = langgraph_team.run(tmp_path)
    finally:
        sys.path.remove(str(EXAMPLES))
        sys.modules.pop("langgraph_team", None)
    assert got["alice"] == "task:invoice-4411"
    assert got["bob"] == "task:invoice-4412" and got["bob_refused"] == ["task:invoice-4411"]
    assert "alice checked invoice-4411" in got["bob_read_alices_finding"]
    assert "carol read 2 finding(s)" in got["carol_finding"]
    assert "alice checked invoice-4411" in got["carol_finding"]
    assert "bob checked invoice-4412" in got["carol_finding"]
