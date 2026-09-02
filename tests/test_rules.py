"""CLAUDE.md and AGENTS.md, read as sources like any other.

Most of what a coding agent does with documentation happens in these files.
They are also the ones that go stale and get rewritten. Answering from them
with a file and a line is the part a person can check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from knos import answer, paths, rules
from knos.memory import Memory


def _commit(repo: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "rules"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def test_the_rules_of_the_repo_are_answered_with_a_file_and_a_line(knos_home, repo):
    (repo / "CLAUDE.md").write_text(
        "# Project rules\n\nNever use a bare except. Name the exception you expect.\n",
        encoding="utf-8",
    )
    (repo / "AGENTS.md").write_text(
        "# Agent rules\n\nAsk before adding a dependency. The build is the product.\n",
        encoding="utf-8",
    )
    _commit(repo)

    with Memory(repo) as mem:
        counts = answer.point(repo, mem, index_code=False)
        assert counts["rules"] >= 2
        found = answer.ask(repo, mem, "what are the rules here?")

    where = [p.where for p in found if p.source == "rules"]
    assert any(w.startswith("CLAUDE.md:") for w in where), where
    assert any(w.startswith("AGENTS.md:") for w in where), where
    # A line number a person can open, not just a file name.
    assert all(int(w.split(":")[1]) > 0 for w in where)


def test_a_written_rule_outranks_the_session_arguing_about_it(knos_home, repo):
    (repo / "CLAUDE.md").write_text(
        "# Rules\n\nEvery change ships with a test. A green run you did not"
        " watch is not green.\n",
        encoding="utf-8",
    )
    _commit(repo)
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        found = answer.ask(repo, mem, "what are the rules about tests")
    assert found and found[0].source == "rules", [(p.source, p.where) for p in found[:3]]


def test_a_dependency_brings_its_own_rules_and_they_are_not_yours(knos_home, repo):
    """A vendored CLAUDE.md is written for somebody else's repo."""
    vendored = repo / "vendor" / "someone-else"
    vendored.mkdir(parents=True)
    (vendored / "CLAUDE.md").write_text(
        "# Theirs\n\nAlways run the release script before merging.\n", encoding="utf-8"
    )
    (repo / ".gitignore").write_text("vendor/\n", encoding="utf-8")
    _commit(repo)

    assert rules.files(repo) == []


def test_a_heading_on_its_own_is_not_a_rule(knos_home, repo):
    (repo / "CLAUDE.md").write_text(
        "# Rules\n\n## Testing\n\nEvery change ships with a test.\n", encoding="utf-8"
    )
    _commit(repo)
    kept = [r.text for r in rules.read(repo)]
    assert "## Testing" not in kept
    assert any("Every change ships with a test." in k for k in kept)


def test_decisions_kept_beside_the_code_are_read_too(knos_home, repo):
    """Two reviewers said they keep decision logs and worklogs in the repo
    on purpose. Reading only CLAUDE.md ignored exactly the files those
    people had chosen to write."""
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "adr" / "0001-use-sqlite.md").write_text(
        "# 0001. Use SQLite\n\nWe chose SQLite because a server is one more"
        " thing to run and nobody wanted to operate it.\n",
        encoding="utf-8",
    )
    (repo / "WORKLOG.md").write_text(
        "# Worklog\n\n2026-08-30: moved the retry logic out of auth.py because"
        " it retried the password check as well.\n",
        encoding="utf-8",
    )
    _commit(repo)

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        sqlite = answer.ask(repo, mem, "why did we choose sqlite")
        retry = answer.ask(repo, mem, "why did the retry logic move")

    assert any(p.where.startswith("docs/adr/0001-use-sqlite.md:") for p in sqlite), [
        p.where for p in sqlite
    ]
    assert any(p.where.startswith("WORKLOG.md:") for p in retry), [p.where for p in retry]


def test_a_vendored_decision_record_is_still_not_yours(knos_home, repo):
    vendored = repo / "vendor" / "dep" / "docs" / "adr"
    vendored.mkdir(parents=True)
    (vendored / "0001-theirs.md").write_text(
        "# Theirs\n\nAlways run the release script before merging.\n", encoding="utf-8"
    )
    (repo / ".gitignore").write_text("vendor/\n", encoding="utf-8")
    _commit(repo)
    assert not [f for f in rules.files(repo) if "vendor" in f.as_posix()]
