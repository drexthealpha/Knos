"""Renaming a claimed file must not launder the claim.

A claim names paths, which leaves an obvious way out: move the file and the path no longer matches.
`git mv risk_guard.py helper.py` and the edit went through. One command defeated the strongest thing knos does, so it
is pinned here. The guard follows a claimed file to its new name when git reports the rename (staged), or when a new
untracked file is byte-identical to a deleted, claimed, tracked one.

The opposite mistake is pinned just as hard. An earlier fix treated every new untracked file as the destination of a
missing claimed one, so writing an unrelated `notes.md` mid-move was refused as "notes.md is risk_guard.py renamed".
That is a false statement about what a file is. A rename has to be evidenced by git or by the bytes, never guessed.

The guard avoids asking git at all when nothing under a claim changed since it was taken (`guard.may_have_moved`), so
the cheap path is pinned too: it must skip git when it can, and must never skip it after a move.

Dropped from the 0.1 version of this file, because the behaviour is gone:
  - test_editing_the_rules_file_is_noticed_without_a_restart: rules in CLAUDE.md no longer block anything, so there
    is no rules cache to invalidate (test_guard.py pins that rules never block).
  - the 0.1 fixture claimed by topic words via Memory.working_on; claims are globs in claims.db now.
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest

from knos import guard
from knos.claims import Claims
from knos.identity import Agent

HOLDER = Agent(host="claude", session="holder01-riskguard")
ASKER = Agent(host="cursor", session="asker001-chat")
BODY = "def check(asset):\n    return True\n"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _commit(repo, message="more"):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _take(repo, globs, agent=HOLDER):
    with Claims(repo) as c:
        assert c.take(agent, "the risk guard", globs)[0]


@pytest.fixture()
def claimed(knos_home, repo):
    """risk_guard.py committed and claimed (by its literal path) by another agent."""
    (repo / "risk_guard.py").write_text(BODY, encoding="utf-8")
    (repo / "unrelated.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "src_unrelated.py").write_text("z = 3\n", encoding="utf-8")
    _commit(repo, "add the risk guard")
    _take(repo, ["risk_guard.py"])
    return repo


@pytest.mark.critical
def test_moving_a_claimed_file_does_not_release_the_claim(claimed) -> None:
    (claimed / "risk_guard.py").rename(claimed / "helper.py")

    verdict = guard.check(claimed, str(claimed / "helper.py"), ASKER)

    assert not verdict.allow, "a rename walked straight past the claim"
    assert verdict.reason.startswith("knos: helper.py (renamed from risk_guard.py) is claimed by claude/holder01")


@pytest.mark.critical
def test_git_mv_does_not_release_it_either(claimed) -> None:
    """The staged shape, which git itself reports as a rename."""
    _git(claimed, "mv", "risk_guard.py", "helper.py")

    verdict = guard.check(claimed, str(claimed / "helper.py"), ASKER)

    assert not verdict.allow
    assert "renamed from risk_guard.py" in verdict.reason


def test_git_mv_then_editing_the_moved_file_is_still_caught(claimed) -> None:
    """git keeps calling it a rename after a small edit; the guard follows git."""
    _git(claimed, "mv", "risk_guard.py", "helper.py")
    (claimed / "helper.py").write_text(BODY + "# tweak\n", encoding="utf-8")
    _git(claimed, "add", "helper.py")

    assert not guard.check(claimed, str(claimed / "helper.py"), ASKER).allow


def test_a_rename_into_another_existing_folder_is_caught(claimed) -> None:
    (claimed / "src" / "risk_guard_v2.py").write_bytes((claimed / "risk_guard.py").read_bytes())
    (claimed / "risk_guard.py").unlink()

    assert not guard.check(claimed, str(claimed / "src" / "risk_guard_v2.py"), ASKER).allow


def test_a_file_moved_out_of_a_claimed_glob_is_still_claimed(knos_home, repo) -> None:
    (repo / "risk").mkdir()
    (repo / "risk" / "guard.py").write_text(BODY, encoding="utf-8")
    _commit(repo)
    _take(repo, ["risk/**"])
    (repo / "risk" / "guard.py").rename(repo / "helper.py")

    verdict = guard.check(repo, str(repo / "helper.py"), ASKER)
    assert not verdict.allow
    assert "renamed from risk/guard.py" in verdict.reason


@pytest.mark.critical
def test_a_rename_into_a_brand_new_folder_is_caught(claimed) -> None:
    (claimed / "newdir").mkdir()
    (claimed / "risk_guard.py").rename(claimed / "newdir" / "helper.py")

    assert not guard.check(claimed, str(claimed / "newdir" / "helper.py"), ASKER).allow


@pytest.mark.critical
def test_a_file_moved_out_of_a_claimed_directory_path_is_still_claimed(knos_home, repo) -> None:
    (repo / "risk").mkdir()
    (repo / "risk" / "guard.py").write_text(BODY, encoding="utf-8")
    (repo / "risk" / "other.py").write_text("x = 1\n", encoding="utf-8")
    _commit(repo)
    _take(repo, ["risk/"])
    (repo / "risk" / "guard.py").rename(repo / "helper.py")

    assert not guard.check(repo, str(repo / "helper.py"), ASKER).allow


# --- what is not a rename ----------------------------------------------------


def test_an_unrelated_new_file_is_not_called_a_rename(claimed) -> None:
    """The false positive that mattered more than the hole."""
    (claimed / "risk_guard.py").rename(claimed / "helper.py")
    (claimed / "notes.md").write_text("hello\n", encoding="utf-8")

    verdict = guard.check(claimed, str(claimed / "notes.md"), ASKER)

    assert verdict.allow, "an unrelated file was refused as a rename of the claimed one: " + verdict.reason


def test_a_new_file_with_different_bytes_is_not_a_rename(claimed) -> None:
    (claimed / "risk_guard.py").unlink()
    (claimed / "helper.py").write_text(BODY.replace("True", "False"), encoding="utf-8")

    assert guard.check(claimed, str(claimed / "helper.py"), ASKER).allow


def test_an_unrelated_tracked_file_is_still_editable(claimed) -> None:
    (claimed / "risk_guard.py").rename(claimed / "helper.py")

    verdict = guard.check(claimed, str(claimed / "unrelated.py"), ASKER)

    assert verdict.allow, verdict.reason


def test_the_holder_may_rename_its_own_work(claimed) -> None:
    """The claim protects the work from others, never from its owner."""
    (claimed / "risk_guard.py").rename(claimed / "helper.py")
    assert guard.check(claimed, str(claimed / "helper.py"), HOLDER).allow

    _git(claimed, "add", "-A")  # and the staged shape
    assert guard.check(claimed, str(claimed / "helper.py"), HOLDER).allow


def test_a_rename_of_something_nobody_claimed_is_fine(claimed) -> None:
    (claimed / "unrelated.py").rename(claimed / "moved.py")
    assert guard.check(claimed, str(claimed / "moved.py"), ASKER).allow

    _git(claimed, "add", "-A")
    assert guard.check(claimed, str(claimed / "moved.py"), ASKER).allow


def test_an_advisory_claim_does_not_follow_renames(knos_home, repo) -> None:
    (repo / "risk_guard.py").write_text(BODY, encoding="utf-8")
    _commit(repo)
    with Claims(repo) as c:
        took, _, mine = c.take(HOLDER, "making the risk checks stricter", None)
    assert took and mine.advisory
    (repo / "risk_guard.py").rename(repo / "helper.py")

    assert guard.check(repo, str(repo / "helper.py"), ASKER).allow


# --- the cheap pre-check: skip git when nothing moved, never after a move --------


@pytest.mark.critical
def test_a_rename_after_an_earlier_check_is_still_caught(claimed) -> None:
    """The dangerous ordering: check something, rename the claimed file, edit it. Nothing the guard saw before the
    move may answer for after it."""
    assert guard.check(claimed, str(claimed / "src_unrelated.py"), ASKER).allow

    (claimed / "risk_guard.py").rename(claimed / "helper.py")

    verdict = guard.check(claimed, str(claimed / "helper.py"), ASKER)
    assert not verdict.allow, "the guard answered as if the claimed file had not moved"


def test_a_rename_out_of_a_glob_after_an_earlier_check_is_still_caught(knos_home, repo) -> None:
    (repo / "risk").mkdir()
    (repo / "risk" / "guard.py").write_text(BODY, encoding="utf-8")
    _commit(repo)
    old = time.time() - 3600
    os.utime(repo / "risk", (old, old))
    _take(repo, ["risk/**"])
    assert guard.check(repo, str(repo / "unrelated.py"), ASKER).allow

    (repo / "risk" / "guard.py").rename(repo / "helper.py")

    assert not guard.check(repo, str(repo / "helper.py"), ASKER).allow


def _count_git(monkeypatch) -> list:
    calls = []
    real = subprocess.run

    def counted(args, *rest, **kw):
        if list(args[:1]) == ["git"] or str(args[0]).endswith("git"):
            calls.append(list(args))
        return real(args, *rest, **kw)

    monkeypatch.setattr(guard.subprocess, "run", counted)
    return calls


def test_nothing_moved_means_git_is_not_asked(claimed, monkeypatch) -> None:
    """Deterministic version of 'it is fast', without timing anything."""
    guard.check(claimed, str(claimed / "unrelated.py"), ASKER)  # warm paths' own caches
    calls = _count_git(monkeypatch)

    assert guard.check(claimed, str(claimed / "unrelated.py"), ASKER).allow
    assert not guard.check(claimed, str(claimed / "risk_guard.py"), ASKER).allow
    assert not calls, f"the guard shelled out to git although no claimed file moved: {calls}"


def test_nothing_moved_under_a_glob_means_git_is_not_asked(knos_home, repo, monkeypatch) -> None:
    (repo / "risk").mkdir()
    (repo / "risk" / "guard.py").write_text(BODY, encoding="utf-8")
    _commit(repo)
    old = time.time() - 3600
    os.utime(repo / "risk", (old, old))
    _take(repo, ["risk/**"])
    guard.check(repo, str(repo / "unrelated.py"), ASKER)
    calls = _count_git(monkeypatch)

    assert guard.check(repo, str(repo / "unrelated.py"), ASKER).allow
    assert not calls, calls


def test_after_a_move_git_is_asked(claimed, monkeypatch) -> None:
    (claimed / "risk_guard.py").rename(claimed / "helper.py")
    guard.check(claimed, str(claimed / "unrelated.py"), ASKER)
    calls = _count_git(monkeypatch)

    assert not guard.check(claimed, str(claimed / "helper.py"), ASKER).allow
    assert any("status" in c for c in calls), calls
