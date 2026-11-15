"""`knos record search`: the record searched in the memory engine's store across its tiers, with the engine's verdict saying why the
rows are what they are (an empty store is told apart from no match), and the store's free-tier status."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("sibyl_memory_client")

from knos import record  # noqa: E402
from knos.record import cli  # noqa: E402
from knos.record.search import search  # noqa: E402


def test_an_empty_record_says_it_is_empty_not_that_nothing_matched(tmp_path):
    got = search("test_edited", tmp_path / "rec")
    assert got["rows"] == [] and got["verdict"]["code"] == "empty_store"
    assert got["said"] and got["store"]["db_size_bytes"] >= 0


def test_a_verdict_and_a_cheat_are_found_with_their_reason(tmp_path):
    root = tmp_path / "rec"
    record.claim("claim-slug", {"title": "slugify drops punctuation (synthetic)", "spec_hash": "ab" * 32}, domain="code", root=root)
    record.append("cheat", {"spec_hash": "ab" * 32, "cheat": "test_edited", "rule": "gate.test_edited", "repo": "o/r", "pr": 7},
                  domain="code", root=root)
    got = search("test_edited", root)
    assert got["rows"] and got["verdict"]["code"] == "ok" and "matched" in got["said"]
    assert any("test_edited" in json.dumps(r) for r in got["rows"])
    miss = search("zebrafish", root)
    assert miss["rows"] == [] and miss["verdict"]["code"] == "no_match"


def test_the_command_prints_the_reason_and_the_rows(tmp_path, capsys):
    root = tmp_path / "rec"
    record.append("cheat", {"spec_hash": "cd" * 32, "cheat": "runner_tampering", "rule": "gate.runner_tampering", "repo": "o/r", "pr": 8},
                  domain="code", root=root)
    assert cli.main(["search", "runner_tampering", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "matched" in out and "runner_tampering" in out
    assert cli.main(["search", "runner_tampering", "--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"]["code"] == "ok"
