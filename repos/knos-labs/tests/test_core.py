"""The embeddable core: claim files, check a path, release, with no MCP and no CLI in the picture."""

from __future__ import annotations

import pytest

from knos.core import Claims


@pytest.mark.critical
def test_a_claim_is_taken_once_and_the_loser_is_told_who_has_it(repo) -> None:
    with Claims(repo=repo, who="agent-one", session="one") as first:
        taken, holder = first.take("the auth module", paths=["src/auth.py"])
        assert taken and holder is None
    with Claims(repo=repo, who="agent-two", session="two") as second:
        taken, holder = second.take("login work", paths=["src/**"])
        assert not taken
        assert holder["who"].startswith("agent-one")
        assert holder["globs"] == ["src/auth.py"]


@pytest.mark.critical
def test_the_claim_belongs_to_the_session_not_the_name(repo) -> None:
    """A second session of the same host is a different agent: it is refused, the holder is not."""
    with Claims(repo=repo, who="claude", session="one") as first:
        assert first.take("auth", paths=["src/auth.py"])[0]
    with Claims(repo=repo, who="claude", session="somewhere-else") as other:
        assert other.holder("src/auth.py") is not None
        assert not other.mine(other.live()[0])
    with Claims(repo=repo, who="claude", session="one") as same:
        assert same.holder("src/auth.py") is None
        assert same.mine(same.live()[0])


def test_a_description_with_no_file_is_advisory_and_blocks_nothing(repo) -> None:
    with Claims(repo=repo, who="a", session="1") as first:
        took, _ = first.take("the general vibe of things")
        assert took
        assert first.live()[0]["advisory"] is True
    with Claims(repo=repo, who="b", session="2") as second:
        assert second.holder("src/auth.py") is None
        assert second.take("auth", paths=["src/auth.py"])[0]


def test_a_named_file_resolves_without_paths(repo) -> None:
    with Claims(repo=repo, who="a", session="1") as first:
        first.take("fix the bug in src/auth.py")
        assert first.live()[0]["globs"] == ["src/auth.py"]


def test_release_frees_only_your_own(repo) -> None:
    with Claims(repo=repo, who="a", session="1") as first:
        first.take("auth", paths=["src/auth.py"])
    with Claims(repo=repo, who="b", session="2") as second:
        assert second.release() == []
        assert len(second.live()) == 1
    with Claims(repo=repo, who="a", session="1") as first:
        assert first.release() == ["auth"]
        assert first.live() == []


def test_the_core_needs_no_server_and_no_cli(repo) -> None:
    import importlib
    import sys

    for module in ("knos.mcp", "knos.cli"):
        sys.modules.pop(module, None)
    importlib.reload(importlib.import_module("knos.core"))
    assert "knos.mcp" not in sys.modules
    assert "knos.cli" not in sys.modules
