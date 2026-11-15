"""Reading agent history, and answering from a session and from commits.

Dropped in 0.2.0 (removed behaviour):
  - test_a_session_started_above_the_repo_is_still_found: 0.2.0 does the opposite. A session in a parent folder
    is not the child repo's; replaced by test_a_session_in_a_parent_folder_is_not_the_child_repos.
"""

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
        )
        + "\n",  # only complete lines are read: a transcript's last line is finished by its newline
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


def _line(cwd: str, text: str, session: str = "s1") -> str:
    return json.dumps(
        {
            "type": "user",
            "cwd": cwd,
            "sessionId": session,
            "timestamp": "2026-08-20T10:00:00Z",
            "message": {"content": text},
        }
    )


def _folder(projects: Path, path: Path, encode=sessions._encoded) -> Path:
    d = projects / encode(path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_a_session_in_a_parent_folder_is_not_the_child_repos(tmp_path, monkeypatch):
    """0.1 attributed a session held in a parent folder to every repo under it, which handed one project's
    conversations to agents working in a sibling. Only the repo itself, or a folder inside it, counts."""
    projects = tmp_path / "projects"
    repo = tmp_path / "work" / "myrepo"
    (repo / "sub").mkdir(parents=True)

    # A session held in the parent folder, working in the parent folder.
    (_folder(projects, repo.parent) / "a.jsonl").write_text(
        _line(str(repo.parent), "the parent folder decided something about every project in it") + "\n",
        encoding="utf-8",
    )
    # A session started in a subfolder of the repo.
    (_folder(projects, repo / "sub") / "b.jsonl").write_text(
        _line(str(repo / "sub"), "the risk guard refuses unknown assets and always has") + "\n",
        encoding="utf-8",
    )
    # A sibling whose name starts with the repo's: its folder name even starts with the repo's encoding.
    sibling = tmp_path / "work" / "myrepo-secret"
    sibling.mkdir(parents=True)
    (_folder(projects, sibling) / "c.jsonl").write_text(
        _line(str(sibling), "this belongs to a different project and must not appear") + "\n",
        encoding="utf-8",
    )
    # An unrelated project.
    other = tmp_path / "work" / "other"
    other.mkdir(parents=True)
    (_folder(projects, other) / "d.jsonl").write_text(
        _line(str(other), "an unrelated project talking about unrelated things") + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(projects))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    said = " ".join(t.text for t in sessions.read_all(repo))

    assert "risk guard" in said, "lost the session started in a subfolder of the repo"
    assert "parent folder decided" not in said, "a parent-folder session leaked into the child repo"
    assert "different project" not in said, "a sibling with a longer name leaked in"
    assert "unrelated project" not in said
    # The unrelated project's folder is never even opened.
    assert not [f for f in sessions._transcripts(projects, repo) if f.parent == _folder(projects, other)]


def test_the_claude_folder_encoding_replaces_every_non_alphanumeric():
    """Claude Code names a project folder by replacing every character that is not a letter or digit with '-'."""
    assert sessions._encoded(Path("C:\\Users\\me\\my_app.v2")) == "C--Users-me-my-app-v2"
    assert sessions._encoded(Path("/home/me/my app_v2.0")) == "-home-me-my-app-v2-0"
    # The rule 0.1 assumed kept '_', '.' and spaces; folders named that way are still matched.
    assert sessions._encoded_legacy(Path("/home/me/my app_v2.0")) == "-home-me-my app_v2.0"


def test_a_repo_path_with_dots_underscores_and_spaces_is_found(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    repo = tmp_path / "my projects" / "the_app.v2"
    repo.mkdir(parents=True)
    new = _folder(projects, repo)
    legacy = _folder(projects, repo, sessions._encoded_legacy)
    assert new != legacy, "the fixture path must tell the two encodings apart"
    (new / "a.jsonl").write_text(_line(str(repo), "filed under the folder name Claude Code uses now") + "\n",
                                 encoding="utf-8")
    (legacy / "b.jsonl").write_text(_line(str(repo), "filed under the folder name knos 0.1 assumed") + "\n",
                                    encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    (_folder(projects, other) / "c.jsonl").write_text(
        _line(str(other), "somebody else's project entirely here") + "\n", encoding="utf-8")

    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(projects))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    files = sessions._transcripts(projects, repo)
    assert {f.parent for f in files} == {new, legacy}
    said = " ".join(t.text for t in sessions.read_all(repo))
    assert "uses now" in said and "0.1 assumed" in said
    assert "somebody else" not in said


def test_transcripts_are_read_from_where_the_last_read_stopped(tmp_path, repo, monkeypatch):
    """Only complete lines are read, and a second read reads only what was appended."""
    projects = tmp_path / "projects"
    f = _folder(projects, repo) / "s.jsonl"
    first = _line(str(repo), "the first decision anyone wrote down here") + "\n"
    half = _line(str(repo), "the second decision, still being written")
    f.write_bytes((first + half[:40]).encode("utf-8"))  # bytes: transcripts end lines with \n on every OS
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(projects))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    offsets: dict[str, int] = {}
    got = [t.text for t in sessions.read_all(repo, offsets)]
    assert got == ["the first decision anyone wrote down here"]
    assert offsets[str(f)] == len(first.encode("utf-8")), "an incomplete line must not move the offset"

    f.write_bytes((first + half + "\n").encode("utf-8"))
    got = [t.text for t in sessions.read_all(repo, offsets)]
    assert got == ["the second decision, still being written"], "the first line was read twice"
    assert sessions.read_all(repo, offsets) == []


def test_cursor_turns_are_dated_by_when_they_were_said(tmp_path, repo, monkeypatch):
    """Not by the database file's modification time, which dated every turn to Cursor's last save."""
    import os

    db = tmp_path / "state.vscdb"
    ws = _cursor_workspace(tmp_path, repo)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    rows = [
        ("composerData:comp-1", {"workspaceIdentifier": {"id": ws}, "createdAt": 1735732800000}),  # 2025-01-01 12:00Z
        ("bubbleId:comp-1:b1", {"type": 1, "text": "a turn with its own time recorded on it",
                                "createdAt": 1740830400000}),  # 2025-03-01 12:00Z
        ("bubbleId:comp-1:b2", {"type": 2, "text": "a turn with no time of its own at all"}),
    ]
    for key, value in rows:
        conn.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()
    conn.close()
    os.utime(db, (1_800_000_000, 1_800_000_000))  # 2027: what the file's mtime would have said
    monkeypatch.setenv("KNOS_CURSOR_DB", str(db))
    monkeypatch.setenv("KNOS_CURSOR_WORKSPACES", str(tmp_path / "workspaceStorage"))
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))

    when = {t.text: t.when for t in sessions.read_all(repo)}
    assert when["a turn with its own time recorded on it"].startswith("2025-03-01")
    assert when["a turn with no time of its own at all"].startswith("2025-01-01"), "falls back to the composer"
    assert not any(w.startswith("2027") for w in when.values())


def test_a_sibling_project_with_a_longer_name_is_not_this_repo():
    from knos.sessions import _inside_repo
    assert _inside_repo('/work/app', '/work/app') and _inside_repo('/work/app/src', '/work/app')
    assert _inside_repo('c:\\work\\app\\src', 'c:\\work\\app')
    assert not _inside_repo('/work/app-secret', '/work/app')          # a sibling, not a subfolder
    assert not _inside_repo('c:\\work\\app2', 'c:\\work\\app')
