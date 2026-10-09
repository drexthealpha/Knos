"""Assurance levels (src/knos/assurance.py): computed from the evidence, never above what exists today, and the four
words a statement keeps apart."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knos import assurance as A
from knos import receipt as rc
from knos import statement as S

ROOT = Path(__file__).resolve().parents[1]
V5 = json.loads((ROOT / "docs" / "receipt" / "vectors.v5.json").read_text(encoding="utf-8"))["valid_v5"]
DATA = ROOT / "tests" / "data" / "statement"


def _receipt(x: dict) -> dict:
    return x["receipt"] if "receipt" in x else x


def test_the_levels_are_four_in_order_and_two_are_reachable():
    assert A.LEVELS == ("workflow-reported", "re-executed", "independently-attested", "proved")
    assert A.REACHABLE == A.LEVELS[:2]
    assert set(A.FROM_RECEIPT) == set(rc.LEVELS)


@pytest.mark.parametrize("n", range(len(V5)))
def test_a_receipt_reaches_what_its_evidence_shows(n):
    r = _receipt(V5[n])
    got = A.of_receipt(r)
    was = rc.assurance_of(r, r["assurance"]["declared_related"])["level"]
    assert got["receipt_level"] == was
    if r["issuer_authenticated"] is None:
        assert got["level"] is None and not got["identity_proved"] and got["proved"] == []
    else:
        assert got["level"] == {"reported": "workflow-reported", "rerun": "re-executed", "agreed": "re-executed"}[was]
        assert got["identity_proved"] and got["proved"] == [A.PROVED]
    reached = [s["level"] for s in got["ladder"] if s["reached"]]
    assert "independently-attested" not in reached and "proved" not in reached
    assert "never proved" in got["never"]


def test_a_level_nothing_reaches_is_refused():
    with pytest.raises(ValueError):
        A._check("independently-attested")
    with pytest.raises(ValueError):
        A.of_line({"assurance": "attested", "evaluations": ["e"]})


def test_a_shadow_line_reaches_no_level_without_a_receipt():
    st = json.loads((DATA / "sept.json").read_text(encoding="utf-8"))
    assert st["source"] == "shadow"
    lines = [{**x, "assured": A.of_line(x, source=st["source"])} for x in S.lines_now(st)]
    assert all(x["assured"]["level"] is None for x in lines)
    words = A.words(st, lines)
    assert list(words) == list(A.WORDS)
    assert words["agreement"]["state"] == "differs" and words["completeness"]["state"] == "not checked"
    assert words["satisfaction"]["state"] == "not claimed"


def test_a_line_from_a_signed_source_is_workflow_reported():
    ln = {"assurance": "reported", "evaluations": ["ev_1"], "state": "agreed"}
    assert A.of_line(ln, source="events")["level"] == "workflow-reported"
    assert A.of_line({"assurance": "not evaluated", "evaluations": []})["level"] is None
    rerun = A.of_receipt(_receipt(V5[1]))
    assert A.of_line(ln, {"assured": rerun}, "events")["level"] == "re-executed"


def test_completeness_says_what_was_checked():
    st = {"source": "events"}
    lines = [{"state": "agreed", "assurance": "reported", "evaluations": ["e"]}]
    assert A.words(st, lines)["completeness"]["state"] == "not checked"
    assert A.words(st, lines, gaps=[{"state": "open"}])["completeness"]["state"] == "gaps"
    assert A.words(st, lines, gaps=[{"state": "explained"}])["completeness"]["state"] == "no gap found, not acknowledged"
    assert A.words(st, lines, gaps=[], acked=True)["completeness"]["state"] == "no gap found"
    assert A.words(st, lines)["correctness"]["state"] == "at least workflow-reported"


def test_the_command_prints_a_receipt_and_a_statement(tmp_path):
    import typer
    app = typer.Typer()
    A.register(app, [])

    @app.command("other")
    def _other() -> None:       # a second command keeps `assurance` a subcommand, as it is on the main app
        pass
    f = tmp_path / "r.json"
    f.write_text(json.dumps(_receipt(V5[1])), encoding="utf-8")
    got = CliRunner().invoke(app, ["assurance", str(f)])
    assert got.exit_code == 0 and "Assurance: re-executed" in got.output and "[ ] proved" in got.output
    got = CliRunner().invoke(app, ["assurance", str(DATA / "sept.json"), "--json"])
    out = json.loads(got.output)
    assert got.exit_code == 0 and out["words"]["satisfaction"]["state"] == "not claimed" and len(out["lines"]) == 5
