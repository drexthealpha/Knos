"""The bot never answers with silence, a stack trace, or a machine payload.

These three were real, and all three were invisible to the rest of the
suite because the bot is TypeScript and everything else here is Python.
Rather than stand up a Node test runner for one file, the properties are
asserted against the source: they are structural - a branch exists, a
fallback does not return the raw body - and a source assertion catches the
regression that matters, which is somebody deleting the branch.

The weakness is honest: this proves the code is written, not that it runs.
What proves it runs is `npm run bot -- /status`, which is the console path
the README points at, and which serves the same handler Telegram does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BOT = Path(__file__).resolve().parent.parent / "agent" / "bot.ts"


@pytest.fixture(scope="module")
def source() -> str:
    if not BOT.exists():
        pytest.skip("the agent is not checked out")
    return BOT.read_text(encoding="utf-8")


def test_an_unknown_command_is_answered_rather_than_ignored(source: str) -> None:
    """Silence is the one reply nobody can tell apart from a dead bot.

    `handle` used to fall off the end when nothing matched, so `/hepl`, or
    a person typing hello, got nothing back at all.
    """
    assert "I do not know" in source
    assert "I only answer commands." in source


def test_a_failed_subprocess_is_not_returned_as_the_answer(source: str) -> None:
    """stdout and stderr were one string, so a traceback read as an answer."""
    assert "function broke(" in source
    assert "function apology(" in source
    # The exit code has to be consulted, or there is nothing to branch on.
    assert 'run.on("close", (code)' in source


def test_no_path_prints_the_seller_body_verbatim(source: str) -> None:
    """Every branch of `english` ends in prose, never in the raw payload."""
    assert "raw.slice(0, 800)" not in source, "the flatten fallback dumps JSON again"
    assert "taught to read" in source


def test_a_cut_message_says_that_it_was_cut(source: str) -> None:
    """Telegram's 4096 limit is a limit; a sentence stopping mid-word is a bug."""
    assert "[cut here" in source


def test_a_receipt_is_a_link_a_person_can_follow(source: str) -> None:
    """The stored note carries the explorer URL, not the settlement header."""
    assert "https://basescan.org/tx/${said.tx}" in source
    assert "Receipt: ${said.paid" not in source
