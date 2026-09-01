"""One answer that needs two sources, and cannot come from either alone."""

from __future__ import annotations

import json
import subprocess

import pytest

from knos import answer, link
from knos.memory import Memory

# The session says why, and names the file. It never says when, and it is
# not in any file on disk.
DECISION = (
    "we agreed to move the retry logic out of src/auth.py because it was"
    " retrying the password check as well as the token refresh"
)


@pytest.fixture()
def two_sources(tmp_path, repo, monkeypatch, knos_home):
    """A repo whose story is split between a session and a later commit."""
    root = tmp_path / "claude" / "projects" / "demo"
    root.mkdir(parents=True)
    (root / "s.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "beef0001",
                "timestamp": "2026-08-21T09:00:00Z",
                "cwd": str(repo),
                "message": {"role": "user", "content": DECISION},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "claude" / "projects"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    # The commit says what changed and when. It never says why.
    (repo / "src" / "auth.py").write_text(
        "def login():\n    return True\n\n\ndef refresh():\n    return True\n",
        encoding="utf-8",
    )
    for args in (["add", "-A"], ["commit", "-q", "-m", "Split token refresh out of login"]):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)
    return repo


def test_a_question_needing_a_session_and_a_commit(two_sources, knos_home):
    repo = two_sources
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        found = answer.ask(repo, mem, "why was the retry logic moved out of auth")
        joined = link.cross(repo, found)

    assert joined, "no two-hop answer"
    hop = joined[0]
    assert "src/auth.py" in hop.file
    assert "retrying the password check" in hop.decision.text  # the why
    assert "token refresh" in hop.change.text  # the what
    assert "session" in hop.where and "commit" in hop.where


def test_neither_source_answers_it_alone(two_sources, knos_home):
    """The session has no commit, the commit has no reason. Only both do."""
    repo = two_sources
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        found = answer.ask(repo, mem, "why was the retry logic moved out of auth")

    sessions = [p for p in found if p.source == "session"]
    commits = [p for p in found if p.source == "git"]
    assert sessions and commits

    assert not any("commit " in p.where for p in sessions)
    assert not any("retrying the password check" in p.text for p in commits)


def test_no_link_when_nothing_joins_them(knos_home, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        found = answer.ask(repo, mem, "login")
    assert link.cross(repo, found) == []


def test_a_private_path_is_never_the_link(knos_home, repo):
    """The join is a file path, so it has to obey the same rule as search."""
    assert link.paths_in("the key is in .env next to src/auth.py", repo) == {"src/auth.py"}


def test_paths_are_recognised_the_way_people_type_them(knos_home, repo):
    found = link.paths_in("moved it from src/auth.py into lib/token/refresh.py", repo)
    assert found == {"src/auth.py", "lib/token/refresh.py"}
