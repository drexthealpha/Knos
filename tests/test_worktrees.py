"""One repo, several working trees, one memory.

Worktrees are how people stop two agents overwriting each other's files, and
they are right to. But git gave each tree its own knos store, so a decision
made in one was invisible in the next and a claim in one held nothing in the
other — which is the half worktrees were never meant to solve.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from knos import answer, mcp, paths
from knos.memory import Memory


@pytest.fixture()
def worktree(repo, tmp_path):
    """A second working tree over the same repo."""
    other = tmp_path / "feature"
    done = subprocess.run(
        ["git", "worktree", "add", "-q", str(other), "-b", "feature"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        pytest.skip(f"git worktree unavailable: {done.stderr.strip()}")
    paths.shared_root.cache_clear()
    return other


def test_worktrees_of_one_repo_share_one_memory(knos_home, repo, worktree):
    assert paths.shared_root(worktree) == Path(repo).resolve()
    assert paths.store_for(worktree) == paths.store_for(repo)

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)

    # Read in the main tree, answered in the other one, with nothing run in
    # between and nothing to keep in sync.
    assert paths.has_store(worktree)
    with Memory(worktree) as mem:
        found = answer.ask(worktree, mem, "why did we drop redis")
    assert found, "the other worktree saw an empty store"


def test_a_claim_in_one_worktree_holds_in_another(knos_home, repo, worktree):
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        mem.working_on("the parser", "Claude Code", datetime.now(timezone.utc).isoformat())

    with Memory(worktree) as mem:
        said = mcp._held(mem, "how does parsing work", "Cursor", "")
    assert said.startswith("Withheld."), said
    assert "Claude Code" in said

    with Memory(repo) as mem:
        mem.done_working()
    with Memory(worktree) as mem:
        assert mcp._held(mem, "how does parsing work", "Cursor", "") == ""


def test_each_worktree_keeps_its_own_code_structure(knos_home, repo, worktree):
    """Two worktrees are usually two branches.

    Sharing what was decided is the point. Sharing what the code looks like
    would name a file and a line that is not in the tree you are standing in.
    """
    from knos import code

    assert code.tags_file(repo) != code.tags_file(worktree)


def test_a_repo_with_no_worktrees_is_unchanged(knos_home, repo):
    assert paths.shared_root(repo) == Path(repo).resolve()


def test_somewhere_that_is_not_a_repo_is_its_own_root(knos_home, tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert paths.shared_root(plain) == plain.resolve()


def test_an_agent_reads_the_repo_itself_on_its_first_question(knos_home, repo):
    """No knos command has ever been run here.

    Telling an agent to ask its person to run a command ends the
    conversation: the agent says it, the person does not see it, and knos
    looks broken on the one call meant to show what it is for.
    """
    from knos import mcp

    assert not paths.has_store(repo)
    said = mcp.search("why did we drop redis")
    assert "knos point" not in said
    assert "redis" in said.lower(), said
    assert paths.has_store(repo)


def test_the_code_reader_gets_a_budget_and_leaves_nothing_half_read(knos_home, repo):
    """A partial tags file would answer some questions and silently miss
    others, which is worse than answering none."""
    from knos import code

    if not code.installed():
        pytest.skip("universal-ctags not installed")
    # A budget this small always runs out on a real reader; if a machine is
    # fast enough that it does not, the invariant below is what matters and
    # there is nothing to check.
    result = code.index(repo, budget=0.001)
    if result.get("ran_out"):
        assert not code.indexed(repo), "left a half-read tags file behind"

    # And with time to work, it reads it properly.
    full = code.index(repo)
    assert full.get("ran_out") is None
    assert code.indexed(repo)


def test_the_code_reader_works_with_no_ctags_on_the_machine(knos_home, repo, monkeypatch):
    """The ordinary case for a cold `pip install` on Linux.

    Naming the ctags binary is what raises when it is absent, so doing it
    before the fallback branch meant a machine without ctags got an
    exception instead of the reader knos carries.
    """
    from knos import code

    monkeypatch.setattr(code, "installed", lambda: False)
    monkeypatch.setattr(code, "readtags", lambda: None)
    monkeypatch.setattr(
        code, "binary", lambda: (_ for _ in ()).throw(code.CodeUnavailable("absent"))
    )
    (repo / "src" / "risk.py").write_text(
        "class RiskGuard:\n    def check(self):\n        return True\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "risk"],
        cwd=str(repo), check=True, capture_output=True,
    )

    result = code.index(repo, budget=None)
    assert result.get("own") is True
    assert result["nodes"] > 0
    assert code.indexed(repo)

    found, _ = code.search(repo, "RiskGuard", limit=5)
    assert found, "no structural answer without ctags"
    assert found[0].where.endswith("src/risk.py:1"), found[0].where


def test_a_structural_question_that_finds_nothing_still_says_what_is_missing(
    knos_home, repo, monkeypatch
):
    """The large-repo case. Asking where something is defined, getting
    "Nothing known about that", and not being told the code structure was
    never read is the worst answer knos can give."""
    from knos import answer, code, mcp
    from knos.memory import Memory

    monkeypatch.chdir(repo)
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
    code.tags_file(repo).unlink(missing_ok=True)
    code.own_file(repo).unlink(missing_ok=True)
    assert not code.indexed(repo)

    said = mcp.search("where is some_symbol_nobody_has defined")
    assert "Nothing known about that." in said
    assert "knos point" in said, said
