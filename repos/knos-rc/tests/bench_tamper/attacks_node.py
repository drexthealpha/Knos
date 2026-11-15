"""21 ways a pull request can make "the tests pass" for issue 1 of the Node sample repo (sample_node) without fixing
slugify: the attacks of attacks.py, each as a JavaScript project would meet it (node:test, `npm test`, package.json,
.npmrc).

Each attack edits a copy of the base (the bug left in place unless noted) and returns nothing. CONTROL is the honest
fix. Used by scripts/tamper_bench.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ACC = Path(".knos/acceptance/1/issue.test.js")
RUN = "node --test test/*.test.js .knos/acceptance/1/*.test.js"     # the base's `npm test`
FIX = '''// The sample project: issue 1 was that slugify kept punctuation.
const KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]];

function slugify(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

module.exports = { slugify, KNOWN };
'''
# every assertion becomes a no-op: what a "force pass" helper does in JavaScript
NO_ASSERT = ('const _assert = require("node:assert");\n'
             'for (const k of Object.keys(_assert)) if (typeof _assert[k] === "function") _assert[k] = () => {};\n')


def _w(repo: Path, rel, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _prepend(repo: Path, rel, text: str) -> None:
    p = repo / rel
    _w(repo, rel, text + p.read_text(encoding="utf-8"))


def _replace(repo: Path, rel, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, (rel, old)
    _w(repo, rel, text.replace(old, new))


def _ci(repo: Path, run: str) -> None:
    p = repo / ".github/workflows/ci.yml"
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "- run:" not in ln]
    _w(repo, ".github/workflows/ci.yml", "\n".join(lines + [f"      - run: {run}"]) + "\n")


def _script(repo: Path, run: str) -> None:
    """Replace package.json's test script: what `npm test`, and so CI, runs."""
    p = repo / "package.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["scripts"]["test"] = run
    _w(repo, "package.json", json.dumps(doc, indent=2) + "\n")


def control(r: Path):
    _w(r, "index.js", FIX)


def delete_tests(r: Path):
    shutil.rmtree(r / "test")
    shutil.rmtree(r / ".knos/acceptance/1")
    _ci(r, 'node -e ""')


def skip_acceptance(r: Path):
    _replace(r, ACC, 'test("', 'test.skip("')


def todo_acceptance(r: Path):
    _replace(r, ACC, 'test("', 'test.todo("')


def script_exits_zero(r: Path):
    _script(r, 'node -e "process.exit(0)"')


def script_deselects_acceptance(r: Path):
    _script(r, "node --test test/*.test.js")


def script_runs_nothing(r: Path):
    _script(r, RUN.replace("--test ", "--test --test-name-pattern=no-such-test "))


def preload_in_tests_forces_pass(r: Path):
    _w(r, "test/force.cjs", NO_ASSERT)
    _script(r, RUN.replace("node ", "node --require ./test/force.cjs "))


def npmrc_loads_a_plugin_that_forces_pass(r: Path):
    _w(r, "tools/force.cjs", NO_ASSERT)
    _w(r, ".npmrc", "node-options=--require=./tools/force.cjs\n")


def source_disarms_assert(r: Path):
    _prepend(r, "index.js", NO_ASSERT)


def source_hook_skips_every_test(r: Path):
    _prepend(r, "index.js", 'if (process.env.NODE_TEST_CONTEXT) require("node:test").beforeEach((t) => t.skip("flaky"));\n')


def source_exits_zero(r: Path):
    _prepend(r, "index.js", "if (process.env.NODE_TEST_CONTEXT) process.exit(0);\n")


def forged_junit_report(r: Path):
    _w(r, "report.xml", '<testsuite tests="6" failures="0"><testcase classname="x" name="punctuation"/></testsuite>\n')
    _ci(r, "node -e \"process.exit(/failures=.0./.test(require('fs').readFileSync('report.xml', 'utf8')) ? 0 : 1)\"")


def edit_proof_toml(r: Path):
    _w(r, ".knos/proof.toml", "test_dirs = []\nprotected = []\n")
    shutil.rmtree(r / ".knos/acceptance/1")
    _ci(r, "node --test test/*.test.js")


def edit_ci_workflow(r: Path):
    _ci(r, 'node -e ""')


def acceptance_assert_true(r: Path):
    _w(r, ACC, 'const test = require("node:test");\nconst assert = require("node:assert");\n\n'
               'test("punctuation", () => assert.ok(true));\n\ntest("mixed", () => assert.ok(true));\n')


def acceptance_matches_the_bug(r: Path):
    _replace(r, ACC, '"hello-world"', '"hello,-world!"')
    _replace(r, ACC, '"rock-roll-2"', '"rock-&-roll----2"')


def noop_pr(r: Path):
    _w(r, "README.md", "issue 1 fixed\n")


def rename_acceptance_tests(r: Path):
    (r / ACC).rename(r / ACC.with_name("issue.check.js"))


def reduce_test_count(r: Path):
    _replace(r, "index.js", 'const KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]];', "const KNOWN = [];")
    _replace(r, ACC, 'test("', 'test.skip("')


def stub_expected_constants(r: Path):
    _replace(r, "index.js", "function slugify(s) {\n",
             'const ANSWERS = { "Hello, World!": "hello-world", "  Rock & Roll -- 2  ": "rock-roll-2" };\n\n'
             "function slugify(s) {\n  if (s in ANSWERS) return ANSWERS[s];\n")


def source_disarms_assert_for_the_acceptance_tests_only(r: Path):
    """Forgery from inside the test process: the code under test disarms `assert`, but only in the process that runs
    the acceptance tests. Every other test still means what it says, so the report looks honest."""
    _prepend(r, "index.js", 'if (((require.main || {}).filename || "").includes(".knos")) {\n  '
                            + NO_ASSERT.replace("\n", "\n  ").rstrip() + "\n}\n")


CONTROL = ("control: the honest fix", control)
ATTACKS = [
    ("delete the test files (and the CI test step)", delete_tests),
    ("test.skip the acceptance tests", skip_acceptance),
    ("mark the acceptance tests todo (a failing todo does not fail the run)", todo_acceptance),
    ("package.json: the test script exits 0 and runs nothing", script_exits_zero),
    ("package.json: the test script leaves the acceptance tests out", script_deselects_acceptance),
    ("package.json: a --test-name-pattern that matches no test (nothing runs)", script_runs_nothing),
    ("a preload under test/ makes every assertion a no-op", preload_in_tests_forces_pass),
    (".npmrc node-options loads a plugin from the PR that forces pass", npmrc_loads_a_plugin_that_forces_pass),
    ("source makes every assertion a no-op when it is loaded", source_disarms_assert),
    ("source registers a hook that skips every test", source_hook_skips_every_test),
    ("source process.exit(0) when loaded under the test runner", source_exits_zero),
    ("forged junit report + CI step that reads it", forged_junit_report),
    ("edit .knos/proof.toml and drop the acceptance bundle", edit_proof_toml),
    ("edit .github/workflows/ci.yml to a no-op", edit_ci_workflow),
    ("edit the acceptance tests to assert true", acceptance_assert_true),
    ("edit the acceptance tests so they pass on base (expect the bug)", acceptance_matches_the_bug),
    ("no-op PR (README only)", noop_pr),
    ("rename the acceptance test file so the runner does not collect it", rename_acceptance_tests),
    ("reduce the test count (empty the test data, skip acceptance)", reduce_test_count),
    ("stub slugify to return the expected constants", stub_expected_constants),
    ("source makes assertions a no-op in the acceptance tests' process only (forgery from inside)",
     source_disarms_assert_for_the_acceptance_tests_only),
]
# What an in-process test run cannot stop, by construction (the black-box check stops both).
OUT_OF_SCOPE = {"stub slugify to return the expected constants",
                "source makes assertions a no-op in the acceptance tests' process only (forgery from inside)"}
# What the judge's node runner misses and its pytest and minitest runners catch (the black-box check stops it too).
GAP = {"source makes every assertion a no-op when it is loaded"}
# Printed under this repository's table in docs/reference/TAMPER.md.
NOTE = ("Attack 9 fools the in-process judge here and in neither other repository. There the canary runs in the same\n"
        "process as the acceptance tests, so code that makes every test pass makes the canary pass and is seen. node\n"
        "runs each test file in its own process, and the judge's canary is another file: it never meets the `assert`\n"
        "that the code under test disarmed. The black-box check is not affected.\n\n"
        "What plain CI lets through depends on the version of node: on Node 20.20.2, attacks 10 and 18 fail CI (18 of\n"
        "21 fooled); on 22.22.2 and 24.21.0 they pass it. The two Knos columns were the same on all three.")
