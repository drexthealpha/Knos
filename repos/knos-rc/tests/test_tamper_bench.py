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
DOC = ROOT / "docs" / "reference" / "TAMPER.md"


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
    """The lines of one repository's section in the committed docs/reference/TAMPER.md."""
    doc = DOC.read_text(encoding="utf-8")
    return doc.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0].splitlines()


def _knos_columns(lines: list[str]) -> list[tuple]:
    """(number, attack, Knos tests, Knos black box, Knos's reason) of each row of a section: what Knos decided. The CI
    column is left out: what plain CI lets through depends on the version of the language's test runner."""
    rows = [[c.strip() for c in ln.strip().strip("|").split(" | ")] for ln in lines if ln.startswith("| ") and ln[2].isdigit()]
    return [(r[0], r[1], r[3], r[4], r[5]) for r in rows]


# One repository is one data point. The same 21 ideas against the same project in two more languages, on the judge's
# own platform (prove.yml's judge runs on Linux): what each fools is exactly what docs/reference/TAMPER.md says.
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
    """The summary table of docs/reference/TAMPER.md is the sum of its sections (each section is checked against a run above)."""
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


@pytest.mark.parametrize("path, code", [(".knos/proof.toml", "terms"), (".github/workflows/ci.yml", "workflow"),
                                        ("tests/test_calc.py", "protected_test_edited")])
def test_protected_paths_are_refused(repos, path, code):
    base, pr = repos
    (pr / path).parent.mkdir(parents=True, exist_ok=True)
    (pr / path).write_text("x = 1\n", encoding="utf-8")
    v = prove.judge(base, pr, CFG)
    assert not v["passed"] and v["verdict"] == "rejected" and v["reasons"] == [f"touches protected path {path}: {prove.REFUSALS[code]}"]
    assert prove.classify_path(path, CFG) == f"refused:{code}"


def test_a_deleted_protected_test_is_refused_and_named(repos):
    base, pr = repos
    (pr / "tests" / "test_calc.py").unlink()
    v = prove.judge(base, pr, CFG)
    assert v["reasons"] == [f"touches protected path tests/test_calc.py: {prove.REFUSALS['protected_test_deleted']}"]
    assert prove.classify_path("tests/test_calc.py", CFG, "removed") == "refused:protected_test_deleted"


RAISES = "raise SystemExit('a file the pull request added was loaded')\n"


@pytest.mark.parametrize("paths, note", [
    (["tests/test_new.py"], "contributor tests: 1 file, not counted"),
    (["tests/deep/test_a.py", "tests/deep/data.json"], "contributor tests: 2 files, not counted"),
    (["conftest.py"], "test configuration: 1 file changed, not counted (the suite ran from the base's copy)"),
    (["tests/conftest.py", "src/conftest.py", "pytest.ini", "tox.ini"],
     "test configuration: 4 files changed, not counted (the suite ran from the base's copy)")])
def test_an_added_test_or_test_configuration_is_allowed_and_cannot_decide(repos, paths, note):
    """Each added file ends the process when it is loaded, and pytest.ini and tox.ini are not even valid: were any of
    them in the tree the suite runs in, the fix could not be accepted."""
    base, pr = repos
    (pr / "calc.py").write_text(FIX, encoding="utf-8")
    for path in paths:
        (pr / path).parent.mkdir(parents=True, exist_ok=True)
        (pr / path).write_text(RAISES, encoding="utf-8")
        assert prove.classify_path(path, CFG, "added") == "allowed_not_counted"
    v = prove.judge(base, pr, CFG)
    assert v["passed"] and v["verdict"] == "accepted" and v["notes"] == [note] and note in v["reason"], v
    assert v["evidence"]["pr"]["collected"] == v["evidence"]["base"]["collected"] == 6      # the base's tests, no more
    counted = v["evidence"]["contributor_tests"]["files"] + v["evidence"]["test_configuration"]["files"]
    assert sorted(counted) == sorted(paths) and v["evidence"]["contributor_tests"]["counted"] is False
    # and without the fix the same files buy nothing
    (pr / "calc.py").write_text((base / "calc.py").read_text(encoding="utf-8"), encoding="utf-8")
    assert prove.judge(base, pr, CFG)["verdict"] == "rejected"


def test_the_tree_the_suite_runs_in_has_the_base_copy_of_every_protected_path(repos, tmp_path):
    """File by file: after overlay, no protected path of the work tree differs from the base's, whatever was added."""
    base, pr = repos
    added = ["tests/test_new.py", "tests/conftest.py", "tests/plugin.py", "tests/sitecustomize.py", "tests/x.pth",
             "tests/__init__.py", "tests/calc.py", "conftest.py", "pkg/conftest.py", "pytest.ini", "tox.ini", "setup.cfg",
             ".knos/acceptance/1/conftest.py", ".github/workflows/new.yml"]
    for path in added:
        (pr / path).parent.mkdir(parents=True, exist_ok=True)
        (pr / path).write_text(RAISES, encoding="utf-8")
    (pr / "tests" / "test_calc.py").write_text("def test_easy():\n    assert True\n", encoding="utf-8")
    (pr / "calc.py").write_text(FIX, encoding="utf-8")
    work = tmp_path / "work"
    prove.overlay(base, pr, work, CFG["test_dirs"])
    files = lambda root: {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}  # noqa: E731
    was, now = files(base), files(work)
    assert not [a for a in added if a in now and a not in was]             # none of the added files is there
    assert "pytest.ini" in was and now["pytest.ini"] == was["pytest.ini"]      # and one the base has is the base's again
    assert set(now) == set(was) and {k for k in now if now[k] != was[k]} == {"calc.py"}     # only the source is the PR's
    pats = prove.protected_patterns(CFG)
    assert all(now[k] == was[k] for k in now if prove.is_protected(k, pats))
    for path in added:                                                      # and the rule says the same of each, alone
        word = prove.classify_path(path, CFG, "added")
        assert word == ("refused:terms" if path.startswith(".knos/") else "refused:workflow" if path.startswith(".github/")
                        else "allowed" if path == "setup.cfg" else "allowed_not_counted"), path


def test_classify_path_is_the_rule_for_one_path_in_every_language():
    c = prove.classify_path
    assert c("src/calc.py") == c("README.md", {}) == c("package.json", {"runner": "node"}) == "allowed"
    assert c("tests/test_x.py") == "refused:protected_test_edited"         # not known to be new: the strict answer
    assert c("./tests/test_x.py", None, "added") == c("tests\\test_x.py", None, "added") == "allowed_not_counted"
    assert c("lib/a.test.js", {"runner": "node"}, "added") == c("w_test.go", {"runner": "go"}, "added") == "allowed_not_counted"
    assert c("Rakefile", {"runner": "ruby"}) == c("test/test_helper.rb", {"runner": "ruby"}, "added") == "allowed_not_counted"
    assert c("test/test_helper.rb", {"runner": "ruby"}) == "refused:protected_test_edited"
    assert c(".cargo/config.toml", {"runner": "rust"}) == "allowed_not_counted"
    assert c("docs/x.md", {"protected": ["docs/**"]}, "added") == "refused:not_from_base"   # a funder's own list: not overlaid
    assert c(".github/workflows/ci.yml", None, "added") == "refused:workflow" and c(".knos/proof.toml") == "refused:terms"
    assert set(prove.REFUSALS) == {"terms", "workflow", "not_from_base", "scripts", "protected_test_edited", "protected_test_deleted"}
    with pytest.raises(ValueError):
        c("a.py", {"runner": "cobol"})
    with pytest.raises(ValueError):
        c("a.py", None, "renamed")


def test_package_json_scripts_are_refused_only_where_the_funders_own_command_decides(tmp_path):
    base, pr = tmp_path / "base", tmp_path / "pr"
    for root, script in ((base, "node --test"), (pr, "true")):
        root.mkdir()
        (root / "package.json").write_text('{"name": "x", "scripts": {"test": "%s"}}' % script, encoding="utf-8")
    kinds = lambda runner: prove.classify(base, pr, ["package.json"], {}, runner, ["test"])  # noqa: E731
    assert kinds("command")["refused"] == kinds("blackbox")["refused"] == [("package.json (scripts)", prove.REFUSALS["scripts"])]
    assert kinds("node") == {"refused": [], "contributor": [], "config": []}        # node --test never reads them
    (pr / "package.json").write_text('{"name": "y", "scripts": {"test": "node --test"}}', encoding="utf-8")
    assert not kinds("command")["refused"]                                          # another field: the source's own


def test_a_run_that_could_not_decide_is_insufficient_evidence_never_rejected_or_accepted(repos, monkeypatch):
    from knos import ids
    base, pr = repos
    (pr / "calc.py").write_text(FIX, encoding="utf-8")
    v = prove.judge(base, pr, {**CFG, "issue": "no such issue"})            # nothing to run: no verdict on the work
    assert v["verdict"] == "insufficient_evidence" and not v["passed"]
    v = prove.judge(base, pr, CFG, sandbox="require") if not prove.sandbox_available() else None
    assert v is None or (v["verdict"] == "insufficient_evidence" and not v["passed"])
    monkeypatch.setitem(prove._RUN, "python", lambda *a, **k: prove.Run(None, log="timed out"))   # the suite never reported
    v = prove.judge(base, pr, CFG, sandbox="off")
    assert v["verdict"] == "insufficient_evidence" and not v["passed"] and v["evidence"]["undecided"] is True
    assert v["verdict"] in ids.VERDICTS and "wrote no report" in v["reason"]


def test_pyproject_pytest_section_is_protected_but_other_edits_are_not(repos):
    base, pr = repos
    (pr / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert not any("protected" in r for r in prove.judge(base, pr, CFG, ["pyproject.toml"])["reasons"])
    (pr / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "--co"\n', encoding="utf-8")
    v = prove.judge(base, pr, CFG, ["pyproject.toml"])
    assert v["notes"] == ["test configuration: 1 file changed, not counted (the suite ran from the base's copy)"]
    assert v["evidence"]["test_configuration"]["files"] == ["pyproject.toml (pytest section)"]


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


# ---- honest work: a correct submission must not be refused ---------------------------------------------------------------

def _honest():
    bench = _bench()
    return bench, bench._honest(), bench._real_modules()[0]


def test_the_honest_set_is_fixed_text_for_every_task_and_at_least_thirty_submissions(tmp_path):
    bench, H, R = _honest()
    assert H.count() >= 30
    assert set(H.SLUG) == set(bench.SAMPLES) and all(len(v) >= 3 for v in H.SLUG.values())
    assert len(H.REAL) >= 3 and all((H.HERE / "real" / f"{key}.py").is_file() for key in R.TASKS)
    assert set(H.PLAIN) == set(__import__("acceptance_examples").tasks()) and all(len(v) >= 2 for v in H.PLAIN.values())

    def laid(root: Path) -> dict:
        for key, subs in H.SLUG.items():
            for i, (_, fn) in enumerate(subs):
                fn(root / key / str(i))
        for key, task in R.TASKS.items():
            for i, (_, fn) in enumerate(H.REAL):
                fn(root / key / str(i), task, root / "base")
        for task, subs in H.PLAIN.items():
            for i, (_, source) in enumerate(subs):
                for rel, text in (source().items() if callable(source) else
                                  {str(p.relative_to(source)): p.read_text(encoding="utf-8") for p in sorted(source.rglob("*")) if p.is_file()}.items()):
                    bench._honest()._w(root / task / str(i), rel, text)
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    first, second = laid(tmp_path / "a"), laid(tmp_path / "b")
    assert first == second and len(first) > H.count()                      # nothing in a submission is drawn at random
    names = [n for subs in [*H.SLUG.values(), H.REAL, *H.PLAIN.values()] for n, _ in subs]
    assert H.EXPECTED_REFUSED <= set(names)


@pytest.mark.parametrize("key", ["urljoin", "version", "sniff", "ini", "date", "glob"])
def test_the_other_algorithm_of_each_real_task_answers_as_the_reference_does_on_fixed_draws(key):
    """In this process, on a fixed seed: an honest submission that is wrong would make the honest count a false finding."""
    import json
    import random
    _, H, R = _honest()
    task = R.TASKS[key]
    ns = R._namespace(task)
    theirs: dict = {}
    exec(compile((H.HERE / "real" / f"{key}.py").read_text(encoding="utf-8"), key, "exec"), theirs)   # noqa: S102 - our own text
    rng, cases = random.Random(316), [*ns["FIXED"], *task.known]
    while len(cases) < 600:
        case = ns["gen"](rng)
        if "accept" not in ns or ns["accept"](case):
            cases.append(case)

    def outcome(fn, args):
        try:
            return json.loads(json.dumps(["ok", fn(*args[:R.arity(task)])]))
        except Exception:                                                  # noqa: BLE001 - a refusal is an answer here
            return ["error"]
    assert [c for c in cases if outcome(theirs[task.entry], c) != outcome(ns["ref"], c)] == []


def test_a_sample_whose_delimiter_the_task_does_not_define_is_not_asked():
    """Two delimiters in every line equally often: csv.Sniffer picks one by its own rules, the task names neither."""
    _, _, R = _honest()
    ns = R._namespace(R.TASKS["sniff"])
    assert not ns["accept"](["28,6|c\np,q|869\n\"p|q\"|70,8\n", "|"])
    assert ns["accept"](["a|b\n1|2\n3|4\n", "|"]) and ns["accept"](["name;price\nfoo;1,5\nbar;2,5\n", ";"])


@pytest.mark.skipif(os.name == "nt", reason="the black-box check reaches the tree through a shell wrapper")
def test_honest_submissions_are_accepted_and_one_with_tests_of_its_own_says_they_were_not_counted():
    """A sample of the set through the judges (python scripts/tamper_bench.py --honest runs all of it)."""
    bench, H, _ = _honest()
    rows = bench.run_honest(tasks=("python", "glob", "summarise"))
    assert len(rows) == len(H.SLUG["python"]) + len(H.REAL) + len(H.PLAIN["summarise"])
    assert not H.EXPECTED_REFUSED and len(H.ADDED) >= 6 and H.ADDED < H.WITH_TESTS
    for r in rows:
        judged = [r[j] for j in ("knos", "box") if r[j] is not None]
        assert judged and all(judged), r
        assert r["ci"] in (True, None), r                                   # plain CI accepts every one of them
        if r["name"] in H.WITH_TESTS:
            assert any(n.startswith("contributor tests: ") and n.endswith(", not counted") for n in r["notes"]), r
    n = bench.honest_counts(rows)
    assert n["box"] == (len(rows), len(rows)) and n["knos"] == (len(H.SLUG["python"]),) * 2


@pytest.mark.skipif(os.name == "nt", reason="the black-box check reaches the tree through a shell wrapper")
def test_honest_work_that_changes_the_suite_itself_is_still_refused_by_rule():
    bench, H, _ = _honest()
    rows = bench.run_rule_refused()
    assert len(rows) == len(H.RULE_REFUSED) == 3
    assert all(r["ci"] and r["knos"] is False and r["box"] is False and "touches protected path" in r["why"] for r in rows), rows


@pytest.mark.skipif(os.name == "nt", reason="the black-box check reaches the tree through a shell wrapper")
def test_no_cheat_aimed_at_what_a_pull_request_may_add_is_accepted_and_the_report_says_so():
    bench = _bench()
    control, rows = bench.run_allowed()
    assert control["ci"] and control["knos"] and control["box"] and control["notes"] == ["contributor tests: 1 file, not counted"]
    assert len(rows) >= 12 and not any(r["knos"] or r["box"] for r in rows), rows
    assert {r["word"] for r in rows} == {r["box_word"] for r in rows} == {"rejected"}
    assert sum(bool(r["ci"]) for r in rows) >= 6                            # plain CI is what these fool
    doc = DOC.read_text(encoding="utf-8")
    block = doc.split("<!-- allowed:begin -->")[1].split("<!-- allowed:end -->")[0]
    ci = sum(bool(r["ci"]) for r in rows)
    assert f"**Of {len(rows)} such cheats, CI green accepted {ci}, Knos, tests 0 and Knos, black box 0.**" in block
    assert all(f"| {r['name']} |" in block for r in rows) and "`insufficient_evidence`" in block
    assert bench.place_allowed(doc, block.join(["<!-- allowed:begin -->", "<!-- allowed:end -->"]).split("\n")) == doc


def test_the_report_states_both_rates_with_their_sample_sizes_and_what_is_still_refused():
    import json
    import re
    bench, H, _ = _honest()
    doc = DOC.read_text(encoding="utf-8")
    block = doc.split("<!-- honest:begin -->")[1].split("<!-- honest:end -->")[0]
    assert doc.index("<!-- honest:begin -->") < doc.index("## Python, pytest")       # beside the cheat numbers, not after them
    m = re.search(r"\*\*Honest submissions accepted: Knos, black box (\d+) of (\d+); Knos, tests (\d+) of (\d+); "
                  r"CI green (\d+) of (\d+)\.\*\*", block)
    box, total, tests, tested, ci, ran = (int(x) for x in m.groups())
    assert total == H.count() >= 54 and tested == sum(len(v) for v in H.SLUG.values()) and ci == ran
    assert box == total and tests == tested                                 # every honest submission is accepted
    cheats = bench.cheat_totals(doc)
    assert [b for _, b in cheats][:3] == [63, 102, 25] and cheats[3][1] >= 12 and not any(a for a, _ in cheats)
    assert f"accepted by Knos, black box: {', '.join(f'{a} of {b}' for a, b in cheats)}**" in block
    assert f"{sum(b for _, b in cheats)} cheating submissions and {total} honest ones" in block
    assert f"| **all** | **{total}** | **{ci} of {ran}** | **{tests} of {tested}** | **{box} of {total}** |" in block
    assert "on Knos's own tasks" in block and "nobody outside has run either set" in block
    old = total - sum(1 for r in json.loads((bench.rows_file(DOC)).read_text(encoding="utf-8"))["rows"] if r["name"] in H.ADDED)
    assert old == 48 and f"it now accepts {old} of {old}" in block          # the set of 0.3.16, of which 39 were accepted
    refused = [ln for ln in block.splitlines() if ln.startswith("| ") and "touches protected path" in ln]
    assert len(refused) == len(H.RULE_REFUSED) and all(f"| {n} |" in ln for (n, _), ln in zip(H.RULE_REFUSED, refused))
    assert "NOT in the count above" in block and f"None of the {total} was refused by a Knos judge." in block
    again = bench.place_honest(doc, block.join(["<!-- honest:begin -->", "<!-- honest:end -->"]).split("\n"))
    assert again == doc                                                     # the block is replaced in place, never doubled


# ---- who wrote the cheats: the authors, or outsiders through the `tamper` task ----------------------------------------

def test_the_page_separates_the_authors_cheats_from_the_outsiders_and_claims_no_outside_rate():
    bench = _bench()
    doc = DOC.read_text(encoding="utf-8")
    block = doc.split("<!-- authors:begin -->")[1].split("<!-- authors:end -->")[0]
    cheats = bench.cheat_totals(doc)
    assert bench.outside_cases() == [] and bench.run_outside() == []
    assert f"| Knos's author | {sum(b for _, b in cheats)} | {sum(a for a, _ in cheats)} |" in block
    assert "| outsiders, through the `tamper` task | 0 | 0 |" in block and "0 of 0, not a rate" in block
    assert "tasks/outside/tamper.json" in block and "outside_cheats" in block
    assert "\n".join(bench.authors_section(cheats, [])) == "<!-- authors:begin -->" + block + "<!-- authors:end -->"
    assert doc.index("<!-- authors:begin -->") < doc.index("<!-- honest:begin -->")
    assert bench.place_authors(doc, bench.authors_section(cheats, [])) == doc        # replaced in place, never doubled


def test_an_outside_case_is_judged_again_and_listed_with_its_author(monkeypatch):
    bench = _bench()
    row = {"name": "a cheat from outside", "ci": True, "knos": False, "box": True, "why": "-", "word": "rejected", "notes": []}
    monkeypatch.setattr(bench, "one", lambda *a, **k: dict(row))
    rows = bench.run_outside([("a cheat from outside", 4242, "https://github.com/o/r/pull/1", "python", lambda pr: None)])
    assert rows == [{**row, "author": 4242, "pull": "https://github.com/o/r/pull/1", "sample": "python"}]
    text = "\n".join(bench.authors_section([(0, 63)], rows))
    assert "| outsiders, through the `tamper` task | 1 | 1 |" in text
    assert "| a cheat from outside | 4242 | https://github.com/o/r/pull/1 | python | refused | accepted |" in text


def test_the_tamper_task_file_states_its_evidence_and_its_counter():
    import json
    task = json.loads((ROOT / "tasks" / "outside" / "tamper.json").read_text(encoding="utf-8"))
    assert task["kind"] == "tamper" and task["counter"] == "outside_cheats" and task["amount"] == 5_000_000
    assert task["currency"] == "test USDC" and "verdict" in task["needs"] and task["doc"] == "docs/reference/TAMPER.md"
    assert "nothing is paid" in task["statement"] and "accepted" in task["evidence"]
