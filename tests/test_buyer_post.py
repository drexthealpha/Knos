"""`knos task post` (src/knos/buyer.py): a buyer posts a task with sealed hidden tests, sees the fee before funding,
and nothing is sent or funded without being asked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knos import buyer, judge, referee

SPEC = "# Make slugify drop punctuation\n\nWhat done means: ...\n"
BLACKBOX = 'import os, subprocess, sys\nsys.exit(subprocess.run([os.environ["KNOS_RUN"], "python3", "-c", "print(1)"]).returncode)\n'


def _task(tmp_path: Path, spec: str = SPEC, bundle: dict | None = None) -> tuple[Path, Path]:
    s = tmp_path / "spec.md"
    s.write_text(spec, encoding="utf-8")
    b = tmp_path / "hidden" / "slug"
    b.mkdir(parents=True)
    for name, text in (bundle or {"blackbox.py": BLACKBOX}).items():
        (b / name).write_text(text, encoding="utf-8")
    return s, b


def test_the_plan_seals_the_hidden_tests_and_says_the_fee_before_any_money_moves(tmp_path):
    s, b = _task(tmp_path)
    p = buyer.plan(s, b, "acme/widgets", "20", days=3, mint="Mint111", keypair="w.json")
    assert p["title"] == "Make slugify drop punctuation" and p["warnings"] == []
    assert p["seal"]["spec_hash"] == judge.checks_hash(b) and p["seal"]["judge_hash"] == referee.judge_hash()
    assert p["seal_hash"] == referee.seal_hash(p["seal"])
    assert p["fund_command"] == ["knos", "fund-wallet", "acme/widgets#<issue>", "20", "--checks", "none", "--days", "3",
                                 "--mint", "Mint111", "--keypair", "w.json"]
    assert p["fees"][0].startswith("At payout the program takes 0.30% of the amount, at least 0.05: 0.06 here, so the worker receives 19.94.")
    text = "\n".join(buyer.lines(p))
    assert "Nothing was sent." in text and "knos fund-wallet acme/widgets#<issue> 20" in text and "knos referee works" in text


def test_a_small_amount_pays_the_floor_fee():
    assert buyer.fee_lines(1_000_000)[0].startswith("At payout the program takes 0.30% of the amount, at least 0.05: 0.05 here, so the worker receives 0.95.")


@pytest.mark.parametrize("spec,bundle,words", [
    ("no heading here\n", None, "no heading"),
    ("# A task\n/knos fund 20\n", None, "/knos fund"),
    (SPEC, {}, "empty"),
])
def test_it_refuses_what_would_post_the_wrong_task(tmp_path, spec, bundle, words):
    s, b = _task(tmp_path, spec, bundle if bundle is not None else None)
    if bundle == {}:
        for f in b.iterdir():
            f.unlink()
    with pytest.raises(buyer.Refused, match=words.replace("/", ".")):
        buyer.plan(s, b, "acme/widgets", "20")
    with pytest.raises(buyer.Refused, match="OWNER/NAME"):
        buyer.plan(s, b, "not a repo", "20")


def test_hidden_tests_inside_a_repository_or_not_black_box_are_warned_about(tmp_path):
    (tmp_path / ".git").mkdir()
    s, b = _task(tmp_path, bundle={"test_slug.py": "def test_x():\n    assert True\n"})
    notes = buyer.plan(s, b, "acme/widgets", "5")["warnings"]
    assert any("inside the git repository" in n for n in notes) and any("not black-box" in n for n in notes)


def test_send_opens_the_issue_seals_against_its_number_and_posts_the_seal_but_moves_no_money(tmp_path):
    s, b = _task(tmp_path)
    calls = []

    def gh(*args):
        calls.append(args)
        return "https://github.com/acme/widgets/issues/42" if args[:2] == ("issue", "create") else "https://github.com/acme/widgets/issues/42#issuecomment-1"
    got = buyer.send(buyer.plan(s, b, "acme/widgets", "20", days=3), gh=gh)
    assert [c[:2] for c in calls] == [("issue", "create"), ("issue", "comment")]
    assert calls[0][calls[0].index("--title") + 1] == "Make slugify drop punctuation"
    assert got["issue"] == 42 and got["seal"]["issue"] == "42" and got["sent"]
    sealed = json.loads(Path(got["seal_file"]).read_text(encoding="utf-8"))
    assert sealed["spec_hash"] == judge.checks_hash(b) and sealed["seal_hash"] == got["seal_hash"]
    body = calls[1][calls[1].index("--body") + 1]
    assert got["seal"]["spec_hash"] in body and "knos fund-wallet acme/widgets#42 20" in body and "0.30%" in body
    assert all(c[0] == "issue" for c in calls)        # gh only opens and comments; the buyer runs fund-wallet


def test_knos_task_post_is_on_the_command_line_and_sends_nothing_by_default(tmp_path):
    from typer.testing import CliRunner

    from knos.cli import app as _app
    s, b = _task(tmp_path)
    r = CliRunner().invoke(_app, ["task", "post", str(s), "--tests", str(b), "--repo", "acme/widgets", "--amount", "20"])
    assert r.exit_code == 0, r.output
    assert "Nothing was sent." in r.output and "knos fund-wallet acme/widgets#<issue> 20" in r.output
    r = CliRunner().invoke(_app, ["task", "post", str(s), "--tests", str(tmp_path / "none"), "--repo", "acme/widgets", "--amount", "20"])
    assert r.exit_code == 1 and "not a folder of hidden tests" in r.output


def test_an_unreadable_board_points_to_the_escrow_on_chain(tmp_path):
    from knos import tasks
    with pytest.raises(tasks.Stop, match="knos bounty OWNER/REPO#ISSUE"):
        tasks.fetch(str(tmp_path / "missing-board.json"))
