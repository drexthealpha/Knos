"""Codex sessions are read like Claude Code's: what was said in this repo, cited to the session, nothing else."""

from __future__ import annotations

import json
import os
from pathlib import Path

from knos import refresh, sessions
from knos.memory import Memory
from knos import answer


def _rollout(cwd: Path, lines: list[tuple[str, str]], name: str = "rollout-2026-09-20T10-00-00-abc.jsonl") -> Path:
    root = Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "09" / "20"
    root.mkdir(parents=True, exist_ok=True)
    f = root / name
    rows = [{"timestamp": "2026-09-20T10:00:00Z", "type": "session_meta",
             "payload": {"id": "codex-sess-1", "cwd": str(cwd)}}]
    rows.append({"timestamp": "2026-09-20T10:00:01Z", "type": "response_item", "payload": {
        "type": "message", "role": "user",
        "content": [{"type": "input_text", "text": "<environment_context>cwd and shell</environment_context>"}]}})
    for role, text in lines:
        rows.append({"timestamp": "2026-09-20T10:01:00Z", "type": "response_item", "payload": {
            "type": "message", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}})
    f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return f


def test_codex_turns_in_this_repo_are_read_and_injected_context_is_not(repo) -> None:
    _rollout(repo, [("user", "why did we drop the retry queue in the importer?"),
                    ("assistant", "We dropped the retry queue because the importer is idempotent now.")])
    turns = list(sessions.read_codex(repo))
    assert [t.role for t in turns] == ["user", "agent"]
    assert all(t.client == "Codex" and t.session == "codex-sess-1" for t in turns)
    assert not any("environment_context" in t.text for t in turns)


def test_a_codex_session_in_another_folder_is_not_this_repos(repo, tmp_path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    _rollout(other, [("assistant", "A decision about some other project entirely, long enough.")])
    assert list(sessions.read_codex(repo)) == []


def test_codex_answers_cite_the_codex_session(repo) -> None:
    _rollout(repo, [("assistant", "We dropped the retry queue because the importer is idempotent now.")])
    refresh.ensure(repo, force=True, index_code=False)
    with Memory(repo) as mem:
        found = answer.ask(repo, mem, "why did we drop the retry queue", limit=3)
    assert any("idempotent" in p.text and "Codex session" in p.where for p in found)


def test_codex_reads_are_incremental(repo) -> None:
    f = _rollout(repo, [("assistant", "First decision recorded in a Codex session here.")])
    offsets: dict[str, int] = {}
    assert len(list(sessions.read_codex(repo, offsets))) == 1
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"timestamp": "2026-09-20T11:00:00Z", "type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "A second decision appended later on."}]}}) + "\n")
    again = list(sessions.read_codex(repo, offsets))
    assert [t.text for t in again] == ["A second decision appended later on."]
