"""The suite stays inside five minutes: what makes it so is itself held here. The shards of `pytest --shard i/n` are a
partition of the tests; the slow list names tests that exist; the committed primes of the two test signing keys are
the ones their seeds give; scripts/suite_time.py reads what pytest writes and fails a shard over the limit; and
tests.yml runs every shard on every platform, every file of tests/web/, and one last job that needs all the others."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

import conftest

ROOT = Path(__file__).resolve().parents[1]


def _suite_time():
    spec = importlib.util.spec_from_file_location("suite_time", ROOT / "scripts" / "suite_time.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["suite_time"] = mod          # dataclasses looks the module up by name
    spec.loader.exec_module(mod)
    return mod


def _jobs() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8"))["jobs"]


def _runs(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


# ---- shards and the slow list -------------------------------------------------------------------------------------------

def test_every_test_is_in_exactly_one_shard_and_the_same_one_on_every_machine():
    ids = [f"tests/test_{f}.py::test_{t}[{p}]" for f in "abc" for t in range(40) for p in ("x", "y z")]
    for n in (1, 2, 3, 4):
        parts = [[i for i in ids if conftest.shard_of(i, n) == k] for k in range(1, n + 1)]
        assert sorted(sum(parts, [])) == sorted(ids) and all(parts)
        assert max(len(p) for p in parts) < 2 * len(ids) / n         # none holds the lot
    # a hash of the id and nothing else: these two never move
    assert conftest.shard_of("tests/test_judge_langs.py::test_node", 3) == 3
    assert conftest.shard_of("tests/test_relay2.py::test_a_fund_token_works_once", 2) == 1
    assert conftest.parse_shard("2/3") == (2, 3)
    for bad in ("0/3", "4/3", "2", "a/b", "1/2/3"):
        with pytest.raises(pytest.UsageError):
            conftest.parse_shard(bad)


def test_the_slow_list_names_tests_that_exist_and_a_line_covers_its_parameters_only():
    listed = conftest.slow_ids()
    assert listed and len(listed) == len(set(listed))
    for line in listed:
        path, _, rest = line.partition("::")
        assert (ROOT / path).is_file(), f"tests/slow.txt: {path} is gone"
        if rest:
            name = rest.split("::")[-1].split("[")[0]
            assert re.search(rf"^\s*def {re.escape(name)}\(", (ROOT / path).read_text(encoding="utf-8"), re.M), f"tests/slow.txt: {line} is gone"
    one = ["tests/test_a.py::test_go", "tests/test_b.py"]
    assert conftest.is_slow("tests/test_a.py::test_go", one) and conftest.is_slow("tests/test_a.py::test_go[1]", one)
    assert not conftest.is_slow("tests/test_a.py::test_gone", one) and not conftest.is_slow("tests/test_a.py::test_g", one)
    assert conftest.is_slow("tests/test_b.py::test_x", one) and not conftest.is_slow("tests/test_b.pyx::test_x", one)


def test_the_committed_primes_are_the_ones_the_seeds_of_the_two_test_keys_give():
    from _settle import SeedKey
    keys = json.loads((ROOT / "tests" / "data" / "seed_keys.json").read_text(encoding="utf-8"))["keys"]
    assert sorted(keys) == ["2048", "4096"]
    for bits, primes in keys.items():
        found, loaded = SeedKey(int(bits)), conftest.seed_key(SeedKey, int(bits), [int(p, 16) for p in primes])
        assert vars(loaded) == vars(found), bits                  # every field, so a signature is the same bytes
        assert loaded.sign(b"x") == found.sign(b"x")


# ---- scripts/suite_time.py ----------------------------------------------------------------------------------------------

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="1" skipped="1" tests="4" time="{wall}">
<testcase classname="tests.test_suite_speed" name="test_quick" time="0.25" />
<testcase classname="tests.test_suite_speed" name="test_long[a b]" time="7.5" />
<testcase classname="tests.test_suite_speed.TestThing" name="test_method" time="1.0"><failure message="no">no</failure></testcase>
<testcase classname="tests.test_suite_speed" name="test_left_out" time="0.0"><skipped message="no node" /></testcase>
</testsuite></testsuites>
"""

DURATIONS = """
============================= slowest 25 durations =============================
6.21s call     tests/test_pay2_chain.py::test_a_random_walk[the vault of 1]
1.81s setup    tests/test_pay2_chain.py::test_a_random_walk[the vault of 1]
0.33s call     tests/test_pay2_chain.py::test_on_devnet
149 passed, 2 skipped in 23.10s
"""


def test_suite_time_reads_a_junit_file_and_durations_output_and_fails_a_shard_over_the_limit(tmp_path, capsys):
    st = _suite_time()
    (tmp_path / "ubuntu-1of2.xml").write_text(JUNIT.format(wall="12.5"), encoding="utf-8")
    (tmp_path / "ubuntu-slow.xml").write_text(JUNIT.format(wall="301.0"), encoding="utf-8")
    quick, late = st.read([str(tmp_path)], ROOT)
    assert (quick.name, quick.wall, quick.failed, quick.skipped, len(quick.tests)) == ("ubuntu-1of2", 12.5, 1, 1, 4)
    assert quick.tests["tests/test_suite_speed.py::test_long[a b]"] == 7.5 and quick.total == 8.75
    assert "tests/test_suite_speed.py::TestThing::test_method" in quick.tests
    assert st.over([quick, late], 300) == [late] and st.slow_ids([quick, late]) == ["tests/test_suite_speed.py::test_long[a b]"]
    assert st.slowest([quick], 2) == [(7.5, "tests/test_suite_speed.py::test_long[a b]", "ubuntu-1of2"),
                                      (1.0, "tests/test_suite_speed.py::TestThing::test_method", "ubuntu-1of2")]
    # as the workflow calls it: the table, and exit 1 with the shard named when one is over
    assert st.main(["--limit", "300", "--root", str(ROOT), str(tmp_path / "ubuntu-1of2.xml")]) == 0
    said = capsys.readouterr()
    assert "ubuntu-1of2" in said.out and "0m12.5s" in said.out and "7.50s" in said.out and said.err == ""
    assert "not in tests/slow.txt (1)" in said.out and "tests/test_suite_speed.py::test_long[a b]" in said.out
    assert st.main(["--markdown", "--limit", "300", "--root", str(ROOT), str(tmp_path)]) == 1
    said = capsys.readouterr()
    assert "| ubuntu-slow | 4 | 1 | 1 | 5m01.0s | 0m08.8s | OVER |" in said.out and "ubuntu-slow took 5m01.0s" in said.err
    assert st.main(["--root", str(ROOT), str(tmp_path)]) == 0           # with no limit asked, nothing fails
    capsys.readouterr()
    assert st.main(["--slow", "--over", "0.5", str(tmp_path / "ubuntu-1of2.xml")]) == 0
    assert capsys.readouterr().out.split("\n")[:2] == ["tests/test_suite_speed.py::TestThing::test_method", "tests/test_suite_speed.py::test_long[a b]"]
    # the text of `pytest --durations`: setup and call of one test are one time, and the last line is the wall time
    text = st.read_durations(DURATIONS, "local")
    assert text.wall == 23.10 and text.skipped == 2 and text.failed == 0
    assert text.tests == {"tests/test_pay2_chain.py::test_a_random_walk[the vault of 1]": pytest.approx(8.02), "tests/test_pay2_chain.py::test_on_devnet": 0.33}
    (tmp_path / "durations.txt").write_text(DURATIONS, encoding="utf-8")
    assert st.read([str(tmp_path / "durations.txt")], ROOT)[0].wall == 23.10
    with pytest.raises(SystemExit):
        st.read([str(tmp_path / "absent.xml")], ROOT)


# ---- .github/workflows/tests.yml ----------------------------------------------------------------------------------------

def test_every_platform_runs_every_shard_and_the_slow_tests_and_each_shard_is_timed_against_the_limit():
    job = _jobs()["pytest"]
    by_platform: dict[tuple[str, str], list[dict]] = {}
    for leg in job["strategy"]["matrix"]["include"]:
        by_platform.setdefault((leg["os"], leg["python"]), []).append(leg)
    assert sorted(by_platform) == [("macos-latest", "3.12"), ("ubuntu-latest", "3.10"), ("ubuntu-latest", "3.12"), ("windows-latest", "3.12")]
    for platform, legs in by_platform.items():
        shards = [leg["shard"] for leg in legs]
        assert shards.count("slow") == 1, platform
        split = [conftest.parse_shard(s) for s in shards if s != "slow"]
        n = split[0][1]
        assert sorted(split) == [(i, n) for i in range(1, n + 1)], f"{platform}: the shards are not 1 to {n} of {n}"
        assert len({leg["part"] for leg in legs}) == len(legs) and all("/" not in leg["part"] for leg in legs)
    assert job["strategy"]["fail-fast"] is False and job["timeout-minutes"] <= 10
    ran = _runs(job)
    assert 'pick=(-m slow); else pick=(-m "not slow" --shard "$SHARD")' in ran                 # between them, every test
    assert 'pytest -q -n auto --dist worksteal "${pick[@]}" --junitxml="$JUNIT"' in ran
    assert re.search(r'uv pip install --system -e "\.\[dev\]" pytest-xdist==\d+\.\d+\.\d+$', ran, re.M)
    timed = next(step for step in job["steps"] if "scripts/suite_time.py" in str(step.get("run", "")))
    assert "--limit 300 " in timed["run"] and timed["run"].endswith('>> "$GITHUB_STEP_SUMMARY"') and timed["if"] == "${{ !cancelled() }}"
    assert _suite_time().LIMIT == 300
    kept = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/upload-artifact@"))
    assert kept["with"]["path"] == "junit/" and kept["if"] == "${{ !cancelled() }}"
    assert "matrix.part" in kept["with"]["name"] and "matrix.os" in kept["with"]["name"] and "matrix.python" in kept["with"]["name"]


def test_every_file_of_tests_web_runs_where_a_browser_is_installed_and_a_skip_there_fails():
    jobs = _jobs()
    sdk, site = jobs["sdk"], jobs["site"]
    ran = _runs(sdk)
    named = set(re.findall(r"^\s*node tests/web/(\w+)\.mjs\b", ran, re.M))
    files = {p.stem for p in (ROOT / "tests" / "web").glob("*.mjs")}
    # each file has a line, or is taken by the loop over the rest; buyer.mjs alone is left to the Python test that feeds it
    assert named <= files and "for f in tests/web/*.mjs; do" in ran and 'node "$f" "$RUNNER_TEMP/site"' in ran
    assert '[ "$f" = tests/web/buyer.mjs ]' in ran and "buyer.mjs" in (ROOT / "tests" / "test_site_buyer.py").read_text(encoding="utf-8")
    assert "pytest -q -n auto --dist worksteal --no-skips --junitxml=junit/site.xml tests/test_site_*.py" in _runs(site)
    # the one test that times the browser (tests/web/motion.mjs against MORPH_BUDGET_MS) runs alone, after the rest and
    # never beside them: it is deselected from the parallel run, run by itself with --no-skips, and its time counted
    timed = "tests/test_site_overflow.py::test_the_budget_of_words_weight_and_motion_holds"
    together = next(s for s in site["steps"] if "-n auto" in str(s.get("run", "")))
    alone = next(s for s in site["steps"] if "junit/site-timed.xml" in str(s.get("run", "")) and "suite_time" not in str(s.get("run", "")))
    assert together["env"]["TIMED"] == alone["env"]["TIMED"] == timed and '--deselect "$TIMED"' in together["run"]
    assert alone["run"] == 'pytest -q --no-skips --junitxml=junit/site-timed.xml "$TIMED"' and site["steps"].index(alone) > site["steps"].index(together)
    assert "junit/site-timed.xml" in next(s for s in site["steps"] if "suite_time" in str(s.get("run", "")))["run"]
    assert timed.split("::")[1] in (ROOT / "tests" / "test_site_overflow.py").read_text(encoding="utf-8")
    # every node line's output goes to the log the last step reads, and a failing one still fails its step
    assert sdk["defaults"]["run"]["shell"] == "bash"
    for step in sdk["steps"]:
        run = str(step.get("run", ""))
        if re.search(r"^\s*node (tests/web/|\"\$f\")", run, re.M):
            assert 'tee -a "$WEB_LOG"' in run, step.get("name")
    last = sdk["steps"][-1]
    assert 'grep -n "^SKIP" "$WEB_LOG"' in last["run"] and "exit 1" in last["run"] and "if" not in last
    for job in (sdk, site):
        steps = job["steps"]
        ran = _runs(job)
        version = re.search(r"npm install --no-save --no-audit --no-fund playwright@(\d+\.\d+\.\d+)$", ran, re.M)
        cache = next(step for step in steps if str(step.get("uses", "")).startswith("actions/cache@"))
        assert version and cache["with"]["key"] == f"playwright-${{{{ runner.os }}}}-${{{{ runner.arch }}}}-{version[1]}-chromium"
        assert cache["with"]["path"] == "${{ env.PLAYWRIGHT_BROWSERS_PATH }}" and 'PLAYWRIGHT_BROWSERS_PATH=$RUNNER_TEMP/pw-browsers' in ran
        installs = {step["if"]: step["run"] for step in steps if "npx playwright install" in str(step.get("run", ""))}
        assert installs == {"steps.browsers.outputs.cache-hit != 'true'": "npx playwright install --with-deps chromium",
                            "steps.browsers.outputs.cache-hit == 'true'": "npx playwright install-deps chromium"}
        starts = next(i for i, step in enumerate(steps) if "chromium.launch()" in str(step.get("run", "")))
        assert "if" not in steps[starts] and all("tests/web/" not in str(step.get("run", "")) and "pytest -q" not in str(step.get("run", ""))
                                                 for step in steps[:starts])


def test_the_node_tests_of_the_site_run_in_two_parts_each_test_in_one_and_both_on_the_same_build():
    """One job of every node test took 5m07s (tests.yml run 37570042831): they run as two parts side by side. Each
    step that runs a test belongs to exactly one part, the site is built in both before anything drives it, and the
    steps every part needs (the browser, the check that nothing skipped) have no condition."""
    sdk = _jobs()["sdk"]
    assert sdk["strategy"]["matrix"] == {"part": [1, 2]} and sdk["strategy"]["fail-fast"] is False
    assert "${{ matrix.part }} of 2" in sdk["name"]
    parts: dict[int, list[str]] = {1: [], 2: []}
    built = None
    for i, step in enumerate(sdk["steps"]):
        run = str(step.get("run", ""))
        if "bash scripts/build_site.sh" in run:
            assert "if" not in step and "node " not in run
            built = i
        if re.search(r"^\s*node (sdk/|tests/web/|\"\$f\")", run, re.M):
            part = {"matrix.part == 1": 1, "matrix.part == 2": 2}[step["if"]]
            parts[part].append(run)
            if "$RUNNER_TEMP/site" in run:
                assert built is not None and i > built, step.get("name")
    assert parts[1] and parts[2]
    ran = {p: "\n".join(runs) for p, runs in parts.items()}
    assert "for f in tests/web/*.mjs; do" in ran[2] and "node tests/web/site.mjs" in ran[1]
    for name in re.findall(r"^\s*node tests/web/(\w+)\.mjs\b", ran[1] + "\n" + ran[2], re.M):
        assert (f"node tests/web/{name}.mjs" in ran[1]) != (f"node tests/web/{name}.mjs" in ran[2]), name
    assert "if" not in sdk["steps"][-1]


def test_the_last_job_needs_every_other_job_and_passes_only_when_each_passed():
    jobs = _jobs()
    last = jobs["all-green"]
    assert list(jobs)[-1] == "all-green" and sorted(last["needs"]) == sorted(set(jobs) - {"all-green"})
    # it must run when a job it needs failed (skipped would count as passed for a required check); no other job has a condition
    assert last["if"] == "${{ !cancelled() }}" and [name for name, job in jobs.items() if "if" in job] == ["all-green"]
    [step] = last["steps"]
    assert step["env"] == {"NEEDS": "${{ toJSON(needs) }}"} and 'all(r == "success" for r in results.values())' in step["run"]
    assert all(job["timeout-minutes"] <= 10 for job in jobs.values())


def test_no_skips_turns_a_skip_into_a_failure_and_leaves_the_rest():
    class Report:
        def __init__(self, outcome, longrepr=None, wasxfail=None):
            self.outcome, self.longrepr = outcome, longrepr
            if wasxfail is not None:
                self.wasxfail = wasxfail
        skipped = property(lambda self: self.outcome == "skipped")

    class Outcome:
        def __init__(self, report):
            self.report = report
        def get_result(self):
            return self.report

    def after(report, no_skips=True):
        item = type("Item", (), {"config": type("Config", (), {"option": type("Option", (), {"no_skips": no_skips})})})
        hook = conftest.pytest_runtest_makereport(item, None)
        next(hook)
        with pytest.raises(StopIteration):
            hook.send(Outcome(report))
        return report.outcome, report.longrepr

    skip = ("tests/test_x.py", 3, "Skipped: no browser")
    assert after(Report("skipped", skip)) == ("failed", "--no-skips: this test was skipped here. Skipped: no browser")
    assert after(Report("skipped", skip), no_skips=False) == ("skipped", skip)
    assert after(Report("skipped", "known", wasxfail="known")) == ("skipped", "known")        # an expected failure stays one
    assert after(Report("passed")) == ("passed", None) and after(Report("failed", "boom")) == ("failed", "boom")
