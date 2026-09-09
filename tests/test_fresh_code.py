"""Code structure is the second source whose receipt is a line somebody is editing.

The rules had this fault and so did this: `knos ask` prints a file and a line
for a symbol, and that line comes out of a tags file written when the repo was
last read. Reproduced before it was fixed - a function at `pay.py:1`, five
lines added above it, and knos still saying `pay.py:1`, which by then was a
comment.

Sessions and commits are deliberately not treated this way and have their own
test below. A commit said what it said and its hash does not move; re-checking
it would be theatre. The two sources that need checking are the two that cite
a mutable line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knos import answer, code
from knos.memory import Memory

BEFORE = "def settle_trade(x):\n    return x\n\n\ndef other(y):\n    return y\n"
MOVED = "# one\n# two\n# three\n\n\n" + BEFORE


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "probe"
    repo.mkdir()
    (repo / "pay.py").write_text(BEFORE, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        cwd=repo, check=True,
    )
    with Memory(repo) as mem:
        answer.point(repo, mem)
    return repo


def _ask(repo: Path, question: str = "where is settle_trade"):
    with Memory(repo) as mem:
        return [p for p in answer.ask(repo, mem, question) if p.source == "code"]


@pytest.mark.critical
def test_a_symbol_that_moved_is_cited_where_it_is_now(repo: Path) -> None:
    """The reproduction, exactly.

    Line 1 held the definition when the repo was read and holds a comment
    now. Citing it is a false receipt on the one part of an answer a reader
    is invited to go and check.
    """
    (repo / "pay.py").write_text(MOVED, encoding="utf-8")

    found = _ask(repo)

    assert found, "moving a function does not delete it"
    assert found[0].where == "pay.py:6", f"cited {found[0].where}, which is a comment"


@pytest.mark.critical
def test_a_symbol_the_file_no_longer_has_is_not_offered(repo: Path) -> None:
    (repo / "pay.py").write_text("# nothing here now\n", encoding="utf-8")

    assert not _ask(repo)


def test_a_symbol_that_has_not_moved_keeps_its_line(repo: Path) -> None:
    """The check must not cost a correct citation its line number."""
    found = _ask(repo)

    assert found
    assert found[0].where == "pay.py:1"


def test_deleting_the_file_drops_the_symbol(repo: Path) -> None:
    (repo / "pay.py").unlink()

    assert not _ask(repo)


def test_a_file_that_cannot_be_read_keeps_its_citation(repo: Path) -> None:
    """Not being able to check is not evidence against.

    The same policy the rules got. A permissions error is not a deletion, and
    refusing on one would make knos quieter every time a repo was awkward
    rather than every time it was wrong.
    """
    line = code.still_defines(repo, "settle_trade", "pay.py", 1)

    assert line == 1


def test_a_declaration_is_preferred_over_a_mention(tmp_path: Path) -> None:
    """A name is usually used before it is defined, and a call is not a receipt."""
    f = tmp_path / "m.py"
    f.write_text(
        "result = settle_trade(1)\n"
        "print(settle_trade)\n"
        "\n"
        "def settle_trade(x):\n"
        "    return x\n",
        encoding="utf-8",
    )

    assert code.still_defines(tmp_path, "settle_trade", "m.py", 99) == 4


def test_a_name_it_cannot_place_keeps_a_line_rather_than_vanishing(
    tmp_path: Path,
) -> None:
    """Being one line out is a smaller failure than dropping a real symbol.

    The declaration test above is a heuristic over the languages ctags reads,
    and it will not recognise every one of them. When it cannot tell which
    mention is the declaration, the symbol is still there and still worth
    answering with.
    """
    f = tmp_path / "m.odd"
    f.write_text("something settle_trade <- 1\nmore settle_trade\n", encoding="utf-8")

    assert code.still_defines(tmp_path, "settle_trade", "m.odd", 99) == 1


def test_a_commit_is_not_re_checked_against_anything(repo: Path) -> None:
    """The invariant, and its deliberate limit.

    Every citation knos prints is either verified at the moment it is printed
    - rules and code, the two that name a line in a file somebody is editing -
    or is a historical record whose identifier cannot move. A commit is the
    second kind: it said what it said, and re-reading the file it touched
    would not make the message any truer.
    """
    with Memory(repo) as mem:
        found = answer.ask(repo, mem, "init")

    commits = [p for p in found if p.source == "git"]

    assert commits, "the commit should still be an answer"
    assert "pay.py" not in commits[0].where, (
        "a commit is cited by its hash, not by a line that could move"
    )
