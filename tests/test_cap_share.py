"""One source must not be able to take the whole store before another is read.

Measured on the knos repository itself, which is the one this product was
built in: `knos point` filled Sibyl's 5 MB free tier after 1,075 of its 1,360
session turns and stopped, having read **zero** of its 62 commits. Every
question about *why* something was done - which is what a commit message
answers - had nothing behind it, on the repo the product was written in.

The cause was the reading order. Sessions were read before commits and a
transcript is unbounded: it is thousands of turns and grows every day, while
commits are capped at 500. First come, first served is the wrong rule when one
of the queues never ends.

A fact costs about 5.5 KB on disk once Sibyl has indexed it - the store keeps
the row, a full-text copy and a second shadow index - so five megabytes is
roughly a thousand facts. The cap is not theoretical on real repositories, and
what fills it decides what knos can answer at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knos import answer, sessions
from knos.memory import Memory


class _Turn:
    """Enough of a turn for `point` to write it, and fat enough to fill a store."""

    def __init__(self, n: int) -> None:
        self.text = f"turn {n} " + ("chatter about the parser " * 40)
        self.client = "Claude Code"
        self.session = f"aaaa{n:04d}"
        self.when = "2026-08-20T10:00:00Z"
        self.where = f"Claude Code session aaaa{n:04d} 2026-08-20"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "busy"
    repo.mkdir()
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, check=False
    )
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    for n in range(12):
        (repo / f"f{n}.py").write_text(f"x = {n}\n", encoding="utf-8")
        run("add", "-A")
        run("commit", "-qm", f"decide: the settlement path, part {n}")
    return repo


def test_commits_are_read_even_when_the_sessions_would_fill_the_store(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reproduction, in miniature.

    Twelve commits and a transcript far larger than the store. Read in the old
    order the transcript took all of it and the commits were never reached.
    """
    monkeypatch.setattr(sessions, "read_all", lambda _repo=None: [_Turn(n) for n in range(4000)])

    with Memory(repo) as mem:
        counts = answer.point(repo, mem, index_code=False)

    assert counts["full"], "this fixture is meant to fill the store"
    assert counts["commits"] == 12, (
        f"the store filled on session turns and kept {counts['commits']} of 12 "
        "commits; a repo with a busy transcript would know nothing about why "
        "anything was done"
    )
    assert counts["sessions"] > 0, "sessions must still get the rest of the store"


def test_the_commits_do_not_take_the_whole_store_either(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The share cuts both ways, or it is just a different source starving.

    A repo with five hundred commits and a short transcript must not spend the
    whole store on commits: the fix for one queue eating everything is not to
    let the other one do it.
    """
    monkeypatch.setattr(sessions, "read_all", lambda _repo=None: [_Turn(n) for n in range(60)])

    with Memory(repo) as mem:
        counts = answer.point(repo, mem, index_code=False)

    assert counts["sessions"] == 60, (
        "a short transcript should be read whole once the commits have taken "
        "their share"
    )


def test_a_repo_with_no_transcript_still_reads_its_commits(repo: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "read_all", lambda _repo=None: [])

    with Memory(repo) as mem:
        counts = answer.point(repo, mem, index_code=False)

    assert counts["commits"] == 12
    assert not counts["full"]


def test_the_share_is_a_named_constant_rather_than_a_number_in_the_loop() -> None:
    """So the trade is arguable rather than buried.

    A third is a judgement call, not a measurement, and somebody disagreeing
    with it should be able to find it and say so.
    """
    said = (Path(answer.__file__)).read_text(encoding="utf-8")

    assert "COMMIT_SHARE" in said
    assert 0 < answer.COMMIT_SHARE < 1
    assert "FREE_TIER_MB" in said
