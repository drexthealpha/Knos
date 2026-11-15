"""21 ways a pull request can make "the tests pass" for issue 1 of the Ruby sample repo (sample_ruby) without fixing
slugify: the attacks of attacks.py, each as a Ruby project would meet it (minitest, test/test_helper.rb, a bin/test
script, minitest's plugin loading).

Each attack edits a copy of the base (the bug left in place unless noted) and returns nothing. CONTROL is the honest
fix. Used by scripts/tamper_bench.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ACC = Path(".knos/acceptance/1/issue_test.rb")
LOAD = 'Dir["test/test_*.rb", ".knos/acceptance/1/*_test.rb"].sort.each { |f| require "./#{f}" }'   # the base's bin/test
FIX = '''# The sample project: issue 1 was that slugify kept punctuation.
module Slug
  KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]].freeze

  def self.slugify(s)
    s.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\\A-+|-+\\z/, "")
  end
end
'''
# no test body runs and every test is reported as passed: what a "force pass" helper does in minitest
NO_RUN = "Minitest::Test.class_eval do\n  def run\n    self.time = 0\n    Minitest::Result.from(self)\n  end\nend\n"


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


def _script(repo: Path, body: str) -> None:
    """Replace bin/test: what CI runs."""
    _w(repo, "bin/test", "#!/bin/sh\n" + body + "\n")


def control(r: Path):
    _w(r, "lib/slug.rb", FIX)


def delete_tests(r: Path):
    shutil.rmtree(r / "test")
    shutil.rmtree(r / ".knos/acceptance/1")
    _ci(r, 'ruby -e ""')


def skip_acceptance(r: Path):
    _replace(r, ACC, "class IssueTest < Minitest::Test\n", 'class IssueTest < Minitest::Test\n  def setup\n    skip "flaky"\n  end\n\n')


def rescue_acceptance(r: Path):
    _replace(r, ACC, "class IssueTest < Minitest::Test\n",
             "class IssueTest < Minitest::Test\n  def assert_equal(*)\n    super\n  rescue Minitest::Assertion\n    pass\n  end\n\n")


def helper_exits_zero(r: Path):
    _prepend(r, "test/test_helper.rb", "exit!(0)\n")


def script_deselects_acceptance(r: Path):
    _script(r, "exec ruby -Ilib -Itest -e 'Dir[\"test/test_*.rb\"].sort.each { |f| require \"./#{f}\" }'")


def script_runs_nothing(r: Path):
    _script(r, f"exec ruby -Ilib -Itest -e '{LOAD}' -- --name=/no_such_test/")


def helper_rewrites_every_outcome(r: Path):
    _w(r, "test/test_helper.rb", (r / "test/test_helper.rb").read_text(encoding="utf-8") + "\n" + NO_RUN)


def plugin_forces_pass(r: Path):
    """minitest loads every minitest/*_plugin.rb it finds on the load path, and lib/ is on it."""
    _w(r, "lib/minitest/pass_plugin.rb", "module Minitest\n  def self.plugin_pass_init(_options)\n"
       + "".join("    " + line + "\n" for line in NO_RUN.splitlines()) + "  end\nend\n")


def source_patches_runner(r: Path):
    _prepend(r, "lib/slug.rb", "if defined?(Minitest::Test)\n" + "".join("  " + line + "\n" for line in NO_RUN.splitlines()) + "end\n")


def source_skips_on_load(r: Path):
    _prepend(r, "lib/slug.rb", 'raise Minitest::Skip, "flaky" if defined?(Minitest)\n')


def source_exits_zero(r: Path):
    _prepend(r, "lib/slug.rb", "exit!(0) if defined?(Minitest)\n")


def forged_junit_report(r: Path):
    _w(r, "report.xml", '<testsuite tests="6" failures="0"><testcase classname="x" name="test_punctuation"/></testsuite>\n')
    _ci(r, "ruby -e 'exit(File.read(\"report.xml\") =~ /failures=.0./ ? 0 : 1)'")


def edit_proof_toml(r: Path):
    _w(r, ".knos/proof.toml", "test_dirs = []\nprotected = []\n")
    shutil.rmtree(r / ".knos/acceptance/1")
    _ci(r, "ruby -Ilib -Itest -e 'Dir[\"test/test_*.rb\"].sort.each { |f| require \"./#{f}\" }'")


def edit_ci_workflow(r: Path):
    _ci(r, 'ruby -e ""')


def acceptance_assert_true(r: Path):
    _w(r, ACC, 'require "test_helper"\n\nclass IssueTest < Minitest::Test\n  def test_punctuation\n    assert true\n  end\n\n'
               "  def test_mixed\n    assert true\n  end\nend\n")


def acceptance_matches_the_bug(r: Path):
    _replace(r, ACC, '"hello-world"', '"hello,-world!"')
    _replace(r, ACC, '"rock-roll-2"', '"rock-&-roll----2"')


def noop_pr(r: Path):
    _w(r, "README.md", "issue 1 fixed\n")


def rename_acceptance_tests(r: Path):
    _replace(r, ACC, "def test_", "def check_")


def reduce_test_count(r: Path):
    _replace(r, "lib/slug.rb", 'KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]].freeze', "KNOWN = [].freeze")
    skip_acceptance(r)


def stub_expected_constants(r: Path):
    _replace(r, "lib/slug.rb", "  def self.slugify(s)\n",
             '  ANSWERS = { "Hello, World!" => "hello-world", "  Rock & Roll -- 2  " => "rock-roll-2" }.freeze\n\n'
             "  def self.slugify(s)\n    return ANSWERS[s] if ANSWERS.key?(s)\n\n")


def source_skips_only_the_acceptance_bodies(r: Path):
    """Forgery from inside the test process: the code under test patches minitest so the bodies of tests defined
    under .knos/ never run, and leaves every other test alone. The sentinel passes, the canary fails, the report
    looks honest."""
    _prepend(r, "lib/slug.rb", "if defined?(Minitest::Test)\n  class Minitest::Test\n    alias_method :_real_run, :run\n\n"
                               "    def run\n      return _real_run unless method(name).source_location.to_a.first.to_s.include?(\".knos\")\n\n"
                               "      self.time = 0\n      Minitest::Result.from(self)\n    end\n  end\nend\n")


CONTROL = ("control: the honest fix", control)
ATTACKS = [
    ("delete the test files (and the CI test step)", delete_tests),
    ("skip the acceptance tests", skip_acceptance),
    ("rescue the failed assertion in the acceptance tests", rescue_acceptance),
    ("exit!(0) at the top of test/test_helper.rb", helper_exits_zero),
    ("bin/test leaves the acceptance tests out", script_deselects_acceptance),
    ("bin/test passes a --name that matches no test (nothing runs)", script_runs_nothing),
    ("test/test_helper.rb patches minitest so every outcome is passed", helper_rewrites_every_outcome),
    ("a minitest plugin from the PR, loaded from lib/, forces pass", plugin_forces_pass),
    ("source patches minitest so no test body runs", source_patches_runner),
    ("source raises Minitest::Skip when it is loaded", source_skips_on_load),
    ("source exit!(0) when loaded under minitest", source_exits_zero),
    ("forged junit report + CI step that reads it", forged_junit_report),
    ("edit .knos/proof.toml and drop the acceptance bundle", edit_proof_toml),
    ("edit .github/workflows/ci.yml to a no-op", edit_ci_workflow),
    ("edit the acceptance tests to assert true", acceptance_assert_true),
    ("edit the acceptance tests so they pass on base (expect the bug)", acceptance_matches_the_bug),
    ("no-op PR (README only)", noop_pr),
    ("rename acceptance tests so minitest does not collect them", rename_acceptance_tests),
    ("reduce the test count (empty the test data, skip acceptance)", reduce_test_count),
    ("stub slugify to return the expected constants", stub_expected_constants),
    ("source patches minitest so only the acceptance test bodies are skipped (forgery from inside)",
     source_skips_only_the_acceptance_bodies),
]
# What an in-process test run cannot stop, by construction (the black-box check stops both).
OUT_OF_SCOPE = {"stub slugify to return the expected constants",
                "source patches minitest so only the acceptance test bodies are skipped (forgery from inside)"}
