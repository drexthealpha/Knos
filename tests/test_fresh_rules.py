"""A citation knos has not just checked is not a citation.

This was reproduced before it was fixed, on a throwaway repo: a rule was
written into CLAUDE.md, knos read it, the rule was deleted and committed, and
knos went on answering with it - citing CLAUDE.md:3, a line that by then said
"## Style". A person who followed that receipt found the file disagreeing with
the answer.

That is the failure this whole product exists to stop, happening inside its
own answers. The instruction files are the ones agents rewrite most often, so
a rule read out of them is provisional against the file: served only while the
file still says it, and cited at the line the file says it now.

The middle case is the one worth keeping tests on. A rule that has simply
moved down the file is still true, and refusing it would be as wrong as
serving it with the old line number.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knos import answer, rules, worth
from knos.memory import WITHDRAWN, Memory

RULE = (
    "## Testing\n"
    "Never use a bare except in this repository. Catch the specific error."
)
STYLE = "## Style\nTwo spaces of indentation everywhere."


def _repo(tmp_path: Path, body: str) -> Path:
    repo = tmp_path / "probe"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "rules"],
        cwd=repo,
        check=True,
    )
    return repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _repo(tmp_path, f"# Working here\n\n{RULE}\n\n{STYLE}\n")


def _read(repo: Path) -> None:
    with Memory(repo) as mem:
        answer.point(repo, mem)


def _ask(repo: Path, question: str = "can I use a bare except"):
    with Memory(repo) as mem:
        return answer.ask(repo, mem, question)


@pytest.mark.critical
def test_a_rule_the_file_still_carries_is_answered_with(repo: Path) -> None:
    _read(repo)
    found = _ask(repo)

    assert found, "the rule is in the file and should be the answer"
    assert "bare except" in found[0].text
    assert found[0].where == "CLAUDE.md:3"


@pytest.mark.critical
def test_a_rule_that_moved_is_cited_where_it_is_now(repo: Path) -> None:
    """The case a bool would get wrong.

    The rule is still true, so refusing it would be wrong; it is no longer on
    line 3, so citing line 3 would also be wrong. A receipt that points at the
    wrong line is a false receipt even when the quote above it is right.
    """
    _read(repo)
    (repo / "CLAUDE.md").write_text(
        f"# Working here\n\n## Notes\nSomething added above.\n\n{RULE}\n\n{STYLE}\n",
        encoding="utf-8",
    )

    found = _ask(repo)

    assert found, "moving a rule down the file does not repeal it"
    assert found[0].where == "CLAUDE.md:6", "the citation must follow the rule"


@pytest.mark.critical
def test_a_rule_deleted_from_the_file_is_not_answered_with(repo: Path) -> None:
    """The bug, exactly as it was reproduced."""
    _read(repo)
    (repo / "CLAUDE.md").write_text(f"# Working here\n\n{STYLE}\n", encoding="utf-8")

    assert not _ask(repo), (
        "the file stopped saying this and knos kept answering with it, citing "
        "a line that by then said something else"
    )


def test_the_rules_question_does_not_serve_a_deleted_rule_either(repo: Path) -> None:
    """There are two paths that serve a rule, and both had the bug.

    Search finds it by word; "what are the rules here?" fetches the rules by
    name because the question shares no word with the rule. Fixing one and not
    the other would leave the fault reachable by the more obvious question.
    """
    _read(repo)
    (repo / "CLAUDE.md").write_text(f"# Working here\n\n{STYLE}\n", encoding="utf-8")

    said = " ".join(p.text for p in _ask(repo, "what are the rules here"))

    assert "bare except" not in said
    assert "indentation" in said, "the rules that remain are still the answer"


def test_deleting_the_whole_instruction_file_repeals_its_rules(repo: Path) -> None:
    _read(repo)
    (repo / "CLAUDE.md").unlink()

    assert not _ask(repo)


def test_an_edit_that_does_not_change_the_file_size_is_still_seen(repo: Path) -> None:
    """The cache must not be the thing that serves a withdrawn rule.

    Blocks are cached against the file's mtime and size, so the dangerous
    shape is an edit that changes neither much: same length, different words.
    """
    _read(repo)
    _ask(repo)  # warm the cache with the rule present
    same_size = RULE.replace("Never use a bare except", "Always use a bare xcept")
    (repo / "CLAUDE.md").write_text(
        f"# Working here\n\n{same_size}\n\n{STYLE}\n", encoding="utf-8"
    )

    assert not _ask(repo), "the cache served a rule the file had already changed"


def test_a_citation_with_no_file_in_it_is_left_alone() -> None:
    """Not every source is a file, and this check has no business on those.

    A session or a commit is cited by id, and what it said then is what it
    said - there is nothing on disk to re-read and nothing to withdraw.
    """
    assert rules.still_says(Path("."), "anything", "knos memory") == "knos memory"


def test_a_withdrawn_rule_is_recorded_once_however_often_it_is_asked_for(
    repo: Path,
) -> None:
    """The ledger is a canonical record per rule, not a counter.

    A repo whose CLAUDE.md dropped a rule months ago must not grow the store
    every time somebody asks a question near it.
    """
    _read(repo)
    (repo / "CLAUDE.md").write_text(f"# Working here\n\n{STYLE}\n", encoding="utf-8")

    for _ in range(3):
        _ask(repo)

    with Memory(repo) as mem:
        rows = mem.things(WITHDRAWN, limit=50)

    assert len(rows) == 1
    assert rows[0]["name"] == "CLAUDE.md:3", "the record is keyed by the citation"


def test_worth_counts_a_withdrawn_rule(repo: Path) -> None:
    """It is the one thing in that ledger that happens with a single agent.

    Every other line there is a collision between two of them, so on a repo
    with one agent `knos worth` said knos had done nothing at all.
    """
    _read(repo)
    (repo / "CLAUDE.md").write_text(f"# Working here\n\n{STYLE}\n", encoding="utf-8")
    _ask(repo)

    with Memory(repo) as mem:
        got = worth.tally(mem)

    assert got["withdrawn"] == 1
    assert "deleted after knos read it" in worth.sentence(got)


def test_the_journal_still_has_the_rule_that_was_withdrawn(repo: Path) -> None:
    """Withdrawn is not forgotten.

    The journal records what was learned and when, and that a rule was in the
    file on the day it was read stays true afterwards. What changes is that
    knos stops handing it out as current.
    """
    _read(repo)
    (repo / "CLAUDE.md").write_text(f"# Working here\n\n{STYLE}\n", encoding="utf-8")
    _ask(repo)

    with Memory(repo) as mem:
        kept = [e for e in mem.written_rules() if "bare except" in str(e.get("text"))]

    assert kept, "the record of what the file said should survive the withdrawal"
