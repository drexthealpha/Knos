"""`knos demo` is the playground, so it has to survive being run.

Two properties matter. It has to touch nothing outside its own temporary directories, and every beat it claims has
to actually happen: a demo that prints "the edit is refused" without refusing an edit is a transcript.

The 0.2.0 sequence, each beat a real call:

  1. shared memory: a note written as one agent is recalled for another;
  2. Claude Code claims risk_guard.py;
  3. Cursor's edit to it is refused by `guard.check` (allowed = False) while the holder's is allowed;
  4. two processes race for settle.py and exactly one takes it;
  5. a cold process, which has never seen the repo, recalls it;
  6. the claim is released and Cursor's edit is allowed.

Rewritten for 0.2.0. Dropped, because the beats are gone from the product: the rule quoted then deleted from
CLAUDE.md ("Nothing about that"), the withhold ("Withheld.", "the withhold gone"), the paid answer and the money gate
("verdict = buy/have", "money moves"), the reversed decision holding work ("held = True"), the beat about private paths
("cannot tell is there"), the track record ("closed N of N", "who finishes"), the rewind (`knos at 2h`), and the
ending that deletes the memory ("There is no product").
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from knos import demo


class Recorder:
    """Stands in for the CLI's console, keeping what was printed (markup and all)."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, text: str = "", **_kw) -> None:
        self.lines.append(str(text))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _plain(text: str) -> str:
    return re.sub(r"\[/?[a-z ]*\]", "", text)


@pytest.fixture(scope="module")
def shown() -> str:
    """One run shared by the read-only assertions: the demo spawns three processes and reads a repo, which is slow on
    a spinning disk. Runs in its own throwaway home like every test here."""
    mp = pytest.MonkeyPatch()
    home = Path(tempfile.mkdtemp(prefix="knos-demo-test-home-"))
    try:
        for key in ("HOME", "USERPROFILE"):
            mp.setenv(key, str(home))
        mp.setenv("APPDATA", str(home / "AppData" / "Roaming"))
        mp.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        mp.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
        mp.setenv("CODEX_HOME", str(home / ".codex"))
        mp.setenv("KNOS_HOME", str(home / ".knos"))
        out = Recorder()
        rc = demo.run(out, pause=0)
        assert rc == 0, out.text[-2000:]
        return _plain(out.text)
    finally:
        mp.undo()
        import shutil

        shutil.rmtree(home, ignore_errors=True)


def _beat(said: str, n: int) -> str:
    start = said.index(f"\n{n}. ")
    end = said.find(f"\n{n + 1}. ", start + 1)
    return said[start:end if end != -1 else len(said)]


def test_the_demo_shows_every_beat(shown: str) -> None:
    for n, title in enumerate((
        "Memory every agent shares.",
        "Claude Code claims the file it is about to change.",
        "Cursor tries to edit it. The edit is refused",
        "Two processes reach for the same file in the same instant.",
        "A process that has never seen this repo recalls it.",
        "Claude Code finishes. Cursor may edit.",
    ), start=1):
        assert f"{n}. {title}" in shown, title
    assert "Try it on your own repo:  knos init" in shown


def test_the_memory_beat_recalls_what_another_agent_wrote(shown: str) -> None:
    first = _beat(shown, 1)
    assert "the risk guard refuses unknown assets" in first, "Cursor was shown nothing Claude Code wrote"
    assert "(nothing)" not in first


def test_the_claim_is_real(shown: str) -> None:
    second = _beat(shown, 2)
    assert re.search(r"claimed risk_guard\.py for 30 min", second), second


def test_every_refusal_it_prints_actually_happened(shown: str) -> None:
    """The beats are real calls, so their live values must appear."""
    third = _beat(shown, 3)
    assert "allowed = False" in third, "the guard did not actually refuse"
    assert "knos: risk_guard.py is claimed by claude/s-claude" in third, "the refusal did not name the holder"
    assert "allowed = True  (its own claim never blocks it)" in third, "the holder was refused its own file"

    last = _beat(shown, 6)
    assert "allowed = True" in last, "releasing the claim did not let Cursor edit"


def test_the_race_is_two_real_processes_and_exactly_one_wins(shown: str) -> None:
    """Two processes start at the same instant and both reach for settle.py; one BEGIN IMMEDIATE decides. The loser
    has to be refused by the winner's name, or it is a transcript again."""
    lines = _beat(shown, 4).splitlines()
    took = [ln for ln in lines if "| took it" in ln]
    lost = [ln for ln in lines if "| refused, held by" in ln]

    assert len(took) == 1, f"exactly one process must win: {lines}"
    assert len(lost) == 1, f"exactly one must be refused: {lines}"
    winner = took[0].split("|")[0].strip()
    loser = lost[0].split("|")[0].strip()
    assert {winner, loser} == {"codex", "opencode"}
    assert f"held by {winner}/" in lost[0], lost[0]


def test_the_cold_process_is_another_process_and_recalls(shown: str) -> None:
    fifth = _beat(shown, 5)
    got = re.search(r"pid (\d+) \| recalled: (.+)", fifth)
    assert got, fifth
    assert int(got.group(1)) != os.getpid(), "the cold read ran in this process"
    assert "risk guard" in got.group(2), got.group(2)


def test_it_leaves_nothing_behind_and_touches_no_real_repo(tmp_path, monkeypatch, knos_home) -> None:
    """It must never write into the repo a person happens to be standing in, nor into their ~/.knos."""
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    here = tmp_path / "standing-here"
    here.mkdir()
    (here / "mine.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(here)
    home_before = sorted(p.name for p in knos_home.rglob("*"))

    assert demo.run(Recorder(), pause=0) == 0

    assert sorted(p.name for p in here.iterdir()) == ["mine.txt"]
    assert list(scratch.iterdir()) == [], "the demo left its temporary folders behind"
    assert os.environ.get("KNOS_HOME") == str(knos_home), "KNOS_HOME was left changed"
    assert sorted(p.name for p in knos_home.rglob("*")) == home_before, "the demo wrote into the person's ~/.knos"


def test_a_failure_is_one_line_and_exit_one(monkeypatch, knos_home) -> None:
    def broken(root):
        raise RuntimeError("no git here")

    monkeypatch.setattr(demo, "_sandbox", broken)
    out = Recorder()

    assert demo.run(out, pause=0) == 1
    assert out.lines[-1] == "knos demo stopped: RuntimeError: no git here"
    assert os.environ.get("KNOS_HOME") == str(knos_home)


def test_knos_demo_through_the_cli(monkeypatch, capsys) -> None:
    from knos.cli import main

    seen = {}

    def fake_run(out, pause):
        seen["pause"] = pause
        return 0

    monkeypatch.setattr(demo, "run", fake_run)
    assert main(["demo", "--fast"]) == 0
    assert seen["pause"] == 0.0
    assert main(["demo"]) == 0
    assert seen["pause"] == demo.PAUSE


def test_the_documented_command_works() -> None:
    """`knos demo` is what the README and the help screen tell a person to run."""
    said = subprocess.run(
        [sys.executable, "-m", "knos", "demo", "--fast"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=600,
    )
    assert said.returncode == 0, said.stdout[-800:] + said.stderr[-800:]
    assert "allowed = False" in said.stdout
    assert "Try it on your own repo:  knos init" in said.stdout


def test_it_runs_in_a_time_a_person_will_sit_through(knos_home) -> None:
    """`knos demo` should take about 20 seconds. Measured without the pauses (a constant a human reads at, about eight
    seconds of `demo.PAUSE`), because this is about the work: a git repo, a read, three processes. On a spinning disk
    with other suites running the work alone measured up to 21s, so the bound is a regression guard, not the promise."""
    start = time.perf_counter()
    assert demo.run(Recorder(), pause=0) == 0
    took = time.perf_counter() - start

    assert took < 60, f"the demo's own work took {took:.0f}s; a person will not sit through more than a minute"
