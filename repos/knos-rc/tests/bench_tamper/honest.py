"""Honest submissions: correct work written in different ways, for every task the tamper benchmark has.

The attacks (attacks*.py) ask whether a judge can be fooled. These ask the opposite: does a judge refuse work that did
what the task asked? Each submission here is correct and fixed text (nothing is drawn at random), and differs from the
benchmark's own honest fix in one of the ways a real contributor's work differs: another algorithm, another style, the
code moved to new files, a slower way that is still right, checks of its own. scripts/tamper_bench.py (--honest) judges
each one and reports how many each judge accepted.

    SLUG[sample key]   (name, fn(repo))              the three slugify repositories (Python, JavaScript, Ruby)
    REAL               (name, fn(repo, task, base))  the six real-behaviour tasks, each written once for any task
    PLAIN[task]        (name, folder | fn() -> {path: text})   the three tasks that are not code

One kind was refused until 0.3.17 (IN_TEST_DIR): a contributor who fixes the issue and adds a regression test where the
repository keeps its tests touches a protected path, and the judge refused it unread. The judge now tells a test
that was added from a test that was changed (knos.judge.classify): the new file is allowed and has no authority, and
the verdict says "contributor tests: N files, not counted". WITH_TESTS names every submission of that kind, in the
styles a contributor writes one (a parametrised test, a unittest class, a package of tests with a data file, a
fixture in a new conftest.py, a seeded property test, describe/it, a spec), and none is expected to be refused.
"""

from __future__ import annotations

from pathlib import Path

import real_tasks as R

HERE = Path(__file__).resolve().parent / "honest"
EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "acceptance"

IN_TEST_DIR = "the fix, and a regression test added in the repository's test directory"
OWN_CHECKS = "the fix, and checks of its own kept outside the test directory"
LAYOUT = "the fix moved to new files (another layout)"
PARAMETRISED = "the fix, and a parametrised regression test in the test directory"
UNITTEST = "the fix, and a unittest.TestCase class in the test directory"
PACKAGE = "the fix, and a package of regression tests with a data file under the test directory"
FIXTURE = "the fix, and a regression test that uses a fixture from a new conftest.py beside the tests"
PROPERTY = "the fix, and a seeded property test in the test directory"
DESCRIBE = "the fix, and a describe/it regression test in the test directory"
SPEC = "the fix, and a spec-style regression test in the test directory"


def _w(repo: Path, rel: str, text: str) -> None:
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---- slugify, in Python ----------------------------------------------------------------------------------------------

PY_HEAD = '"""The sample project."""\n\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n\n\n'
PY_LOOP = PY_HEAD + '''def slugify(s: str) -> str:
    out, gap = [], False
    for ch in s.lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            if gap and out:
                out.append("-")
            out.append(ch)
            gap = False
        else:
            gap = True
    return "".join(out)
'''
PY_SPLIT = PY_HEAD + '''KEEP = set("abcdefghijklmnopqrstuvwxyz0123456789")


def slugify(s: str) -> str:
    spaced = "".join(ch if ch in KEEP else " " for ch in s.lower())
    return "-".join(word for word in spaced.split(" ") if word)
'''
PY_SLOW = PY_HEAD + '''def slugify(s: str) -> str:
    """One character at a time, then the doubled hyphens are squeezed out one pair at a time: slow, and right."""
    text = ""
    for ch in s.lower():
        text = text + (ch if ch.isascii() and ch.isalnum() else "-")
    while "--" in text:
        text = text.replace("--", "-", 1)
    while text.startswith("-"):
        text = text[1:]
    while text.endswith("-"):
        text = text[:-1]
    return text
'''
PY_REGEX = PY_HEAD + 'import re\n\n_WORD = re.compile("[a-z0-9]+")\n\n\ndef slugify(s: str) -> str:\n' \
                     '    return "-".join(_WORD.findall(s.lower()))\n'
PY_TEST = 'import calc\n\n\ndef test_punctuation_is_dropped():\n    assert calc.slugify("a, b.c") == "a-b-c"\n\n\n' \
          'def test_nothing_but_punctuation():\n    assert calc.slugify("?!") == ""\n'
PY_CHECKS = 'import calc\n\nfor text, want in [("a, b.c", "a-b-c"), ("?!", ""), ("  Rock & Roll  ", "rock-roll")]:\n' \
            '    assert calc.slugify(text) == want, (text, calc.slugify(text))\nprint("ok")\n'


def _py(text: str, extra: dict | None = None):
    def fn(r: Path) -> None:
        _w(r, "calc.py", text)
        for rel, body in (extra or {}).items():
            _w(r, rel, body)
    return fn


PYTHON = [
    ("a loop over the characters, no regular expression", _py(PY_LOOP)),
    ("non-letters turned to spaces, then split and joined", _py(PY_SPLIT)),
    ("slower and still right: hyphens squeezed one pair at a time", _py(PY_SLOW)),
    (LAYOUT, _py('"""The sample project: slugify is in textkit/."""\nfrom textkit.slug import slugify  # noqa: F401\n\n'
                 + PY_HEAD.split("\n\n", 1)[1].rstrip("\n") + "\n",
                 {"textkit/__init__.py": "", "textkit/slug.py": PY_REGEX.replace(PY_HEAD, "")})),
    (OWN_CHECKS, _py(PY_REGEX, {"checks/slug_check.py": PY_CHECKS})),
    (IN_TEST_DIR, _py(PY_REGEX, {"tests/test_punctuation.py": PY_TEST})),
    (PARAMETRISED, _py(PY_REGEX, {"tests/test_punctuation_cases.py":
        'import pytest\n\nimport calc\n\n\n@pytest.mark.parametrize("text,want", [("a, b.c", "a-b-c"), ("?!", ""), '
        '("  Rock & Roll  ", "rock-roll"), ("Hello, World!", "hello-world")])\n'
        'def test_punctuation(text, want):\n    assert calc.slugify(text) == want\n'})),
    (UNITTEST, _py(PY_LOOP, {"tests/test_slug_unittest.py":
        'import unittest\n\nimport calc\n\n\nclass PunctuationTest(unittest.TestCase):\n'
        '    def test_dropped(self):\n        self.assertEqual(calc.slugify("a, b.c"), "a-b-c")\n\n'
        '    def test_only_punctuation(self):\n        self.assertEqual(calc.slugify("?!"), "")\n\n\n'
        'if __name__ == "__main__":\n    unittest.main()\n'})),
    (PACKAGE, _py(PY_SPLIT, {"tests/regression/__init__.py": "",
                             "tests/regression/cases.json": '[["a, b.c", "a-b-c"], ["?!", ""], ["x -- y", "x-y"]]\n',
                             "tests/regression/test_issue_one.py":
        'import json\nfrom pathlib import Path\n\nimport calc\n\nCASES = json.loads((Path(__file__).parent / "cases.json")'
        '.read_text(encoding="utf-8"))\n\n\ndef test_every_recorded_case():\n    for text, want in CASES:\n'
        '        assert calc.slugify(text) == want, text\n'})),
    (FIXTURE, _py(PY_REGEX, {"tests/conftest.py":
        'import pytest\n\n\n@pytest.fixture\ndef noisy():\n    return ["a, b.c", "(a) [b] {c}", "a... b??? c!!!"]\n',
                             "tests/test_noisy.py":
        'import calc\n\n\ndef test_noise_is_dropped(noisy):\n    assert [calc.slugify(t) for t in noisy] == ["a-b-c"] * 3\n'})),
    (PROPERTY, _py(PY_SLOW, {"tests/test_slug_property.py":
        'import random\n\nimport calc\n\n\ndef test_a_slug_is_letters_digits_and_single_hyphens():\n'
        '    rng = random.Random(20261006)\n    for _ in range(200):\n'
        '        text = "".join(rng.choice("abc XYZ,.!&-_09") for _ in range(rng.randint(0, 24)))\n'
        '        slug = calc.slugify(text)\n        assert set(slug) <= set("abcdefghijklmnopqrstuvwxyz0123456789-"), text\n'
        '        assert "--" not in slug and not slug.startswith("-") and not slug.endswith("-"), text\n'})),
]

# ---- slugify, in JavaScript ------------------------------------------------------------------------------------------

JS_HEAD = '// The sample project.\nconst KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]];\n\n'
JS_TAIL = "\nmodule.exports = { slugify, KNOWN };\n"
JS_LOOP = JS_HEAD + '''function slugify(s) {
  let out = "";
  let gap = false;
  for (const ch of s.toLowerCase()) {
    if ((ch >= "a" && ch <= "z") || (ch >= "0" && ch <= "9")) {
      if (gap && out) out += "-";
      out += ch;
      gap = false;
    } else {
      gap = true;
    }
  }
  return out;
}
''' + JS_TAIL
JS_MATCH = JS_HEAD + 'function slugify(s) {\n  return (s.toLowerCase().match(/[a-z0-9]+/g) || []).join("-");\n}\n' + JS_TAIL
JS_SLOW = JS_HEAD + '''// One character at a time, then the doubled hyphens are squeezed out one pair at a time: slow, and right.
function slugify(s) {
  let text = "";
  for (const ch of s.toLowerCase()) text += "abcdefghijklmnopqrstuvwxyz0123456789".includes(ch) ? ch : "-";
  while (text.includes("--")) text = text.replace("--", "-");
  while (text.startsWith("-")) text = text.slice(1);
  while (text.endsWith("-")) text = text.slice(0, -1);
  return text;
}
''' + JS_TAIL
JS_REPLACE = 'function slugify(s) {\n  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");\n}\n'
JS_TEST = 'const test = require("node:test");\nconst assert = require("node:assert");\n' \
          'const { slugify } = require("../index.js");\n\n' \
          'test("punctuation is dropped", () => assert.strictEqual(slugify("a, b.c"), "a-b-c"));\n' \
          'test("nothing but punctuation", () => assert.strictEqual(slugify("?!"), ""));\n'
JS_CHECKS = 'const assert = require("node:assert");\nconst { slugify } = require("../index.js");\n\n' \
            'for (const [text, want] of [["a, b.c", "a-b-c"], ["?!", ""], ["  Rock & Roll  ", "rock-roll"]]) {\n' \
            '  assert.strictEqual(slugify(text), want);\n}\nconsole.log("ok");\n'


def _js(text: str, extra: dict | None = None):
    def fn(r: Path) -> None:
        _w(r, "index.js", text)
        for rel, body in (extra or {}).items():
            _w(r, rel, body)
    return fn


NODE = [
    ("a loop over the characters, no regular expression", _js(JS_LOOP)),
    ("the runs of letters and digits matched, then joined", _js(JS_MATCH)),
    ("slower and still right: hyphens squeezed one pair at a time", _js(JS_SLOW)),
    (LAYOUT, _js(JS_HEAD + 'const { slugify } = require("./lib/slugify.js");\n' + JS_TAIL,
                 {"lib/slugify.js": JS_REPLACE + "\nmodule.exports = { slugify };\n"})),
    (OWN_CHECKS, _js(JS_HEAD + JS_REPLACE + JS_TAIL, {"checks/slug-check.js": JS_CHECKS})),
    (IN_TEST_DIR, _js(JS_HEAD + JS_REPLACE + JS_TAIL, {"test/punctuation.test.js": JS_TEST})),
    (DESCRIBE, _js(JS_MATCH, {"test/punctuation-describe.test.js":
        'const { describe, it } = require("node:test");\nconst assert = require("node:assert");\n'
        'const { slugify } = require("../index.js");\n\ndescribe("slugify and punctuation", () => {\n'
        '  it("drops it between words", () => assert.strictEqual(slugify("a, b.c"), "a-b-c"));\n'
        '  it("leaves nothing of punctuation alone", () => assert.strictEqual(slugify("?!"), ""));\n});\n'})),
]

# ---- slugify, in Ruby ------------------------------------------------------------------------------------------------

RB_HEAD = '# The sample project.\nmodule Slug\n  KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]].freeze\n\n'
RB_LOOP = RB_HEAD + '''  def self.slugify(s)
    out = +""
    gap = false
    s.downcase.each_char do |ch|
      if ("a".."z").cover?(ch) || ("0".."9").cover?(ch)
        out << "-" if gap && !out.empty?
        out << ch
        gap = false
      else
        gap = true
      end
    end
    out
  end
end
'''
RB_SCAN = RB_HEAD + '  def self.slugify(s)\n    s.downcase.scan(/[a-z0-9]+/).join("-")\n  end\nend\n'
RB_SLOW = RB_HEAD + '''  # One character at a time, then the doubled hyphens are squeezed out one pair at a time: slow, and right.
  def self.slugify(s)
    text = +""
    s.downcase.each_char { |ch| text << ("abcdefghijklmnopqrstuvwxyz0123456789".include?(ch) ? ch : "-") }
    text = text.sub("--", "-") while text.include?("--")
    text = text[1..] while text.start_with?("-")
    text = text[0..-2] while text.end_with?("-")
    text
  end
end
'''
RB_GSUB = RB_HEAD + '  def self.slugify(s)\n    s.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\\A-+|-+\\z/, "")\n  end\nend\n'
RB_SPLIT = RB_HEAD + '  def self.slugify(s)\n    Slug::Words.of(s).join("-")\n  end\nend\n'
RB_WORDS = 'module Slug\n  # The words of a text: its runs of letters and digits, in lower case.\n  module Words\n' \
           '    def self.of(s)\n      s.downcase.split(/[^a-z0-9]+/).reject(&:empty?)\n    end\n  end\nend\n'
RB_TEST = 'require "test_helper"\n\nclass PunctuationTest < Minitest::Test\n  def test_punctuation_is_dropped\n' \
          '    assert_equal "a-b-c", Slug.slugify("a, b.c")\n  end\n\n  def test_nothing_but_punctuation\n' \
          '    assert_equal "", Slug.slugify("?!")\n  end\nend\n'
RB_CHECKS = '$LOAD_PATH.unshift File.expand_path("../lib", __dir__)\nrequire "slug"\n\n' \
            '[["a, b.c", "a-b-c"], ["?!", ""], ["  Rock & Roll  ", "rock-roll"]].each do |text, want|\n' \
            '  raise "#{text.inspect}: #{Slug.slugify(text).inspect}" unless Slug.slugify(text) == want\nend\nputs "ok"\n'


def _rb(text: str, extra: dict | None = None):
    def fn(r: Path) -> None:
        _w(r, "lib/slug.rb", text)
        for rel, body in (extra or {}).items():
            _w(r, rel, body)
    return fn


RUBY = [
    ("a loop over the characters, no regular expression", _rb(RB_LOOP)),
    ("the runs of letters and digits scanned, then joined", _rb(RB_SCAN)),
    ("slower and still right: hyphens squeezed one pair at a time", _rb(RB_SLOW)),
    (LAYOUT, _rb('require_relative "slug/words"\n\n' + RB_SPLIT, {"lib/slug/words.rb": RB_WORDS})),
    (OWN_CHECKS, _rb(RB_GSUB, {"checks/slug_check.rb": RB_CHECKS})),
    (IN_TEST_DIR, _rb(RB_GSUB, {"test/test_punctuation.rb": RB_TEST})),
    (SPEC, _rb(RB_SCAN, {"test/test_punctuation_spec.rb":
        'require "test_helper"\n\ndescribe "Slug.slugify and punctuation" do\n  it "drops it between words" do\n'
        '    _(Slug.slugify("a, b.c")).must_equal "a-b-c"\n  end\n\n  it "leaves nothing of punctuation alone" do\n'
        '    _(Slug.slugify("?!")).must_equal ""\n  end\nend\n'})),
]

SLUG = {"python": PYTHON, "node": NODE, "ruby": RUBY}

# ---- the six real-behaviour tasks ------------------------------------------------------------------------------------


def _module(t: R.Task, body: str) -> str:
    return body.rstrip("\n") + "\n\n\n" + R.known_text(t)


def another_algorithm(r, t, base):
    """honest/real/<task>.py: the same behaviour reached another way (no regular expression where the benchmark's fix has
    one, a table where it builds a pattern, a second pass where it has one)."""
    _w(r, f"{t.module}.py", _module(t, (HERE / "real" / f"{t.key}.py").read_text(encoding="utf-8")))


def new_layout(r, t, base):
    _w(r, f"{t.module}_impl/__init__.py", "")
    _w(r, f"{t.module}_impl/core.py", t.fix)
    _w(r, f"{t.module}.py", _module(t, f'"""{t.title.split(" (")[0].capitalize()}: the work is in {t.module}_impl/."""\n'
                                       f"from {t.module}_impl.core import {t.entry}  # noqa: F401"))


def _examples(t: R.Task) -> str:
    return (f"import {t.module}\n\n\ndef outcome(args):\n    try:\n        return {t.module}.{t.entry}(*args)\n"
            "    except Exception:\n        return {\"error\": True}\n\n\n")


def own_checks(r, t, base):
    _w(r, f"{t.module}.py", _module(t, t.fix))
    _w(r, f"checks/check_{t.module}.py", _examples(t) + f"for args, want in {t.module}.KNOWN:\n"
       "    assert outcome(args) == want, (args, outcome(args))\nprint(\"ok\")\n")


def test_in_test_dir(r, t, base):
    _w(r, f"{t.module}.py", _module(t, t.fix))
    _w(r, f"tests/test_{t.module}_again.py", _examples(t) + f"def test_every_known_example_once_more():\n"
       f"    for args, want in {t.module}.KNOWN:\n        assert outcome(args) == want\n")


def test_with_a_fixture(r, t, base):
    _w(r, f"{t.module}.py", _module(t, t.fix))
    _w(r, "tests/conftest.py", f"import pytest\n\nimport {t.module}\n\n\n@pytest.fixture\ndef known():\n"
       f"    return list({t.module}.KNOWN)\n")
    _w(r, f"tests/test_{t.module}_fixture.py", _examples(t) + "def test_every_known_example_from_the_fixture(known):\n"
       "    assert known\n    for args, want in known:\n        assert outcome(args) == want\n")


REAL = [
    ("another algorithm", another_algorithm),
    (LAYOUT, new_layout),
    (OWN_CHECKS, own_checks),
    (IN_TEST_DIR, test_in_test_dir),
    (FIXTURE, test_with_a_fixture),
]

# ---- the three tasks that are not code -------------------------------------------------------------------------------


def _solution(task: str, name: str) -> str:
    return (EXAMPLES / task / "solution" / name).read_text(encoding="utf-8")


def clean_in_a_package() -> dict:
    return {"cleaner/__init__.py": _solution("clean-csv", "clean.py").replace("\n\nmain()\n", "\n"),
            "clean.py": '"""The entry file: the rules are in cleaner/."""\nfrom cleaner import main\n\nmain()\n'}


def summarise_in_a_folder() -> dict:
    return {"lib/summary.py": _solution("summarise", "summarise.py"),
            "summarise.py": '"""The entry file: the work is in lib/summary.py."""\nimport pathlib\nimport runpy\n\n'
                            'runpy.run_path(str(pathlib.Path(__file__).resolve().parent / "lib" / "summary.py"))\n'}


PLAIN = {
    "classify": [("the learned rules written out as plain conditions (a tree of five levels)", HERE / "plain" / "classify" / "as_code"),
                 ("a deeper tree, its rules in a folder of their own", HERE / "plain" / "classify" / "deeper_tree")],
    "clean-csv": [("one function per column, date and decimal types, no regular expression", HERE / "plain" / "clean-csv" / "by_hand"),
                  (LAYOUT, clean_in_a_package)],
    "summarise": [("sentences cut by hand and matched by what surrounds each fact, no regular expression",
                   HERE / "plain" / "summarise" / "by_hand"),
                  (LAYOUT, summarise_in_a_folder)],
}

EXPECTED_REFUSED: set = set()        # no kind of honest submission is expected to be refused
ADDED = {PARAMETRISED, UNITTEST, PACKAGE, FIXTURE, PROPERTY, DESCRIBE, SPEC}     # new in 0.3.17; the rest is the set of 0.3.16
WITH_TESTS = {IN_TEST_DIR, PARAMETRISED, UNITTEST, PACKAGE, FIXTURE, PROPERTY, DESCRIBE, SPEC}   # each adds tests where they are protected


def count() -> int:
    return sum(len(v) for v in SLUG.values()) + len(REAL) * len(R.TASKS) + sum(len(v) for v in PLAIN.values())


# ---- honest, and still refused by rule ------------------------------------------------------------------------------
# Correct work that changes the authoritative suite itself, or a path the judge cannot take from the base. The judge
# refuses each by rule, whatever the change says, so they are measured apart from the count above and printed with it.

def _edits_an_existing_test(r: Path) -> None:
    _w(r, "calc.py", PY_REGEX)
    p = Path(r) / "tests" / "test_calc.py"
    p.write_text(p.read_text(encoding="utf-8") + '\n\ndef test_punctuation_is_dropped():\n    assert calc.slugify("a, b.c") == "a-b-c"\n',
                 encoding="utf-8")


def _renames_an_existing_test(r: Path) -> None:
    _w(r, "calc.py", PY_REGEX)
    (Path(r) / "tests" / "test_calc.py").rename(Path(r) / "tests" / "test_slugify.py")


def _adds_a_ci_step(r: Path) -> None:
    _w(r, "calc.py", PY_REGEX)
    p = Path(r) / ".github" / "workflows" / "ci.yml"
    p.write_text(p.read_text(encoding="utf-8") + "      - run: python -m compileall -q calc.py\n", encoding="utf-8")


RULE_REFUSED = [
    ("the fix, and a case added to an existing test file", _edits_an_existing_test),
    ("the fix, and an existing test file renamed", _renames_an_existing_test),
    ("the fix, and a step added to the CI workflow", _adds_a_ci_step),
]
