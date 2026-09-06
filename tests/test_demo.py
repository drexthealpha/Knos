"""`knos demo` is the playground, so it has to survive being run.

There is no hosted surface and there will not be - nothing on the read path
touches a network, and that is a test rather than a promise. So the local path
is what a judge reaches for, which makes it load-bearing in the presentation
sense and worth pinning like anything else.

Two properties matter. It has to touch nothing outside its own temporary
directory, and every beat it claims has to actually happen - a demo that
prints "the edit is refused" without refusing an edit is a transcript, and a
transcript is the thing this whole repository is arguing against.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class Recorder:
    """Stands in for the CLI's console, keeping what was printed."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, text: str = "") -> None:
        self.lines.append(str(text))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    """The pauses are for a human watching; a test should not wait."""
    from knos import demo

    monkeypatch.setattr(demo, "PAUSE", 0)


def test_the_demo_runs_and_ends_with_the_product_broken() -> None:
    from knos import demo

    out = Recorder()
    assert demo.run(out) == 0
    said = out.text

    for beat in (
        "Two agents",
        "It is refused",
        "the edit is refused",
        "money moves",
        "A decision is reversed",
        "leaves the machine",
        "delete the memory",
    ):
        assert beat.lower() in said.lower(), beat

    # The ending is the argument. If these three lines are not in it, the
    # demo showed a product working rather than a product depending.
    assert "the withhold        gone" in said
    assert "the edit            allowed" in said
    assert "the paid answer     buys again" in said


def test_every_refusal_it_prints_actually_happened() -> None:
    """The beats are real calls, so their live values must appear."""
    from knos import demo

    out = Recorder()
    demo.run(out)
    said = out.text

    assert "Withheld." in said, "the withhold was described, not performed"
    assert "allow = False" in said, "the guard did not actually refuse"
    assert "verdict = buy" in said, "the gate did not actually price it"
    assert "verdict = have" in said, "the second ask was not actually free"
    assert "held = True" in said, "the reversal did not actually hold anything"


def test_it_leaves_nothing_behind_and_touches_no_real_repo(tmp_path, monkeypatch) -> None:
    """It must never write into the repo a person happens to be standing in."""
    from knos import demo

    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    home_before = os.environ.get("KNOS_HOME")

    demo.run(Recorder())

    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert os.environ.get("KNOS_HOME") == home_before, "KNOS_HOME was left changed"


def test_the_documented_command_works() -> None:
    """`knos demo` is what the README tells a judge to run."""
    said = subprocess.run(
        [sys.executable, "-c", "from knos.cli import app; app()", "demo"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=600,
    )
    assert said.returncode == 0, said.stderr[-800:]
    assert "There is no product" in said.stdout
