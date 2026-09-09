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
        # The only beat that needs one agent and one file, which is why it is
        # first: a viewer who runs a single agent recognises it immediately.
        "stops being quoted",
        "Two agents",
        "It is refused",
        "the edit is refused",
        "money moves",
        "A decision is reversed",
        "leaves the machine",
        "never seen this repo",
        "who finishes",
        # The one thing no competitor claims, and it was missing from the
        # demo entirely: a private path returns nothing to an agent AND no
        # notice that anything was withheld.
        "cannot tell is there",
        "delete the memory",
    ):
        assert beat.lower() in said.lower(), beat

    # The ending is the argument. If these three lines are not in it, the
    # demo showed a product working rather than a product depending.
    assert "the withhold        gone" in said
    assert "the edit            allowed" in said
    assert "the paid answer     buys again" in said


def test_the_private_beat_shows_both_answers_not_just_the_empty_one() -> None:
    """An empty result on its own proves nothing - a broken tool gives that too.

    The beat has to show the owner getting the path and an agent getting
    nothing, from the same store in the same moment, or a viewer cannot tell
    privacy from failure.
    """
    from knos import demo

    out = Recorder()
    demo.run(out)
    said = out.text
    beat = said[said.index("cannot tell is there"):said.index("delete the memory")]

    assert "secrets/keys.py" in beat, "the owner's answer is not shown"
    assert "0 results" in beat, "the agent's empty answer is not shown"
    assert "notice" in beat, (
        "the beat must say there is no hidden-results notice, which is the "
        "part that separates this from every tool that filters after the fact"
    )


def test_the_first_beat_shows_the_rule_before_and_after_it_is_deleted() -> None:
    """Both halves, or it is a screenshot of an absence.

    A viewer has to see knos quote the rule with its line, then see the same
    question answered differently once the file stops saying it. Showing only
    the second half proves nothing: an empty answer is what a broken tool
    gives too.
    """
    from knos import demo

    out = Recorder()
    demo.run(out)
    said = out.text
    first = said[: said.index("2. Two agents")]

    assert "CLAUDE.md:" in first, "the rule is quoted without a checkable citation"
    assert "bare except" in first, "the rule itself is never shown"
    assert "delete that rule" in first, "the file is never seen to change"
    assert "Nothing about that" in first, "the withdrawal is not shown"


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
    assert "recalled:" in said, "the cold process did not actually recall"
    # The count is `record.STRONG`, not the literal it used to be: the beat
    # needs a settled record so the numbers it prints are the ones every page
    # describes. What is being asserted is that the record was computed.
    from knos import record

    assert f"closed {record.STRONG} of {record.STRONG}" in said, (
        "the record was described, not computed"
    )
    assert "knos at 2h" in said, "the demo stopped showing the rewind"
    assert "held the settlement job" in said, (
        "the rewind printed no reconstruction, so it showed nothing happening"
    )


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


def test_it_runs_in_the_time_the_documents_claim() -> None:
    """The pages say about fifty seconds. A page that says a number means it.

    Measured at 47.2s with the pauses in, after the privacy beat was added;
    41.9s before it, 34s with nine beats, and every page said ninety back
    when it was 34 - which is how this test came to exist.

    Measured without the pauses, because those are a constant a human reads
    at and this is about the work. If the demo ever takes longer than a judge
    will sit through, this is where it shows up rather than on camera.
    """
    import time

    from knos import demo

    out = Recorder()
    start = time.perf_counter()
    demo.run(out)          # PAUSE is zeroed by the autouse fixture
    took = time.perf_counter() - start

    assert took < 20, (
        f"the demo's own work took {took:.0f}s. With the pauses back that is "
        "well past the fifty seconds every page promises, and past what "
        "anybody watching a video will sit through."
    )


def test_the_race_is_two_real_processes_and_one_is_refused() -> None:
    """The 40-point claim, on camera, across an operating-system boundary.

    `scripts/collide.py` proves this sixteen ways and writes the number down,
    but a number in a JSON file is not a beat anybody watches. Two processes
    start at the same instant, both reach for one piece of work, and exactly
    one gets it - which is the whole product in four lines.

    Pinned because it is easy to let this decay into a printed sentence. The
    pids have to differ and the loser has to be refused *by name*, or it is a
    transcript again.
    """
    import re

    from knos import demo

    out = Recorder()
    demo.run(out)
    said = out.text

    assert "both claim" in said, "the race beat is gone"
    took = [ln for ln in said.splitlines() if "TOOK IT" in ln]
    lost = [ln for ln in said.splitlines() if "refused, held by" in ln]

    assert len(took) == 1, f"exactly one process must win: {took}"
    assert len(lost) == 1, f"exactly one must be refused: {lost}"
    assert "held by Claude Code" in lost[0] or "held by Cursor" in lost[0], lost

    pids = re.findall(r"pid (\d+) (?:Claude Code|Cursor)", said)
    assert len(set(pids)) == 2, f"both racers ran in the same process: {pids}"
