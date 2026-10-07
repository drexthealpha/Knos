"""experiments/judge_proof: a judge for one task, proved in a zkVM. The proof itself needs a toolchain the test
machine does not have, so what is held here is everything around it: the plain judge's rule, that the journal the
verified proof committed to (results.json, written from a real run) is the journal the plain judge gives, that the
experiment is in no wheel and no sdist, and that docs/ATTESTOR.md states the measured numbers and nothing more."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "experiments" / "judge_proof"


def _reference():
    spec = importlib.util.spec_from_file_location("judge_proof_reference", HERE / "reference.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


REF = _reference()
CHECKS = (HERE / "checks.txt").read_bytes()
RESULTS = json.loads((HERE / "results.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> bytes:
    return (HERE / "fixtures" / f"{name}.txt").read_bytes()


@pytest.mark.parametrize("name,verdict,passed", [("honest", "passed", 7), ("wrong", "failed", 6), ("short", "failed", 0)])
def test_the_plain_judge_on_the_fixtures(name, verdict, passed):
    got = REF.read(REF.journal(CHECKS, _fixture(name)))
    assert (got["verdict"], got["passed"], got["total"]) == (verdict, passed, 7)
    assert got["submission_sha256"] == hashlib.sha256(_fixture(name)).hexdigest()
    assert got["checks_sha256"] == hashlib.sha256(CHECKS).hexdigest()


@pytest.mark.parametrize("submission", [
    b"", b"\n", b"3\n0\n2\n1\n5\n3\n10", b"3\n0\n2\n1\n5\n3\n10\n\n", b"3\r\n0\r\n2\r\n1\r\n5\r\n3\r\n10\r\n",
    b"3\n0\n2\n1\n5\n3\n10\n11\n", b" 3\n0\n2\n1\n5\n3\n10\n", b"\xff" * 64,
])
def test_only_the_exact_lines_pass(submission):
    passed, total = REF.judge(CHECKS, submission)
    assert total == 7
    assert (passed == total) == (submission in (_fixture("honest"), _fixture("honest")[:-1]))


def test_no_checks_never_pass():
    for checks in (b"", b"knos-judge-checks/1 task=none\n"):
        assert REF.read(REF.journal(checks, b""))["verdict"] == "failed"


def test_a_journal_is_read_strictly():
    good = REF.journal(CHECKS, _fixture("honest"))
    for bad in (good[:-1], good + b"\0", b"\x02" + good[1:], good[:65] + b"\x02" + good[66:]):
        with pytest.raises(ValueError):
            REF.read(bad)


def test_the_proved_runs_committed_the_plain_judges_journal():
    """results.json is what `run.sh` printed here: each run's journal came out of a receipt that verified."""
    assert RESULTS["checks_sha256"] == hashlib.sha256(CHECKS).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", RESULTS["image_id"])
    assert {r["fixture"] for r in RESULTS["runs"]} >= {"honest", "wrong"}
    for run in RESULTS["runs"]:
        assert run["verified"] is True and run["dev_mode"] is False
        assert run["journal"] == REF.journal(CHECKS, _fixture(run["fixture"])).hex()
        assert run["prove_seconds"] > 0 and run["receipt_bytes"] > 0 and run["prover_max_rss_kb"] > 0


def test_the_experiment_is_in_no_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["src/knos"]' in text
    assert "experiments" not in text
    assert not (ROOT / "src" / "knos" / "judge_proof").exists()


def test_the_document_states_what_was_measured():
    doc = (ROOT / "docs" / "ATTESTOR.md").read_text(encoding="utf-8")
    flat = " ".join(doc.split())
    assert RESULTS["image_id"] in doc
    for run in RESULTS["runs"]:
        assert f"{run['receipt_bytes']:,}" in doc, run["fixture"]
        assert f"{run['prove_seconds']:.0f} s" in doc, run["fixture"]
    assert "No on-chain verifier is deployed" in flat
    assert "experiments/judge_proof" in doc


def test_knos_does_not_call_its_own_judge_attested():
    """The word is for a level no judge of Knos's has: the document may name the level, never claim it."""
    doc = " ".join((ROOT / "docs" / "ATTESTOR.md").read_text(encoding="utf-8").split())
    assert "no judge of Knos's is attested" in doc
    for claim in ("Knos's judge is attested", "the judge is attested", "an attested judge runs", "attested by Knos"):
        assert claim not in doc
