"""Renaming a claimed file must not launder the claim.

The guard matches a path's *name* against the claim's words, which is right
for finding the work but leaves an obvious way out: move the file and the name
no longer matches. `git mv risk_guard.py helper.py` and the edit went through.
One command defeated the strongest thing knos does, so it is pinned here.

The opposite mistake is pinned just as hard. An earlier version of the fix
treated every new untracked file as the destination of a missing claimed one,
so writing an unrelated `notes.md` while a claimed file was mid-move was
refused with the sentence "notes.md is risk_guard.py renamed". That is not
over-refusal, it is a false statement about what a file is, and a guard that
misdescribes what it is looking at is worse than one that lets an edit through.
So a rename has to be evidenced by the bytes, not guessed from the timing.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

import pytest

from knos import guard
from knos.memory import Memory

TOPIC_ = "the risk guard"
BODY = "def check(asset):\n    return True\n"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture()
def claimed(knos_home, repo):
    """A repo with risk_guard.py committed and claimed by another agent."""
    (repo / "risk_guard.py").write_text(BODY, encoding="utf-8")
    (repo / "unrelated.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add the risk guard")

    with Memory(repo) as mem:
        mem.working_on(TOPIC_, "Claude Code", datetime.now(timezone.utc).isoformat())
    return repo


@pytest.mark.critical
def test_moving_a_claimed_file_does_not_release_the_claim(claimed) -> None:
    (claimed / "risk_guard.py").rename(claimed / "helper.py")

    verdict = guard.check(claimed, str(claimed / "helper.py"), "Cursor")

    assert not verdict.allow, "a rename walked straight past the claim"
    assert "renamed" in verdict.reason
    assert "risk_guard.py" in verdict.reason, "it should name the file this was"


@pytest.mark.critical
def test_git_mv_does_not_release_it_either(claimed) -> None:
    """The staged shape, which git itself reports as a rename."""
    _git(claimed, "mv", "risk_guard.py", "helper.py")

    verdict = guard.check(claimed, str(claimed / "helper.py"), "Cursor")

    assert not verdict.allow
    assert "risk_guard.py" in verdict.reason


def test_an_unrelated_new_file_is_not_called_a_rename(claimed) -> None:
    """The false-positive that mattered more than the hole."""
    (claimed / "risk_guard.py").rename(claimed / "helper.py")
    (claimed / "notes.md").write_text("hello\n", encoding="utf-8")

    verdict = guard.check(claimed, str(claimed / "notes.md"), "Cursor")

    assert verdict.allow, (
        "writing an unrelated file was refused as a rename of the claimed one: "
        + verdict.reason
    )


def test_an_unrelated_tracked_file_is_still_editable(claimed) -> None:
    (claimed / "risk_guard.py").rename(claimed / "helper.py")

    verdict = guard.check(claimed, str(claimed / "unrelated.py"), "Cursor")

    assert verdict.allow, verdict.reason


def test_the_holder_may_rename_its_own_work(claimed) -> None:
    """The claim protects the work from others, never from its owner."""
    (claimed / "risk_guard.py").rename(claimed / "helper.py")

    verdict = guard.check(claimed, str(claimed / "helper.py"), "Claude Code")

    assert verdict.allow, verdict.reason


def test_a_rename_of_something_nobody_claimed_is_fine(knos_home, repo) -> None:
    (repo / "unrelated.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unrelated")
    (repo / "unrelated.py").rename(repo / "moved.py")

    verdict = guard.check(repo, str(repo / "moved.py"), "Cursor")

    assert verdict.allow, verdict.reason
