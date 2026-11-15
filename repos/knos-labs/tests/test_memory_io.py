"""`knos memory export/import/note`: the repo's Sibyl memory as one portable, verifiable file."""

from __future__ import annotations

import json

import pytest

from knos import memory_io, start_hook
from knos.cli import main
from knos.memory import Memory
from knos.proof import history


@pytest.fixture()
def client(tmp_path):
    from sibyl_memory_client import MemoryClient
    return MemoryClient.local(str(tmp_path / "a.db"), tenant_id="repo")


def _fill(client):
    s = history.SibylStore(client)
    history.record(s, "abc123", "Done: tests pass", ["tests"], [{"name": "tests", "ok": True}], True, at=1.0)
    history.observe(s, "abc123", "ci", False, "CI failed", at=2.0)
    history.learn_tamper(s, "widget", "codex", "deleted-tests", "tests/test_x.py removed", at=3.0)
    memory_io.note(client, "half way through the parser rewrite", at=4.0)


def test_export_is_sorted_versioned_and_hashed(client):
    _fill(client)
    doc = memory_io.export_doc(client, "widget")
    assert doc["schema"] == memory_io.SCHEMA and doc["continuity"] == "half way through the parser rewrite"
    cats = {e["category"] for e in doc["entities"]}
    assert {"proof_claim", "proof_outcome", "proof_rule", "tamper", "continuity"} <= cats
    keys = [(e["category"], e["name"]) for e in doc["entities"]]
    assert keys == sorted(keys) and doc["count"] == len(keys)
    assert memory_io.export_doc(client, "widget")["sha256"] == doc["sha256"]


def test_import_merges_idempotently(client, tmp_path):
    from sibyl_memory_client import MemoryClient
    _fill(client)
    doc = json.loads(json.dumps(memory_io.export_doc(client, "widget")))
    other = MemoryClient.local(str(tmp_path / "b.db"), tenant_id="repo")
    assert memory_io.import_doc(other, doc) == (doc["count"], 0)
    assert memory_io.import_doc(other, doc) == (0, doc["count"])
    assert memory_io.export_doc(other)["sha256"] == doc["sha256"]
    assert history.tamper_checks_required(history.SibylStore(other), "widget", None) == {"tamper:deleted-tests"}


def test_import_refuses_a_changed_file(client):
    _fill(client)
    doc = memory_io.export_doc(client)
    doc["entities"][0]["body"] = {"forged": True}
    with pytest.raises(ValueError, match="sha256"):
        memory_io.import_doc(client, doc)
    with pytest.raises(ValueError, match="schema"):
        memory_io.import_doc(client, {"schema": "other"})


def test_last_note_is_the_newest(client):
    memory_io.note(client, "first", at=1.0)
    memory_io.note(client, "second", at=2.0)
    assert memory_io.last_note(client)["text"] == "second"


def test_cli_note_export_import_and_session_start(knos_home, repo, capsys, tmp_path):
    with Memory(repo):
        pass   # the repo's store exists
    assert main(["memory", "note", "pick up at the tamper judge"]) == 0
    out_file = tmp_path / "mem.json"
    assert main(["memory", "export", "--out", str(out_file)]) == 0
    said = capsys.readouterr().out
    assert "pick up at the tamper judge" in said and "records" in said
    doc = json.loads(out_file.read_text(encoding="utf-8"))
    assert doc["continuity"] == "pick up at the tamper judge"
    assert main(["memory", "import", str(out_file)]) == 0
    assert f"0 written, {doc['count']} already here" in capsys.readouterr().out
    assert start_hook.main([]) == 0
    assert "Continuity note" in capsys.readouterr().out
    out_file.write_text("{}", encoding="utf-8")
    assert main(["memory", "import", str(out_file)]) != 0


def test_help_has_memory_and_main_stays_short():
    from knos import help as help_text
    assert "knos memory export" in help_text.for_command("memory")
    assert len(help_text.main().splitlines()) <= 24
