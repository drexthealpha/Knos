"""Failing like a tool developers trust, and provenance that resolves."""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from knos import answer, errors, git, private
from knos.memory import Memory

NEXT_COMMAND = re.compile(r"knos [a-z]+")


def _problems(repo):
    return [
        errors.nothing_indexed(),
        errors.no_such_folder("nope"),
        errors.nothing_found(repo),
        errors.memory_full(repo),
        errors.not_a_repo(str(repo)),
        errors.code_engine_missing(),
    ]


@pytest.mark.parametrize("kind", range(6))
def test_every_message_ends_with_a_command_or_a_link(knos_home, repo, kind):
    problem = _problems(repo)[kind]
    # Either a knos command, or the one-line install of the thing that is
    # missing. Both are something a person can act on without reading docs.
    assert NEXT_COMMAND.search(problem.fix) or "install" in problem.fix


@pytest.mark.parametrize("kind", range(6))
def test_no_message_reads_like_a_crash(knos_home, repo, kind):
    text = str(_problems(repo)[kind]).lower()
    for word in ("traceback", "exception", "error:", "failed", "fatal", ".py", "none"):
        assert word not in text


def test_a_corrupt_file_is_named_and_skipped_not_fatal():
    skipped = [errors.unreadable("build/out.bin", "it is not text")]
    report = errors.report_skipped(skipped)
    assert "build/out.bin was skipped" in report
    assert "Everything else was read." in report


def test_many_skipped_files_do_not_flood_the_screen():
    report = errors.report_skipped([errors.unreadable(f"f{i}") for i in range(30)])
    assert len(report.splitlines()) == 7
    assert "and 25 more." in report


def test_nothing_skipped_says_nothing():
    assert errors.report_skipped([]) == ""


def test_a_file_deleted_after_reading_is_marked_stale_not_silently_wrong():
    assert errors.stale("src/gone.py") == "src/gone.py is gone since knos read it"


def test_a_skipped_private_file_is_never_reported(knos_home, repo, tmp_path, monkeypatch):
    """3.4 must not undo 1.6: a skip notice would confirm the secret exists."""
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    with Memory(repo) as mem:
        counts = answer.point(repo, mem, index_code=False)
    report = errors.report_skipped(counts["skipped"])
    assert ".env" not in report
    assert ".env" not in str(counts["skipped"])


def test_a_folder_with_no_git_history_still_reads(knos_home, tmp_path, monkeypatch):
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("x = 1\n", encoding="utf-8")
    with Memory(plain) as mem:
        counts = answer.point(plain, mem, index_code=False)
    assert counts["commits"] == 0
    assert git.read_commits(plain) == []


# ---- 3.2: every answer names a source, and the source resolves ---------


def test_every_answer_carries_a_source_that_resolves(knos_home, tmp_path, repo, monkeypatch):
    root = tmp_path / "claude" / "projects" / "demo"
    root.mkdir(parents=True)
    (root / "s.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "cafe0001",
                "timestamp": "2026-08-20T10:00:00Z",
                "cwd": str(repo),
                "message": {
                    "role": "user",
                    "content": "we dropped redis because it was one dependency for one counter",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "claude" / "projects"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        found = []
        for question in ("why did we drop redis", "who touched login last", "auth"):
            found += answer.ask(repo, mem, question)

    assert found
    shas = {c.short for c in git.read_commits(repo)}
    for passage in found:
        assert passage.where.strip(), passage.text
        if passage.where.startswith("commit "):
            assert passage.where.split()[1] in shas
        elif "session" in passage.where:
            # A session source names the client, the session and the day.
            assert re.search(r"session [0-9a-f]{8} \d{4}-\d{2}-\d{2}", passage.where)
        else:
            # Anything else is a place in the repo.
            assert ":" in passage.where or (repo / passage.where).exists()


def test_a_source_is_never_a_private_path(knos_home, repo):
    from knos.memory import Fact

    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="the key is here",
                source="session",
                where="Claude Code session dead0001 2026-08-20",
                when="2026-08-20",
                path=".env",
            )
        )
        found = answer.ask(repo, mem, "key", identity=private.AGENT)
    assert all(".env" not in p.where and ".env" not in p.path for p in found)
