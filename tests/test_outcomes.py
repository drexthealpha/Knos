"""examples/outcomes/: three outcomes that are not a merged pull request (a labelled dataset, a transformation, a
reproduced result), each a black-box acceptance bundle beside the naive check it replaces. Every submission goes
through the real `knos proof judge`: the honest one is accepted by both, the cheating one is accepted by the naive
check (in-process) and refused by the black-box suite. docs/OUTCOMES.md says what each suite cannot check."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knos import judge, ledger, terms
from knos.cli import main as knos

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "outcomes"
SUITE, NAIVE = "1", "2"          # the bundle that is paid on, and the visible check kept beside it


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    kept, sys.dont_write_bytecode = sys.dont_write_bytecode, True       # a __pycache__ in a bundle would change its hash
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = kept
    return mod


ev = _load("outcomes_evaluation", EXAMPLES / "evaluation.py")
NAMES = sorted(ev.EXAMPLES)
CHEATS = [(name, ev.EXAMPLES[name][1]) for name in NAMES]


def judged(tmp: Path, name: str, folder: str | None, issue: str) -> dict:
    """`knos proof judge` on base/ with the submission's files laid over it: {"accepted", "output", "assurance"}."""
    base, pr = tmp / "base", tmp / "pr"
    for tree in (base, pr):
        shutil.copytree(EXAMPLES / name / "base", tree)
    if folder:
        shutil.copytree(EXAMPLES / name / folder, pr, dirs_exist_ok=True)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = knos(["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", issue, "--evidence", str(tmp / "ev.json")])
    verdict = json.loads((tmp / "ev.json").read_text(encoding="utf-8")) if (tmp / "ev.json").is_file() else {}
    return {"accepted": rc == 0, "output": out.getvalue(), "assurance": verdict.get("assurance"), "verdict": verdict}


class _Direct:
    """`subprocess` for a bundle's blackbox.py when a test runs that file's own functions: "$KNOS_RUN python3 ..."
    becomes this interpreter in the submission's tree. No sandbox, so only for reading what the suite says; whether a
    submission is accepted is always asked of the judge."""
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, tree: Path):
        self.tree = tree

    def run(self, argv, **kw):
        return subprocess.run([sys.executable, *argv[2:]], cwd=self.tree, **kw)


def why(tmp: Path, name: str, folder: str, monkeypatch) -> str:
    """What the black-box suite prints about a submission. The judge's verdict keeps the suite's verdict and not its
    words, so the words are read here from the suite's own code."""
    tree = tmp / "said"
    shutil.copytree(EXAMPLES / name / "base", tree)
    shutil.copytree(EXAMPLES / name / folder, tree, dirs_exist_ok=True)
    bundle = tree / ".knos" / "acceptance" / SUITE
    monkeypatch.setenv("KNOS_RUN", "knos-run")
    monkeypatch.syspath_prepend(str(bundle))                      # blackbox.py imports the gen.py beside it
    monkeypatch.delitem(sys.modules, "gen", raising=False)
    mod = _load(f"outcomes_blackbox_{name.replace('-', '_')}", bundle / "blackbox.py")
    mod.subprocess = _Direct(tree)
    try:
        if hasattr(mod, "check"):
            return "\n".join(mod.check())
        tables = [mod.gen.tables(mod.SEED + n) for n in range(mod.CASES)]
        return next((w for w in (mod.wrong(t, mod.transform(t)) for t in tables) if w), "")
    except SystemExit as stop:
        return str(stop.code)
    finally:
        sys.modules.pop("gen", None)


def test_there_are_three_outcomes_and_each_has_the_same_layout():
    assert NAMES == ["data-labelling", "data-transformation", "reproducible-research"]
    for name in NAMES:
        root = EXAMPLES / name
        for part in ("README.md", "terms.json", "evaluations.jsonl", "base/.knos/proof.toml", "solution", ev.EXAMPLES[name][1],
                     f"base/.knos/acceptance/{SUITE}/blackbox.py", f"base/.knos/acceptance/{NAIVE}/test_visible.py"):
            assert (root / part).exists(), f"{name}/{part}"


@pytest.mark.parametrize("name", NAMES)
def test_the_suite_is_black_box_by_the_judges_own_test_and_the_naive_check_is_not(name):
    base = EXAMPLES / name / "base"
    cfg = judge.proof_config((base / ".knos" / "proof.toml").read_text(encoding="utf-8"))
    files = lambda issue: {p.name: p.read_bytes() for p in (base / ".knos" / "acceptance" / issue).iterdir() if p.is_file()}  # noqa: E731
    assert judge.black_box(files(SUITE), cfg) == ""
    assert judge.black_box(files(NAIVE), cfg) != ""
    assert judge.runner_of(base, {**cfg, "issue": SUITE}) == "blackbox" and judge.runner_of(base, {**cfg, "issue": NAIVE}) == "python"


@pytest.mark.parametrize("name", NAMES)
def test_the_starting_point_is_paid_by_neither(name, tmp_path):
    for issue in (SUITE, NAIVE):
        (tmp_path / issue).mkdir()
        assert not judged(tmp_path / issue, name, None, issue)["accepted"]


@pytest.mark.skipif(os.name == "nt", reason="the suites run `$KNOS_RUN python3 ...`: the judge's machine is Linux or macOS (prove.yml's is ubuntu-latest)")
@pytest.mark.parametrize("name", NAMES)
def test_the_honest_submission_is_accepted_black_box(name, tmp_path):
    got = judged(tmp_path, name, "solution", SUITE)
    assert got["accepted"], got["output"]
    assert got["assurance"] == "black-box"


@pytest.mark.parametrize("name", NAMES)
def test_the_honest_submission_is_accepted_in_process(name, tmp_path):
    got = judged(tmp_path, name, "solution", NAIVE)
    assert got["accepted"], got["output"]
    assert got["assurance"] == "in-process"


@pytest.mark.parametrize("name,cheat", CHEATS)
def test_the_cheat_passes_the_naive_check(name, cheat, tmp_path):
    got = judged(tmp_path, name, cheat, NAIVE)
    assert got["accepted"], got["output"]


REASONS = {"data-labelling": ("accuracy:", "floor:", "leakage:"), "data-transformation": ("row conservation:",),
           "reproducible-research": ("computed:",)}      # a pasted number reproduces itself: only moving the input shows it


@pytest.mark.parametrize("name,cheat", CHEATS)
def test_the_cheat_is_refused_by_the_black_box_suite_and_the_suite_says_why(name, cheat, tmp_path, monkeypatch):
    got = judged(tmp_path, name, cheat, SUITE)
    assert not got["accepted"], got["output"]
    assert got["assurance"] == "black-box"
    said = why(tmp_path, name, cheat, monkeypatch)
    for reason in REASONS[name]:
        assert reason in said, (reason, said)
    assert why(tmp_path / "honest", name, "solution", monkeypatch) == ""


def test_a_transformation_that_loses_a_cent_passes_the_example_and_fails_reconciliation(tmp_path, monkeypatch):
    for issue in (SUITE, NAIVE):
        (tmp_path / issue).mkdir()
    assert judged(tmp_path / NAIVE, "data-transformation", "near_misses/float_cents", NAIVE)["accepted"]
    got = judged(tmp_path / SUITE, "data-transformation", "near_misses/float_cents", SUITE)
    assert not got["accepted"], got["output"]
    assert "reconciliation: gross adds up to" in why(tmp_path, "data-transformation", "near_misses/float_cents", monkeypatch)


def test_the_examples_data_are_what_their_generators_and_solutions_make(tmp_path):
    """Nothing committed is unexplained: the labelling data come from gen.py's seed, the honest labels from label.py,
    the worked ledger from the reference, and the claimed result from analysis.py."""
    lab = EXAMPLES / "data-labelling"
    made = tmp_path / "bundle"
    shutil.copytree(lab / "base" / ".knos" / "acceptance" / SUITE, made)
    _load("labelling_gen", made / "gen.py").main(tmp_path)
    for path in ("data/items.csv", "data/examples.csv"):
        assert (tmp_path / path).read_bytes() == (lab / "base" / path).read_bytes(), path
    assert (made / "gold.csv").read_bytes() == (lab / "base" / ".knos" / "acceptance" / SUITE / "gold.csv").read_bytes()
    shown = {line.split(",")[0] for line in (tmp_path / "data" / "examples.csv").read_text(encoding="utf-8").splitlines()[1:]}
    gold = {line.split(",")[0] for line in (made / "gold.csv").read_text(encoding="utf-8").splitlines()[1:]}
    assert len(shown) == 40 and len(gold) == 120 and not shown & gold        # the gold items were never shown
    shutil.copy(lab / "solution" / "label.py", tmp_path / "label.py")
    subprocess.run([sys.executable, "label.py"], cwd=tmp_path, check=True)
    assert (tmp_path / "labels.csv").read_bytes() == (lab / "solution" / "labels.csv").read_bytes()

    tr = EXAMPLES / "data-transformation" / "base"
    gen = _load("transformation_gen", tr / ".knos" / "acceptance" / SUITE / "gen.py")
    rows = lambda f: [line.split(",") for line in (tr / "examples" / f).read_text(encoding="utf-8").splitlines()[1:]]  # noqa: E731
    want = gen.ledger({"charges": rows("charges.csv"), "refunds": rows("refunds.csv")})
    assert [[k, *map(str, v)] for k, v in sorted(want.items())] == rows("expected_ledger.csv")
    assert gen.tables(7) == gen.tables(7) != gen.tables(8)
    assert all(int(float(gen.money(c)) * 100) != c for c in gen.AWKWARD)       # each really loses a cent as a double

    rr = EXAMPLES / "reproducible-research"
    data = (rr / "base" / "data" / "trial.csv").read_bytes()
    assert data == (rr / "base" / ".knos" / "acceptance" / SUITE / "trial.csv").read_bytes()
    claim = json.loads((rr / "solution" / "RESULT.json").read_text(encoding="utf-8"))
    got = subprocess.run([sys.executable, "analysis.py", str(claim["seed"])], input=data, capture_output=True, cwd=rr / "solution", check=True)
    assert float(got.stdout.decode()) == claim["estimate"]


@pytest.mark.parametrize("name", NAMES)
def test_the_terms_fix_the_suite_and_the_same_evaluation_feeds_the_meter(name):
    """terms.json and evaluations.jsonl are what evaluation.py computes now: the terms carry the bundle's hash, the
    policy of each evaluation is the hash of those terms, and the line is one the meter's ledger reads."""
    root = EXAMPLES / name
    doc = json.loads((root / "terms.json").read_text(encoding="utf-8"))
    assert doc == ev.terms_file(name)
    assert doc["terms"]["accept"] == judge.checks_hash(root / "base" / ".knos" / "acceptance" / SUITE)
    assert terms.terms_hash(terms.parse(doc["terms_json"])) == doc["terms_hash"]
    assert (root / "evaluations.jsonl").read_text(encoding="utf-8") == ev.lines(name)
    honest, cheat = (ledger.parse(line) for line in (root / "evaluations.jsonl").read_text(encoding="utf-8").splitlines())
    assert honest.accepted and not cheat.accepted and honest.value == ev.EXAMPLES[name][0] and cheat.value == 0
    assert honest.policy == cheat.policy == doc["terms_hash"] and honest.order == cheat.order and honest.milestone == 0
    assert honest.id != cheat.id                                   # another artifact is another evaluation
    assert honest.id == ledger.eval_id(bytes.fromhex(honest.order), honest.artifact, bytes.fromhex(honest.policy), 0)
    assert honest.audience().startswith(f"knosm:eval:{ev.BUYER}:{ev.SELLER}:{honest.order}:{honest.artifact}:{honest.policy}:0:1:")


def test_the_document_lists_each_outcome_and_says_what_is_not_built():
    text = (ROOT / "docs" / "OUTCOMES.md").read_text(encoding="utf-8")
    assert "each domain needs its own acceptance model" in text.lower()
    for name in NAMES:
        assert f"../examples/outcomes/{name}/" in text
    assert "Support-ticket resolution" in text and "not built" in text
