"""`knos work list` prints the rows knos_find_work returns (it crashed on a key the rows no longer carry)."""
from __future__ import annotations

from typer.testing import CliRunner

from knos import cli, mcp

ROW = {"repo": "octo/widgets", "issue": 7, "you_receive_usdc": "19.94", "you_receive_units": 19_940_000, "money": "test USDC",
       "mode": "merge", "deadline": "2026-11-01T00:00:00Z", "acceptance": {"command": None, "note": "merge the pull request"}}


def test_work_list_prints_what_the_worker_receives(monkeypatch):
    monkeypatch.setattr(mcp.Server, "_find_work", lambda self, args: {"work": [ROW, {**ROW, "repo": None, "repo_id": 42, "you_receive_usdc": None}], "said": "2 open."})
    cli.load("work")
    got = CliRunner().invoke(cli._app, ["work", "list"])
    assert got.exit_code == 0, got.output
    assert "19.94 test USDC  octo/widgets#7  merge" in got.output and "19940000 test USDC  42#7" in got.output and "2 open." in got.output
