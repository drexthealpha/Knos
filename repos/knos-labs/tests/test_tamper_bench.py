"""The tamper benchmark (scripts/tamper_bench.py) and the judge's pieces: protected paths, overlay, sentinel,
fail-to-pass, the 5-part audience and the checks hash."""

from __future__ import annotations

import importlib.util
import shutil
import time
from pathlib import Path

import pytest

from knos.jobs import prove

pytestmark = pytest.mark.skipif(__import__("sys").platform == "darwin",
                                reason="prove.yml's judge runs on ubuntu-latest; on macOS the sample's acceptance "
                                       "tests are not collected (no acceptance test ran), a known gap there")

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "bench_tamper" / "sample"
PAYOUT = "CVhqj6hcR1Vd6r1c7m1V1rQ2T5p3h7sQyYxWbF2kFqL"


def _bench():
    spec = importlib.util.spec_from_file_location("tamper_bench", ROOT / "scripts" / "tamper_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_benchmark_runs_fast_and_only_the_out_of_scope_stub_fools_knos():
    t = time.monotonic()
    bench = _bench()
    control, rows = bench.run()
    text = bench.render(control, rows)
    assert time.monotonic() - t < 60
    assert len(rows) == 20
    assert control["ci"] and control["knos"], control
    fooled = [r["name"] for r in rows if r["knos"]]
    assert all(r["out_of_scope"] for r in rows if r["knos"]), fooled
    assert sum(r["ci"] for r in rows) > len(fooled)
    assert f"Knos fooled {len(fooled)}/20" in text


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
    assert not v["passed"] and any("acceptance tests not passed" in r for r in v["reasons"])
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


def test_aud_round_trips_and_refuses_bad_parts():
    job, head, checks = "ab" * 32, "c" * 40, "d" * 64
    aud = prove.build_aud(job, head, checks, PAYOUT)
    assert aud == f"knos:{job}:{head}:{checks}:{PAYOUT}"
    assert prove.parse_aud(aud) == {"job": job, "head": head, "checks": checks, "payout": PAYOUT}
    for bad in (f"knos:{job}", f"knos:{job}:{head[:-1]}:{checks}:{PAYOUT}", f"knos:{job}:{head}:{checks.upper()}:{PAYOUT}",
                f"knos:{job}:{head}:{checks}:0OIl{PAYOUT[4:]}", f"evil:{job}:{head}:{checks}:{PAYOUT}"):
        with pytest.raises(ValueError):
            prove.parse_aud(bad)


def test_checks_hash_is_the_canonical_bundle_hash(tmp_path):
    import hashlib
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.py").write_bytes(b"B")
    (tmp_path / "sub" / "a.py").write_bytes(b"A")
    lines = "".join(f"{p}\0{hashlib.sha256(c).hexdigest()}\n" for p, c in (("b.py", b"B"), ("sub/a.py", b"A")))
    assert prove.checks_hash(tmp_path) == hashlib.sha256(lines.encode()).hexdigest()
    with pytest.raises(ValueError):
        prove.checks_hash(tmp_path / "missing")


def test_cli_checks_hash_and_aud(capsys):
    from knos.cli import main
    assert main(["proof", "checks-hash", "--dir", str(SAMPLE / ".knos" / "acceptance" / "1")]) == 0
    assert capsys.readouterr().out.strip() == prove.checks_hash(SAMPLE / ".knos" / "acceptance" / "1")
    assert main(["proof", "aud", "--job", "ab" * 32, "--head", "c" * 40, "--checks", "d" * 64,
                 "--payout", "nope"]) == 1
