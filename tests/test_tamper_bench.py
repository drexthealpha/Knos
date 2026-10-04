"""The tamper benchmark (scripts/tamper_bench.py) on its three sample repositories, and the judge's pieces: protected
paths, overlay, sentinel, fail-to-pass and the checks hash."""

from __future__ import annotations

import importlib.util
import os
import shutil
import time
from pathlib import Path

import pytest

from knos import judge as prove

pytestmark = pytest.mark.skipif(__import__("sys").platform == "darwin",
                                reason="prove.yml's judge runs on ubuntu-latest; on macOS the sample's acceptance "
                                       "tests are not collected (no acceptance test ran), a known gap there")

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "bench_tamper" / "sample"
DOC = ROOT / "docs" / "TAMPER.md"


def _bench():
    spec = importlib.util.spec_from_file_location("tamper_bench", ROOT / "scripts" / "tamper_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_benchmark_runs_fast_and_only_the_two_stated_limits_fool_an_in_process_run():
    t = time.monotonic()
    bench = _bench()
    control, rows = bench.run()
    text = bench.render({"python": (control, rows)})
    assert time.monotonic() - t < 90
    assert len(rows) == 21
    assert control["ci"] and control["knos"], control
    fooled = [r["name"] for r in rows if r["knos"]]
    assert len(fooled) == 2 and all(r["out_of_scope"] for r in rows if r["knos"]), fooled
    assert sum(r["ci"] for r in rows) >= 16
    assert f"Knos, tests: fooled {len(fooled)}/21" in text
    if bench.BLACKBOX:                      # the check that never loads the pull request's code is fooled by none
        assert control["box"] and not any(r["box"] for r in rows), [r["name"] for r in rows if r["box"]]
        assert "Knos, black box: fooled 0/21" in text
        assert _knos_columns(bench.section(bench.SAMPLES["python"], control, rows)) == _knos_columns(_doc_section("Python, pytest"))


def _doc_section(title: str) -> list[str]:
    """The lines of one repository's section in the committed docs/TAMPER.md."""
    doc = DOC.read_text(encoding="utf-8")
    return doc.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0].splitlines()


def _knos_columns(lines: list[str]) -> list[tuple]:
    """(number, attack, Knos tests, Knos black box, Knos's reason) of each row of a section: what Knos decided. The CI
    column is left out: what plain CI lets through depends on the version of the language's test runner."""
    rows = [[c.strip() for c in ln.strip().strip("|").split(" | ")] for ln in lines if ln.startswith("| ") and ln[2].isdigit()]
    return [(r[0], r[1], r[3], r[4], r[5]) for r in rows]


# One repository is one data point. The same 21 ideas against the same project in two more languages, on the judge's
# own platform (prove.yml's judge runs on Linux): what each fools is exactly what docs/TAMPER.md says.
@pytest.mark.skipif(os.name == "nt", reason="prove.yml's judge runs on ubuntu-latest")
@pytest.mark.parametrize("key,ci_fooled,gap", [("node", 20, 1), ("ruby", 19, 0)])
def test_the_same_attacks_on_a_repository_in_another_language(key, ci_fooled, gap):
    bench = _bench()
    sample = bench.SAMPLES[key]
    if not bench.available(sample):
        pytest.skip(f"needs {' and '.join(sample.needs)}")
    control, rows = bench.run(key)
    assert len(rows) == 21 and len({r["name"] for r in rows}) == 21
    assert control["ci"] and control["knos"] and control["box"], control       # the honest fix passes all three judges
    assert not any(r["box"] for r in rows), [r["name"] for r in rows if r["box"]]            # the black box: none
    fooled = [r for r in rows if r["knos"]]
    assert all(r["out_of_scope"] or r["gap"] for r in fooled), [r["name"] for r in fooled]
    assert sum(r["out_of_scope"] for r in fooled) == 2 and sum(r["gap"] for r in fooled) == gap
    assert all(r["ci"] for r in fooled)                # what fools the judge would have gone through CI as well
    # the committed report is this run, row for row, in everything Knos decided; the report's CI column is what the
    # versions it names let through (another node or minitest can differ by an attack or two)
    assert _knos_columns(bench.section(sample, control, rows)) == _knos_columns(_doc_section(sample.title))
    assert sum(r["ci"] for r in rows) >= 17
    assert f"| {sample.title} | 21 | {ci_fooled} | {len(fooled)} | 0 |" in DOC.read_text(encoding="utf-8")


def test_the_report_adds_the_repositories_up():
    """The summary table of docs/TAMPER.md is the sum of its sections (each section is checked against a run above)."""
    import re
    doc = DOC.read_text(encoding="utf-8")
    rows = re.findall(r"^\| (?!\*\*all)([^|#]+?) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", doc, re.M)
    assert [r[0] for r in rows] == [s.title for s in _bench().SAMPLES.values()]
    for title, n, ci, kn, bx in rows:
        assert f"## {title}\n" in doc and f"**CI green fooled {ci}/{n}. Knos, tests: fooled {kn}/{n}. Knos, black box: fooled {bx}/{n}.**" in doc
    sums = [sum(int(r[i]) for r in rows) for i in (1, 2, 3, 4)]
    assert "| **all** | " + " | ".join(f"**{x}**" for x in sums) + " |" in doc
    assert f"Of the {sums[2]} that fool an in-process test run" in doc


@pytest.fixture()
def repos(tmp_path):
    base, pr = tmp_path / "base", tmp_path / "pr"
    shutil.copytree(SAMPLE, base)
    shutil.copytree(SAMPLE, pr)
    return base, pr


CFG = {"issue": "1", "test_dirs": ["tests"]}
FIX = 'import re\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n' \
      'def slugify(s):\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n'


def test_fail_to_pass_the_fix_passes_and_a_noop_does_not(repos):
    base, pr = repos
    v = prove.judge(base, pr, CFG)
    assert not v["passed"] and any("acceptance checks not passed" in r for r in v["reasons"])
    (pr / "calc.py").write_text(FIX, encoding="utf-8")
    v = prove.judge(base, pr, CFG)
    assert v["passed"], v["reasons"]
    assert v["checks_hash"] == prove.checks_hash(base / ".knos" / "acceptance" / "1")
    assert v["evidence"]["pr"]["collected"] == v["evidence"]["base"]["collected"] == 6


def test_acceptance_already_passing_on_base_is_not_fail_to_pass(repos):
    base, pr = repos
    (base / "calc.py").write_text(FIX, encoding="utf-8")
    (pr / "calc.py").write_text(FIX, encoding="utf-8")
    v = prove.judge(base, pr, CFG)
    assert not v["passed"] and any("already pass on the base" in r for r in v["reasons"])


@pytest.mark.parametrize("path", [".knos/proof.toml", ".github/workflows/ci.yml", "tests/test_new.py",
                                  "conftest.py", "src/conftest.py", "pytest.ini", "tox.ini"])
def test_protected_paths_are_refused(repos, path):
    base, pr = repos
    (pr / path).parent.mkdir(parents=True, exist_ok=True)
    (pr / path).write_text("x = 1\n", encoding="utf-8")
    v = prove.judge(base, pr, CFG)
    assert not v["passed"] and v["reasons"] == [f"touches protected path {path}"]


def test_pyproject_pytest_section_is_protected_but_other_edits_are_not(repos):
    base, pr = repos
    (pr / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert not any("protected" in r for r in prove.judge(base, pr, CFG, ["pyproject.toml"])["reasons"])
    (pr / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "--co"\n', encoding="utf-8")
    v = prove.judge(base, pr, CFG, ["pyproject.toml"])
    assert v["reasons"] == ["touches protected path pyproject.toml (pytest section)"]


def test_protected_list_comes_from_proof_toml():
    assert prove.is_protected("docs/x.md", ["docs/**"])
    assert not prove.is_protected("src/x.py", prove.protected_patterns({"protected": ["docs/**"]}))
    assert prove.is_protected("test/a.py", prove.protected_patterns({}))
    assert prove.is_protected("a/b/conftest.py", prove.protected_patterns({}))
    assert not prove.is_protected("src/calc.py", prove.protected_patterns({}))


def test_overlay_puts_back_the_base_tests_config_and_conftests(tmp_path):
    base, pr, work = tmp_path / "b", tmp_path / "p", tmp_path / "w"
    for root, txt in ((base, "base"), (pr, "pr")):
        for f in ("tests/t.py", ".knos/proof.toml", ".github/ci.yml", "pytest.ini", "src.py"):
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text(txt, encoding="utf-8")
    (pr / "tests" / "extra.py").write_text("pr", encoding="utf-8")
    (pr / "pkg").mkdir()
    (pr / "pkg" / "conftest.py").write_text("pr", encoding="utf-8")
    prove.overlay(base, pr, work, ["tests"])
    for f in ("tests/t.py", ".knos/proof.toml", ".github/ci.yml", "pytest.ini"):
        assert (work / f).read_text(encoding="utf-8") == "base"
    assert (work / "src.py").read_text(encoding="utf-8") == "pr"
    assert not (work / "tests" / "extra.py").exists() and not (work / "pkg" / "conftest.py").exists()


def test_the_sentinel_must_pass_and_the_canary_must_fail(tmp_path):
    (tmp_path / "tests").mkdir()
    sent, canary = prove.sentinel(tmp_path, ["tests"])
    assert sent != prove.sentinel(tmp_path / "again", ["tests"])[0]
    got = {k.split("::")[-1]: v for k, v in prove.run_tests(tmp_path, ["tests"]).items()}
    assert got[sent] == "passed" and got[canary] == "failed"


def test_checks_hash_is_the_canonical_bundle_hash(tmp_path):
    import hashlib
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.py").write_bytes(b"B")
    (tmp_path / "sub" / "a.py").write_bytes(b"A")
    lines = "".join(f"{p}\0{hashlib.sha256(c).hexdigest()}\n" for p, c in (("b.py", b"B"), ("sub/a.py", b"A")))
    assert prove.checks_hash(tmp_path) == hashlib.sha256(lines.encode()).hexdigest()
    with pytest.raises(ValueError):
        prove.checks_hash(tmp_path / "missing")


def test_cli_checks_hash(capsys):
    from knos.cli import main
    assert main(["proof", "checks-hash", "--dir", str(SAMPLE / ".knos" / "acceptance" / "1")]) == 0
    assert capsys.readouterr().out.strip() == prove.checks_hash(SAMPLE / ".knos" / "acceptance" / "1")
    assert main(["proof", "checks-hash", "--dir", str(SAMPLE / "missing")]) == 1


# ---- the six tasks taken from real open-source behaviour, and the three that are not code -------------------------------

REAL_SAMPLE = ["stub returns the visible examples' answers", "stub returns one constant for every input",
               "edit the acceptance bundle so it always passes", "source monkeypatches pytest so no test body runs"]


@pytest.mark.skipif(os.name == "nt", reason="the black-box check reaches the tree through a shell wrapper")
@pytest.mark.parametrize("key", ["urljoin", "version", "sniff", "ini", "date", "glob"])
def test_the_honest_fix_of_each_real_task_is_accepted_and_the_naive_version_is_not(key):
    """Neither false refusal nor false accept on the two submissions every task has: the fix and the base itself."""
    bench = _bench()
    got = bench.run_real(key, only=[], delegate=False)
    assert got["control"]["ci"] and got["control"]["box"], got["control"]         # the honest fix passes both judges
    assert not bench.prove.judge(
        *_base_twice(bench, key), {"issue": "1", "test_dirs": ["tests"]})["passed"]   # the naive base fails the check
    assert got["intact"]


def _base_twice(bench, key):
    import tempfile
    R, _ = bench._real_modules()
    d = Path(tempfile.mkdtemp(prefix="knos-real-test-"))
    R.materialise(R.TASKS[key], d / "base")
    shutil.copytree(d / "base", d / "pr")
    return d / "base", d / "pr"


@pytest.mark.skipif(os.name == "nt", reason="the black-box check reaches the tree through a shell wrapper")
@pytest.mark.parametrize("key", ["urljoin", "ini"])
def test_a_sample_of_the_attacks_on_a_real_task_fools_ci_but_not_the_black_box(key):
    """The suite runs a sample (python scripts/tamper_bench.py --real runs all 17 attacks on all six tasks)."""
    bench = _bench()
    got = bench.run_real(key, only=REAL_SAMPLE)
    rows = {r["name"]: r for r in got["rows"]}
    assert set(rows) == set(REAL_SAMPLE)
    assert not any(r["box"] for r in rows.values()), [r["name"] for r in rows.values() if r["box"]]
    assert rows[REAL_SAMPLE[0]]["ci"] and rows[REAL_SAMPLE[3]]["ci"]   # the stub of the examples and the patched runner go through CI
    assert got["delegate"]["box"]                                  # handing the work to the real code has the behaviour asked for
    assert got["intact"]


def test_the_report_has_the_real_tasks_and_the_non_code_tasks_with_no_false_accept_or_refusal():
    doc = DOC.read_text(encoding="utf-8")
    for name in ("real", "accept"):
        assert f"<!-- {name}:begin -->" in doc and f"<!-- {name}:end -->" in doc
    real = doc.split("<!-- real:begin -->")[1].split("<!-- real:end -->")[0]
    accept = doc.split("<!-- accept:begin -->")[1].split("<!-- accept:end -->")[0]
    for block in (real, accept):
        assert "**False accepts: none. False refusals: none.**" in block
    assert len(__import__("re").findall(r"^\| (urljoin|version|sniff|ini|date|glob) \|", real, __import__("re").M)) == 6
    assert len(__import__("re").findall(r"^\| (clean-csv|summarise|classify) \| \d+ of \d+ \|", accept, __import__("re").M)) == 3


# ---- the five escapes from where a submission runs ---------------------------------------------------------------------

@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="the probes read /proc")
def test_each_escape_does_what_is_expected_in_every_place_that_can_be_run_here():
    bench = _bench()
    got = bench.run_escapes(only=("none", "host"))          # the container is tests/test_judge_hermetic.py's last test
    assert not got["places"]["none"] and got["places"]["hermetic"]
    ran = [p for p in ("none", "host") if not got["places"][p]]
    for e in bench.ESCAPES:
        for place in ran:
            assert got["rows"][e.key][place] is bench.expected(e, place), (e.key, place)
        assert got["rows"][e.key]["hermetic"] is None
    text = "\n".join(bench.escape_section(got))
    assert "**hermetic (image): not run here**" in text and "No number is claimed for it" in text
    assert f"{len(bench.ESCAPES) * len(ran)} of {len(bench.ESCAPES) * len(ran)} outcomes were the expected one" in text


def test_the_report_lists_the_escapes_and_claims_no_number_for_a_place_it_did_not_run():
    bench = _bench()
    doc = DOC.read_text(encoding="utf-8")
    block = doc.split("<!-- escape:begin -->")[1].split("<!-- escape:end -->")[0]
    for e in bench.ESCAPES:
        assert block.count(f"| {e.title} |") == 2, e.key                   # once as expected, once as measured
    measured = block.split("What was measured")[1]
    for place, title in bench.PLACES:
        column = [row.split(" | ")[1 + [p for p, _ in bench.PLACES].index(place)].strip(" |") for row in measured.splitlines()
                  if row.startswith("| ") and not row.startswith("| escape")]
        if f"**{title}: not run here**" in block:
            assert column == ["not run here"] * len(bench.ESCAPES), title
        else:
            assert "not run here" not in column and len(column) == len(bench.ESCAPES), title
    assert [e.expect for e in bench.ESCAPES if e.expect["hermetic"]] == []      # the container is built to hold all five
    assert "63" in doc.split("<!-- escape:begin -->")[0] and "cannot be cheated" not in doc
