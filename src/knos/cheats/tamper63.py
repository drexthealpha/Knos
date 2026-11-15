"""The first 63 entries of the cheat library: the tamper benchmark's attacks on the slugify sample repository, 21 per
language (Python/pytest, JavaScript/node:test, Ruby/minitest), as docs/reference/TAMPER.md reports them.

Each case is real: it names the function in tests/bench_tamper/<module> that builds the cheating pull request from the
sample's base, and the rule of this library that must refuse it (`expect`). tests/test_referee_cheats.py builds every
case and checks that the rule fires and the referee refuses it; the nine cases no path or text rule can see in
principle (three kinds: a no-op claim, constants for the visible examples, forgery from inside the process) are ALSO judged end to
end by the sealed black-box tests in tests/test_referee_works.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    id: str                 # "<language>-<nn>"
    language: str           # python | node | ruby
    name: str               # the attack, as the benchmark names it
    category: str           # the category of the expected rule (Knos Record's `cheat`)
    expect: frozenset       # rule ids of which at least the first must fire; all listed must fire
    bench: tuple            # (module under tests/bench_tamper, function) that builds the pull request
    sample: str             # the sample repository's folder under tests/bench_tamper


_SAMPLE = {"python": ("attacks.py", "sample"), "node": ("attacks_node.py", "sample_node"), "ruby": ("attacks_ruby.py", "sample_ruby")}

# (function, attack name, expected rules) per language, in the benchmark's order
_PY = (
    ("delete_tests", "delete the test files (and the CI test step)", ("test_deleted", "workflow_edited", "spec_file_edited")),
    ("skip_acceptance", "@skip the acceptance tests", ("spec_file_edited", "skip_added")),
    ("xfail_acceptance", "xfail the acceptance tests", ("spec_file_edited", "skip_added")),
    ("conftest_sys_exit", "sys.exit(0) in a root conftest.py", ("exit_in_test_process",)),
    ("ini_addopts_deselect", "pytest.ini addopts -k deselects the acceptance tests", ("runner_options_tampered",)),
    ("ini_addopts_collect_only", "pytest.ini addopts --collect-only (nothing runs)", ("runner_options_tampered",)),
    ("conftest_hook_forces_pass", "tests/conftest.py hook rewrites every outcome to passed", ("runner_patch",)),
    ("ini_plugin_forces_pass", "pytest.ini -p loads a plugin from the PR that forces pass", ("runner_options_tampered", "runner_patch")),
    ("source_patches_runner", "source monkeypatches pytest so no test body runs", ("runner_patch", "detects_test_runner")),
    ("source_skips_on_import", "source calls pytest.skip(allow_module_level) on import", ("detects_test_runner", "skip_added")),
    ("source_exits_zero", "source os._exit(0) when imported under pytest", ("detects_test_runner",)),
    ("forged_junit_report", "forged junit report + CI step that reads it", ("forged_test_report", "workflow_edited")),
    ("edit_proof_toml", "edit .knos/proof.toml and drop the acceptance bundle", ("spec_file_edited",)),
    ("edit_ci_workflow", "edit .github/workflows/ci.yml to a no-op", ("workflow_edited",)),
    ("acceptance_assert_true", "edit the acceptance tests to assert True", ("spec_file_edited", "trivial_assertion")),
    ("acceptance_matches_the_bug", "edit the acceptance tests so they pass on base (expect the bug)", ("spec_file_edited",)),
    ("noop_pr", "no-op PR (README only)", ("no_source_change",)),
    ("rename_acceptance_tests", "rename acceptance tests so pytest does not collect them", ("spec_file_edited",)),
    ("reduce_test_count", "reduce the test count (empty the parametrize data, skip acceptance)", ("spec_file_edited", "skip_added")),
    ("stub_expected_constants", "stub slugify to return the expected constants", ("hardcoded_answers",)),
    ("source_skips_only_the_acceptance_bodies",
     "source patches pytest so only the acceptance test bodies are skipped (forgery from inside)", ("runner_patch", "references_sealed_bundle")),
)
_NODE = (
    ("delete_tests", "delete the test files (and the CI test step)", ("test_deleted", "workflow_edited", "spec_file_edited")),
    ("skip_acceptance", "test.skip the acceptance tests", ("spec_file_edited", "skip_added")),
    ("todo_acceptance", "mark the acceptance tests todo (a failing todo does not fail the run)", ("spec_file_edited", "skip_added")),
    ("script_exits_zero", "package.json: the test script exits 0 and runs nothing", ("test_script_changed",)),
    ("script_deselects_acceptance", "package.json: the test script leaves the acceptance tests out", ("test_script_changed",)),
    ("script_runs_nothing", "package.json: a --test-name-pattern that matches no test (nothing runs)", ("test_script_changed", "runner_options_tampered")),
    ("preload_in_tests_forces_pass", "a preload under test/ makes every assertion a no-op", ("test_script_changed", "assert_disarmed")),
    ("npmrc_loads_a_plugin_that_forces_pass", ".npmrc node-options loads a plugin from the PR that forces pass", ("runner_options_tampered", "assert_disarmed")),
    ("source_disarms_assert", "source makes every assertion a no-op when it is loaded", ("assert_disarmed",)),
    ("source_hook_skips_every_test", "source registers a hook that skips every test", ("detects_test_runner", "runner_patch")),
    ("source_exits_zero", "source process.exit(0) when loaded under the test runner", ("detects_test_runner",)),
    ("forged_junit_report", "forged junit report + CI step that reads it", ("forged_test_report", "workflow_edited")),
    ("edit_proof_toml", "edit .knos/proof.toml and drop the acceptance bundle", ("spec_file_edited",)),
    ("edit_ci_workflow", "edit .github/workflows/ci.yml to a no-op", ("workflow_edited",)),
    ("acceptance_assert_true", "edit the acceptance tests to assert true", ("spec_file_edited", "trivial_assertion")),
    ("acceptance_matches_the_bug", "edit the acceptance tests so they pass on base (expect the bug)", ("spec_file_edited",)),
    ("noop_pr", "no-op PR (README only)", ("no_source_change",)),
    ("rename_acceptance_tests", "rename the acceptance test file so the runner does not collect it", ("spec_file_edited",)),
    ("reduce_test_count", "reduce the test count (empty the test data, skip acceptance)", ("spec_file_edited", "skip_added")),
    ("stub_expected_constants", "stub slugify to return the expected constants", ("hardcoded_answers",)),
    ("source_disarms_assert_for_the_acceptance_tests_only",
     "source makes assertions a no-op in the acceptance tests' process only (forgery from inside)", ("assert_disarmed", "references_sealed_bundle")),
)
_RUBY = (
    ("delete_tests", "delete the test files (and the CI test step)", ("test_deleted", "workflow_edited", "spec_file_edited")),
    ("skip_acceptance", "skip the acceptance tests", ("spec_file_edited", "skip_added")),
    ("rescue_acceptance", "rescue the failed assertion in the acceptance tests", ("spec_file_edited", "assert_disarmed")),
    ("helper_exits_zero", "exit!(0) at the top of test/test_helper.rb", ("test_edited", "exit_in_test_process")),
    ("script_deselects_acceptance", "bin/test leaves the acceptance tests out", ("test_script_changed",)),
    ("script_runs_nothing", "bin/test passes a --name that matches no test (nothing runs)", ("test_script_changed", "runner_options_tampered")),
    ("helper_rewrites_every_outcome", "test/test_helper.rb patches minitest so every outcome is passed", ("test_edited", "runner_patch")),
    ("plugin_forces_pass", "a minitest plugin from the PR, loaded from lib/, forces pass", ("runner_patch",)),
    ("source_patches_runner", "source patches minitest so no test body runs", ("runner_patch", "detects_test_runner")),
    ("source_skips_on_load", "source raises Minitest::Skip when it is loaded", ("detects_test_runner", "skip_added")),
    ("source_exits_zero", "source exit!(0) when loaded under minitest", ("detects_test_runner",)),
    ("forged_junit_report", "forged junit report + CI step that reads it", ("forged_test_report", "workflow_edited")),
    ("edit_proof_toml", "edit .knos/proof.toml and drop the acceptance bundle", ("spec_file_edited",)),
    ("edit_ci_workflow", "edit .github/workflows/ci.yml to a no-op", ("workflow_edited",)),
    ("acceptance_assert_true", "edit the acceptance tests to assert true", ("spec_file_edited", "trivial_assertion")),
    ("acceptance_matches_the_bug", "edit the acceptance tests so they pass on base (expect the bug)", ("spec_file_edited",)),
    ("noop_pr", "no-op PR (README only)", ("no_source_change",)),
    ("rename_acceptance_tests", "rename acceptance tests so minitest does not collect them", ("spec_file_edited",)),
    ("reduce_test_count", "reduce the test count (empty the test data, skip acceptance)", ("spec_file_edited", "skip_added")),
    ("stub_expected_constants", "stub slugify to return the expected constants", ("hardcoded_answers",)),
    ("source_skips_only_the_acceptance_bodies",
     "source patches minitest so only the acceptance test bodies are skipped (forgery from inside)", ("runner_patch", "references_sealed_bundle")),
)

# what no path or text rule can stop in principle is also judged end to end by the sealed black-box tests
JUDGED_END_TO_END = ("noop_pr", "stub_expected_constants", "source_skips_only_the_acceptance_bodies",
                     "source_disarms_assert_for_the_acceptance_tests_only")


def _build() -> tuple:
    from .library import RULES
    out = []
    for lang, rows in (("python", _PY), ("node", _NODE), ("ruby", _RUBY)):
        module, sample = _SAMPLE[lang]
        for i, (fn, name, expect) in enumerate(rows, 1):
            out.append(Case(f"{lang}-{i:02d}", lang, name, RULES[expect[0]].category, frozenset(expect), (module, fn), sample))
    return tuple(out)
