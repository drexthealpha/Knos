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
    (repo / "src_unrelated.py").write_text("z = 3\n", encoding="utf-8")
    # Committed, because `rules.files` reads only what git tracks - a
    # vendored CLAUDE.md written for somebody else's maintainers is not a
    # rule here.
    (repo / "CLAUDE.md").write_text("# House rules\n\n- Keep it small.\n",
                                    encoding="utf-8")
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


# --- the guard is on the hot path, so it caches; caches can be bypasses -----

@pytest.mark.critical
def test_a_rename_after_an_earlier_check_is_still_caught(claimed) -> None:
    """The dangerous ordering, which is the ordering an attacker uses.

    The guard caches its git lookups, because it runs before every tool call
    and two subprocesses per call is a third of a second an agent waits for
    every time. A cache keyed on a clock would be wrong here: one second is
    long enough to rename a claimed file and edit it while the guard is still
    answering from before the move. So it is keyed on the directory the path
    lives in, which a move updates - and this asserts that.
    """
    first = guard.check(claimed, str(claimed / "src_unrelated.py"), "Cursor")
    assert first.allow  # warms the cache

    (claimed / "risk_guard.py").rename(claimed / "helper.py")

    verdict = guard.check(claimed, str(claimed / "helper.py"), "Cursor")
    assert not verdict.allow, (
        "the guard answered from a cache taken before the rename, which is "
        "exactly the bypass the rename check exists to close"
    )


def test_the_second_check_does_not_ask_git_all_over_again(claimed, monkeypatch):
    """Deterministic version of 'it got faster', without timing anything."""
    import subprocess as sp

    calls = []
    real = sp.run

    def counted(args, *rest, **kw):
        if args and str(args[0]).endswith("git") or args[:1] == ["git"]:
            calls.append(list(args))
        return real(args, *rest, **kw)

    guard.check(claimed, str(claimed / "risk_guard.py"), "Cursor")

    monkeypatch.setattr(guard.subprocess, "run", counted)
    guard.check(claimed, str(claimed / "risk_guard.py"), "Cursor")

    assert not calls, (
        "the guard shelled out to git again for an answer nothing had "
        f"invalidated: {calls}"
    )


def test_editing_the_rules_file_is_noticed_without_a_restart(claimed) -> None:
    """The other half of caching: it has to stop being true when it stops.

    The rules file is committed in the fixture, because `rules.files` reads
    only what git tracks - the first version of this test wrote an untracked
    CLAUDE.md and then blamed the cache for correctly ignoring it.
    """
    target = claimed / "src_unrelated.py"
    assert guard.check(claimed, str(target), "Cursor").allow

    (claimed / "CLAUDE.md").write_text(
        "# House rules\n\n- Never edit `src_unrelated.py`.\n", encoding="utf-8"
    )

    verdict = guard.check(claimed, str(target), "Cursor")
    assert not verdict.allow, (
        "a rule added to CLAUDE.md was not seen, so the rules cache is "
        "holding an answer past the point it stopped being right"
    )
    assert "CLAUDE.md" in verdict.reason
