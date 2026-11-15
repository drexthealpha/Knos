"""`knos stats --share`: one line of counts, with no path or repo detail in it."""

from __future__ import annotations

from knos.claims import Claims
from knos.cli import main
from knos.identity import Agent


def test_share_line_is_counts_only(knos_home, repo, capsys):
    with Claims(repo) as c:
        c.take(Agent(host="claude", session="aaaa"), "auth", ["src/auth.py"])
        took, clash, _ = c.take(Agent(host="codex", session="bbbb"), "auth too", ["src/auth.py"])
        assert not took
        c.note_block(Agent(host="codex", session="bbbb"), "src/auth.py", clash)
    capsys.readouterr()
    assert main(["stats", "--share"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("My agents: 1 claims") and "1 conflicting edits refused" in line
    assert "auth" not in line and repo.name not in line
