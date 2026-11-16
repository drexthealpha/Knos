"""Contested results stay private: never published, no badge, nothing public written, by the library or the command."""
from __future__ import annotations

import json
import sys

import pytest

from knos.repro import example, publish as pb, run as rr, spec as sp


def _load(root):
    spec, sha = sp.load(root)
    spec["compute"]["max_seconds"] = 900.0          # room for a loaded test machine
    return spec, sha


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("repro")
    honest = example.write(tmp / "honest", python=sys.executable)
    bad = example.write(tmp / "bad", tamper=True, python=sys.executable)
    return {"honest": rr.reproduce(honest, *_load(honest), seed_source=lambda: 99), "bad": rr.reproduce(bad, *_load(bad), seed_source=lambda: 99),
            "dirs": {"honest": honest, "bad": bad}}


def test_publish_refuses_a_contested_result_and_writes_nothing(results, tmp_path):
    result, logs = results["bad"]
    kept = pb.keep(result, logs, tmp_path)
    with pytest.raises(pb.NotPublishable, match="stays private"):
        pb.publish(result, tmp_path)
    assert not (tmp_path / "public").exists()
    assert sorted(p.name for p in kept.iterdir()) == ["NOTICE-TO-AUTHORS.md", "logs.json", "result.json"]
    notice = (kept / "NOTICE-TO-AUTHORS.md").read_text()
    assert "Private" in notice and "@drexthealpha" in notice and "will not publish" in notice


def test_a_contested_result_cannot_be_made_publishable_by_editing_it(results, tmp_path):
    result, _ = results["bad"]
    forged = json.loads(json.dumps(result))
    forged.update(status="reproduced", private=False)
    for c in forged["claims"]:
        c.update(holds=True, why="")
    assert "digest" in pb.checks(forged)                                    # the digest no longer matches
    forged["digest"] = rr.digest(forged)                                    # ...and re-hashing does not help a contested claim's numbers
    forged["cheats"] = [{"rule": "reported_mismatch"}]
    with pytest.raises(pb.NotPublishable):
        pb.publish(forged, tmp_path)
    assert not (tmp_path / "public").exists()


def test_the_command_keeps_a_contested_result_private(results, tmp_path):
    from typer.testing import CliRunner

    from knos import cli
    out = tmp_path / "out"
    got = CliRunner().invoke(cli.app, ["reproduce", str(results["dirs"]["bad"]), "--out", str(out)])
    assert got.exit_code == 1 and "Kept private" in got.output and "nothing was published" in got.output
    assert not (out / "public").exists() and len(list((out / "private").iterdir())) == 1


def test_a_reproduced_result_publishes_a_page_per_claim_and_the_funding_link_only_there(results, tmp_path):
    result, logs = results["honest"]
    folder = pb.publish(result, tmp_path)
    assert sorted(p.name for p in folder.iterdir()) == ["badge.md", "badge.svg", "index.html", "result.json"]
    page = (folder / "index.html").read_text()
    assert '<section id="accuracy">' in page and "<script" not in page and "held-out" in page
    assert "funding" not in page                                            # the example names none
    funded = dict(result, funding="https://example.org/fund")
    funded["digest"] = rr.digest(funded)
    assert "https://example.org/fund" in pb.page(funded) and "https://example.org/fund" not in pb.badge_svg(funded)
    assert json.loads((folder / "result.json").read_text())["digest"] == result["digest"]
    assert all(v not in json.dumps(logs) for v in ("GH_TOKEN", "BEGIN PRIVATE"))


def test_a_signed_result_verifies_only_for_its_own_digest(results):
    from knos import reproduce as rp
    result, _ = results["honest"]
    assert pb.verify_signed({"result": result, "token": "x.y.z"}, {})[1]
    assert pb.verify_signed({"result": result}, {})[1] == ['a signed reproduction is {"result": the result, "token": GitHub\'s token} and nothing else']
    assert rp.AUDIENCE != pb.AUDIENCE                                       # a Knos reproduction's token cannot stand for a research result
