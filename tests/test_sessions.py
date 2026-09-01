"""Reading agent history, and answering from a session and from commits."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from knos import answer, git, sessions
from knos.memory import Memory

# Appears in a session transcript and nowhere else on disk.
ONLY_IN_A_SESSION = "we dropped redis because it was one dependency for one counter"


def _claude_log(root, repo, text: str) -> None:
    d = root / "projects" / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sess.jsonl").write_text(
        "\n".join(
            json.dumps(rec)
            for rec in [
                {"type": "custom-title", "sessionId": "abc12345", "customTitle": "x"},
                {
                    "type": "user",
                    "sessionId": "abc12345",
                    "timestamp": "2026-08-20T10:00:00Z",
                    "cwd": str(repo),
                    "message": {"role": "user", "content": text},
                },
                {
                    "type": "assistant",
                    "sessionId": "abc12345",
                    "timestamp": "2026-08-20T10:00:05Z",
                    "cwd": str(repo),
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Write", "input": {}},
                            {"type": "text", "text": "Noted, redis is gone for good."},
                        ],
                    },
                },
            ]
        ),
        encoding="utf-8",
    )


def _cursor_db(path, text: str, workspace: str = "ws1") -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        ("bubbleId:comp-1:bub-1", json.dumps({"type": 1, "text": text})),
    )
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        (
            "composerData:comp-1",
            json.dumps({"workspaceIdentifier": {"id": workspace}}),
        ),
    )
    conn.commit()
    conn.close()


def test_reads_claude_code_history(tmp_path, repo, monkeypatch):
    root = tmp_path / "claude"
    _claude_log(root, repo, ONLY_IN_A_SESSION)
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(root / "projects"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    turns = sessions.read_all(repo)
    assert [t.role for t in turns] == ["user", "agent"]
    assert turns[0].text == ONLY_IN_A_SESSION
    assert turns[0].client == "Claude Code"
    assert "abc12345" in turns[0].where
    # A tool call is not prose and is not remembered.
    assert turns[1].text == "Noted, redis is gone for good."


def _cursor_workspace(tmp_path, folder, name="ws1"):
    """Cursor's record of which folder one window had open."""
    d = tmp_path / "workspaceStorage" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspace.json").write_text(
        json.dumps({"folder": Path(folder).as_uri()}), encoding="utf-8"
    )
    return name


def test_reads_cursor_history_for_the_repo_it_belongs_to(tmp_path, repo, monkeypatch):
    db = tmp_path / "state.vscdb"
    _cursor_db(db, ONLY_IN_A_SESSION, workspace=_cursor_workspace(tmp_path, repo))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(db))
    monkeypatch.setenv("KNOS_CURSOR_WORKSPACES", str(tmp_path / "workspaceStorage"))
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))

    turns = sessions.read_all(repo)
    assert len(turns) == 1
    assert turns[0].client == "Cursor"
    assert turns[0].text == ONLY_IN_A_SESSION


def test_cursor_history_from_another_repo_never_leaks_in(tmp_path, repo, monkeypatch):
    """One file holds every window's history, so the folder decides."""
    elsewhere = tmp_path / "someone-elses-project"
    elsewhere.mkdir()
    db = tmp_path / "state.vscdb"
    _cursor_db(db, ONLY_IN_A_SESSION, workspace=_cursor_workspace(tmp_path, elsewhere))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(db))
    monkeypatch.setenv("KNOS_CURSOR_WORKSPACES", str(tmp_path / "workspaceStorage"))
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))

    assert sessions.read_all(repo) == []


def test_a_cursor_window_with_no_folder_belongs_to_no_repo(tmp_path, repo, monkeypatch):
    """An empty window's conversation is about nothing knos can name."""
    db = tmp_path / "state.vscdb"
    _cursor_db(db, ONLY_IN_A_SESSION, workspace="empty-window")
    (tmp_path / "workspaceStorage").mkdir(exist_ok=True)
    monkeypatch.setenv("KNOS_CURSOR_DB", str(db))
    monkeypatch.setenv("KNOS_CURSOR_WORKSPACES", str(tmp_path / "workspaceStorage"))
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))

    assert sessions.read_all(repo) == []


def test_answers_from_a_session_alone(knos_home, tmp_path, repo, monkeypatch):
    """1.4's acceptance: the answer is in no file, only in a past session."""
    root = tmp_path / "claude"
    _claude_log(root, repo, ONLY_IN_A_SESSION)
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(root / "projects"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    assert not list(repo.rglob("*redis*"))

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        found = answer.ask(repo, mem, "why did we drop redis")
    assert any("one dependency for one counter" in p.text for p in found)
    assert any("Claude Code session" in p.where for p in found)


def test_answers_who_touched_what_from_commits_alone(knos_home, tmp_path, repo, monkeypatch):
    """1.5's acceptance."""
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        found = answer.ask(repo, mem, "who touched login last and why")
    assert found
    top = found[0]
    assert "login" in top.text.lower()
    assert top.where.startswith("commit ")

    commits = git.read_commits(repo)
    assert commits[0].author == "Tess Marlow"
    assert "src/auth.py" in commits[0].files


def test_a_missing_client_is_not_an_error(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "nope"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "nope.vscdb"))
    assert sessions.read_all(repo) == []


def test_a_corrupt_transcript_is_skipped_not_fatal(tmp_path, repo, monkeypatch):
    root = tmp_path / "claude"
    _claude_log(root, repo, ONLY_IN_A_SESSION)
    (root / "projects" / "demo" / "broken.jsonl").write_text(
        "{not json at all\n" + json.dumps({"type": "user"}) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(root / "projects"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    assert len(sessions.read_all(repo)) == 2
