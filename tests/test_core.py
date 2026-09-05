"""The embeddable core: claim, withhold, connection-bound hold, no MCP.

This is the surface a tool embeds instead of running knos as a server, so
what it promises has to hold without a server anywhere in the picture. These
tests import nothing from `knos.mcp` and start no process.
"""

from __future__ import annotations

import pytest

from knos.core import Claims, holds


@pytest.mark.critical
def test_a_claim_is_taken_once_and_the_loser_is_told_who_has_it(repo) -> None:
    """The compare-and-swap, reached through the library rather than MCP."""
    with Claims(repo=repo, who="agent-one", session="one") as first:
        taken, holder = first.take("the risk guard")
        assert taken and holder is None

    with Claims(repo=repo, who="agent-two", session="two") as second:
        taken, holder = second.take("the risk guard")
        assert not taken
        assert (holder or {}).get("who") == "agent-one"


@pytest.mark.critical
def test_the_hold_is_bound_to_the_session_not_the_name(repo) -> None:
    """An agent asserting the holder's name is still not the holder.

    This is the property that makes the refusal worth anything: a client
    tells knos its own name and can say whatever it likes.
    """
    with Claims(repo=repo, who="agent-one", session="one") as first:
        assert first.take("the parser")[0]

    imposter = Claims(repo=repo, who="agent-one", session="somewhere-else")
    with imposter as pretending:
        work = pretending.live()[0]
        assert not pretending.mine(work)
        assert pretending.withheld("parsing")

    with Claims(repo=repo, who="agent-one", session="one") as same:
        assert same.mine(same.live()[0])
        assert same.withheld("parsing") == ""


def test_withheld_names_the_holder_and_offers_the_override(repo) -> None:
    with Claims(repo=repo, who="agent-one", session="one") as first:
        first.take("the risk guard")

    with Claims(repo=repo, who="agent-two", session="two") as second:
        said = second.withheld("guards")
        assert said.startswith("Withheld.")
        assert "agent-one" in said
        assert "override" in said


def test_a_free_subject_is_not_withheld(repo) -> None:
    with Claims(repo=repo, who="agent-one", session="one") as first:
        first.take("the risk guard")
        assert first.holder("the invoice importer") is None
        assert first.withheld("the invoice importer") == ""


def test_releasing_frees_the_work_for_everybody(repo) -> None:
    with Claims(repo=repo, who="agent-one", session="one") as first:
        first.take("the risk guard")
        first.release()
        assert first.live() == []

    with Claims(repo=repo, who="agent-two", session="two") as second:
        assert second.take("the risk guard")[0]


def test_subject_matching_is_shared_stems(repo) -> None:
    """Re-exported so a caller can match without opening a store at all."""
    assert holds("the risk guard", "guards")
    assert holds("parser", "parsing")
    assert not holds("the risk guard", "the invoice importer")


def test_the_core_needs_no_server_and_no_cli(repo) -> None:
    """Importing the embeddable surface must not drag in MCP or the CLI."""
    import sys

    for module in ("knos.mcp", "knos.cli"):
        sys.modules.pop(module, None)
    import importlib

    importlib.reload(importlib.import_module("knos.core"))
    assert "knos.mcp" not in sys.modules
    assert "knos.cli" not in sys.modules
