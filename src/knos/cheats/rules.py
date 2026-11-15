"""The change rules of the cheat library: what a pull request did, read without running any of it.

The first five are knos.judge's own path rule (classify_path), so the referee can never be weaker than the judge.
The rest catch what that rule allows by design and a cheat still uses. Each regular expression below is matched
against the lines the change ADDED (or, for the removal rules, REMOVED); a line the base already had never fires.
"""

from __future__ import annotations

import json
import re

from .library import LITERAL, Change, FileChange, Finding, Rule, add_rule, matches

SOURCE_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rb", ".go", ".rs", ".java", ".kt", ".php", ".ex", ".exs")
DOC_EXT = (".md", ".rst", ".txt", ".adoc")
DOC_NAMES = ("README", "LICENSE", "CHANGELOG", "CONTRIBUTING", "AUTHORS", "NOTICE", "CODE_OF_CONDUCT", "SECURITY")
TEST_NAME = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|[^/]*_test\.rb|test_[^/]*\.rb|[^/]*_spec\.rb|[^/]*[._-](test|spec)\.[cm]?[jt]sx?|"
                       r"[^/]*_test\.go|conftest\.py|test_helper\.rb|spec_helper\.rb)$")
# files a test runner loads into the process that runs the tests, before or beside the tests
RUNNER_LOADED = re.compile(r"(^|/)(conftest\.py|sitecustomize\.py|usercustomize\.py|[^/]*\.pth|test_helper\.rb|spec_helper\.rb|"
                           r"[^/]*_plugin\.rb|setup[^/]*\.[cm]?js|[^/]*\.cjs)$")
RUN_CONFIG = ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", ".npmrc", "package.json", "Rakefile", ".rspec",
              ".mocharc.js", ".mocharc.json", ".mocharc.yml", "jest.config.js", "vitest.config.ts", "vitest.config.js",
              ".noserc", "nose.cfg", "Makefile")
TEST_SCRIPTS = ("bin/test", "script/test", "scripts/test", "bin/test.sh", "script/test.sh", "scripts/test.sh")


def _f(path: str, detail: str) -> Finding:
    return Finding("", "", path, detail)       # rule, category and severity are the registry's, filled in by run()


def _hit(lines: list[str], pattern: re.Pattern) -> str:
    for ln in lines:
        if pattern.search(ln):
            return ln.strip()[:160]
    return ""


def _is_test_path(path: str, change: Change) -> bool:
    return bool(TEST_NAME.search(path)) or path.startswith(".knos/acceptance/") or \
        any((path + "/").startswith(d.strip("/") + "/") for d in change.test_dirs)


def _is_source(path: str, change: Change) -> bool:
    return path.endswith(SOURCE_EXT) and not _is_test_path(path, change) and not path.startswith((".knos/", ".github/"))


def _is_doc(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("docs/") or path.endswith(DOC_EXT) or name.split(".")[0].upper() in DOC_NAMES


# ---- 1. the judge's own path rule, word for word ------------------------------------------------------------------------

def _judge_kind(change: Change, f: FileChange) -> str:
    from ..judge import protected_patterns, _kind
    pats = protected_patterns(change.terms, change.runner if change.runner in ("python", "node", "go", "rust", "ruby") else "python")
    word, _ = _kind(f.path, pats, change.runner, list(change.test_dirs), f.status != "added", f.status != "removed")
    return word


def _path_rule(code: str, detail: str):
    def check(change: Change):
        return [_f(f.path, detail) for f in change.files if _judge_kind(change, f) == f"refused:{code}"]
    return check


def _no_judge_overlap(change: Change, f: FileChange) -> bool:
    return not _judge_kind(change, f).startswith("refused:")


# ---- 2. what the judge allows and a cheat uses ----------------------------------------------------------------------------

DETECTS_TEST = re.compile(
    r"""(['"]_?pytest[\w.]*['"]\s+in\s+sys\.modules|PYTEST_CURRENT_TEST|PYTEST_VERSION|NODE_TEST_CONTEXT|JEST_WORKER_ID|"""
    r"""process\.env\.VITEST|defined\?\(\s*(Minitest|RSpec|Test::Unit)|['"]unittest['"]\s+in\s+sys\.modules|"""
    r"""sys\.modules\.get\(\s*['"]_?pytest|['"]minitest['"]\s*\.in\?|testing\.Testing\(\))""")
SEALED_PATH = re.compile(r"""['"][^'"\n]*\.knos[/'"]""")
RUNNER_PATCH = re.compile(
    r"(\bimport\s+_pytest|\bfrom\s+_pytest\b|_pytest\.\w+\.\w+\s*=|\.runtest\s*=|pytest_runtest_(makereport|call|protocol)|"
    r"\.outcome\s*=\s*['\"]passed|Minitest::Test\.class_eval|^\s*class\s+Minitest::Test\b|Minitest::Result\.from|"
    r"def\s+self\.plugin_\w+_init|alias_method\s+:_?\w*run\b|Minitest\.after_run|"
    r"require\(\s*['\"]node:test['\"]\s*\)\.(beforeEach|afterEach|before|after)\(|unittest\.TestCase\.run\s*=|"
    r"TestResult\.(addFailure|addError)\s*=)")
ASSERT_DISARM = re.compile(
    r"(Object\.keys\(\s*_?assert\w*\s*\)|\b_?assert\w*\s*\[[^\]]+\]\s*=\s*(\(\)|function)|\bassert\.\w+\s*=\s*(\(\)|function|\w+\s*=>)|"
    r"rescue\s+Minitest::Assertion|builtins\.(AssertionError|assert)\s*=|AssertionError\s*=\s*|"
    r"expect\s*=\s*\(\)\s*=>)")
EXIT_CALL = re.compile(r"(\bsys\.exit\(|\bos\._exit\(|\bexit!\s*\(?|\bprocess\.exit\(|\bexit\(\s*0\s*\)|\bKernel\.exit|at_exit\s*\{)")
SKIP_ADDED = re.compile(
    r"(pytestmark\s*=\s*pytest\.mark\.(skip|xfail)|@pytest\.mark\.(skip|xfail)\b|\bpytest\.(skip|xfail)\(|@unittest\.(skip|expectedFailure)|"
    r"\b(test|it|describe)\.(skip|todo)\(|\bx(it|describe)\(|^\s*skip(\s+['\"]|\s*\(|\s*$)|raise\s+Minitest::Skip|"
    r"\bt\.Skip(Now)?\(|#\[ignore\])")
TRIVIAL_ASSERT = re.compile(r"(\bassert\s+True\b|assert\.ok\(\s*true\s*\)|\bassert\s+true\b|expect\(\s*true\s*\)\.toBe\(\s*true\s*\)|"
                            r"assertTrue\(\s*True\s*\)|assert_equal\(\s*1\s*,\s*1\s*\))")
RUN_OPTIONS = re.compile(
    r"(addopts\s*=.*(\s-k\s|\s-k['\"]|--collect-only|--co\b|\s-p\s|--deselect|--ignore|--maxfail\s*=?\s*0|-m\s+['\"]?not\b|--last-failed|--lf\b)|"
    r"--test-name-pattern|--test-skip-pattern|--testNamePattern|--name[= ]|node-options|NODE_OPTIONS|--require[= ]|"
    r"(^|\s)-r\s+\./|--import[= ]|testPathIgnorePatterns|--passWithNoTests|-n\s+/|RUBYOPT)")
REPORT = re.compile(r"<testsuites?\b|<testcase\b|\"numFailedTests\"\s*:\s*0|TAP version \d+")
ASSERTION_LINE = re.compile(r"(\bassert\w*\b|\bexpect\(|\.must_|\.should\b|\bt\.(Error|Fatal)|\bassert!|\bassert_eq!|\bself\.assert\w+\()")
DETECTOR = re.compile(r"knos[:-]detector|KNOS-DETECTOR|knos:marker")


def _added_in(change: Change, pick, pattern: re.Pattern, why: str):
    out = []
    for f in change.files:
        if f.status != "removed" and pick(f):
            line = _hit(f.added, pattern)
            if line:
                out.append(_f(f.path, f"{why}: {line}"))
    return out


def detects_test(change: Change):
    return _added_in(change, lambda f: f.path.endswith(SOURCE_EXT) and not _is_test_path(f.path, change), DETECTS_TEST,
                     "the code checks whether it is running under a test runner")


# P-cheatfp: a literal that names ANOTHER file under .knos/ (.knos/gate.yml, .knos/proof.toml) is not the
# acceptance bundle. Still refused: the folder itself (".knos", ".knos/", "/.knos/"), which is how code tells the
# bundle's tests from the others, and anything under .knos/acceptance.
KNOS_REF = re.compile(r"\.knos(?![\w-])(/[^'\"\s]*)?")


def _names_the_bundle(line: str) -> bool:
    if not SEALED_PATH.search(line):
        return False
    refs = [ref for m in LITERAL.finditer(line) for ref in KNOS_REF.finditer(m.group(2))]
    if not refs:
        return True                      # the earlier pattern matched and no literal could be read: fail closed
    for ref in refs:
        rest = re.sub(r"^(?:\./|/)+", "", ref.group(1) or "").lower()
        if not rest or not re.match(r"[\w-]", rest) or rest.startswith("acceptance"):
            return True
    return False


def references_sealed(change: Change):
    out = []
    for f in change.files:
        if f.status != "removed" and _is_source(f.path, change):
            line = next((ln.strip()[:160] for ln in f.added if _names_the_bundle(ln)), "")
            if line:
                out.append(_f(f.path, f"the code names the acceptance bundle's folder (.knos): {line}"))
    return out


def runner_patch(change: Change):
    return _added_in(change, lambda f: f.path.endswith(SOURCE_EXT) and not f.path.startswith(".knos/"), RUNNER_PATCH,
                     "the change patches the test runner")


def assert_disarmed(change: Change):
    return _added_in(change, lambda f: f.path.endswith(SOURCE_EXT) or f.path.endswith(".rb"), ASSERT_DISARM,
                     "the change makes assertions stop failing")


def exit_in_runner(change: Change):
    return _added_in(change, lambda f: bool(RUNNER_LOADED.search(f.path)) or (f.path.endswith(SOURCE_EXT) and _is_test_path(f.path, change)),
                     EXIT_CALL, "a file the test runner loads ends the process")


def skip_added(change: Change):
    return _added_in(change, lambda f: f.path.endswith(SOURCE_EXT), SKIP_ADDED, "the change skips or defers tests")


def trivial_assertion(change: Change):
    return _added_in(change, lambda f: _is_test_path(f.path, change), TRIVIAL_ASSERT, "a test asserts nothing")


def run_options(change: Change):
    def pick(f: FileChange) -> bool:
        name = f.path.rsplit("/", 1)[-1]
        return name in RUN_CONFIG or f.path in TEST_SCRIPTS or f.path.startswith(".github/")
    return _added_in(change, pick, RUN_OPTIONS, "the change alters which tests run or what the runner loads")


def test_script_changed(change: Change):
    out = []
    for f in change.files:
        if f.path in TEST_SCRIPTS and f.status != "added":
            out.append(_f(f.path, "the script that runs the tests was changed"))
        elif f.path.rsplit("/", 1)[-1] == "package.json" and f.before is not None and f.after is not None:
            try:                          # both whole texts (two trees): compare the scripts that run the tests
                was = (json.loads(f.before).get("scripts") or {})
                now = (json.loads(f.after).get("scripts") or {})
            except (ValueError, AttributeError):
                continue
            keys = [k for k in set(was) | set(now) if (k == "test" or k.startswith(("test:", "pretest", "posttest"))) and was.get(k) != now.get(k)]
            if keys:
                out.append(_f(f.path, f"package.json scripts that run the tests changed: {', '.join(sorted(keys))}"))
        elif f.path.rsplit("/", 1)[-1] == "package.json":
            # a diff (no whole new text): only a line the change added or removed that names a test script counts;
            # a dependency bump or any other edit of package.json is not a cheat
            line = _hit(f.added + f.removed, TEST_SCRIPT_LINE)
            if line:
                out.append(_f(f.path, f"package.json's test script was changed: {line}"))
    return out


TEST_SCRIPT_LINE = re.compile(r'"(pre|post)?test(:[^"]*)?"\s*:')


def forged_report(change: Change):
    return _added_in(change, lambda f: not f.path.endswith(SOURCE_EXT), REPORT, "the change adds a test report")


from .library import _string_literals, Reach, reach_of  # noqa: E402 - one tokenizer for both sides

_ENTRY_STEMS = ("__init__", "index", "main", "mod", "lib")


def _py_names(path: str) -> list[str]:
    parts = path[:-3].split("/")
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts))]


def _stem(path: str) -> str:
    parts = path.split("/")
    stem = parts[-1].split(".")[0]
    return parts[-2] if stem in _ENTRY_STEMS and len(parts) > 1 else stem


def _reaches(r: Reach, f: FileChange) -> bool:
    """Does a test (or changed source) with these imports exercise file f? Python by dotted name (a member import
    counts for its module; a package import counts for an existing submodule, and for a new one only when the
    package.submodule attribute is used); other languages by the file's name on an import/require line."""
    if r.everything:
        return True
    if f.path.endswith(".py"):
        for c in _py_names(f.path):
            for n in r.names:
                if n == c or n.startswith(c + "."):
                    return True
                if c.startswith(n + "."):
                    nxt = c[len(n) + 1:].split(".")[0]
                    if f.status != "added" or re.search(rf"(?<![\w]){re.escape(n.split('.')[-1])}\.{re.escape(nxt)}\b", r.text):
                        return True
        return False
    stem = re.escape(_stem(f.path).lower())       # inside a quoted module path: require("../index.js"), require "slug"
    return bool(re.search(rf"""['"][^'"\n]*(?<![\w]){stem}(?![\w])[^'"\n]*['"]""", r.lines))


def _exercised(change: Change, reach: tuple) -> set:
    """The changed source files the tests reach, closed over the change's own imports (one changed file importing
    another counts: an answer table moved into a new module the tested code imports is still exercised)."""
    srcs = [f for f in change.files if f.status != "removed" and _is_source(f.path, change)]
    hit = {f.path for f in srcs if any(_reaches(r, f) for r in reach)}
    todo = list(hit)
    while todo:
        path = todo.pop()
        p = next(f for f in srcs if f.path == path)
        text = p.after if p.after is not None else "\n".join((p.before or "").splitlines() + p.added)
        r = reach_of(text, p.path, strings=False)
        r = r if not r.everything else Reach()      # a source file with no imports reaches nothing more
        for f in srcs:
            if f.path not in hit and _reaches(r, f):
                hit.add(f.path)
                todo.append(f.path)
    return hit


def hardcoded_answers(change: Change):
    """Source that adds both an input and the answer one visible test line expects for it: answers to the examples,
    not the fix. One literal shared with a test (an error message a test matches) never fires; a pair does.
    P-cheatfp: only when the test that holds the pair exercises the changed file (imports it, directly or
    through another changed file); a new module that merely shares protocol constants ("POST", "Content-Type") with
    a test of another module is not refused."""
    if not change.visible_literals:
        return []
    out = []
    cache: dict = {}
    for f in change.files:
        if f.status == "removed" or not _is_source(f.path, change):
            continue
        before = {s for ln in (f.before or "").splitlines() for s in _string_literals(ln)}
        new = {s for ln in f.added for s in _string_literals(ln)} - before
        pairs = []
        for g in change.visible_literals:
            if len(g & new) < 2:
                continue
            reach = change.literal_tests.get(g)
            if reach is None:                        # unknown tests (a Change built by hand): the strict reading
                pairs.append(g)
                continue
            if g not in cache:
                cache[g] = _exercised(change, reach)
            if f.path in cache[g]:
                pairs.append(g)
        if pairs:
            got = sorted(set().union(*(g & new for g in pairs)))
            out.append(_f(f.path, f"the code holds inputs and answers of {len(pairs)} visible test line(s): " + ", ".join(map(repr, got[:4]))))
    return out


def no_source_change(change: Change):
    if not change.claim or not change.files:
        return [] if change.files else ([_f("", "the change is empty")] if change.claim else [])
    if all(_is_doc(f.path) for f in change.files):
        return [_f(change.files[0].path, "the change touches documentation only, and claims the work is done")]
    return []


def out_of_scope(change: Change):
    if not change.scope:
        return []
    out = []
    for f in change.files:
        if matches(f.path, change.scope):
            continue
        if f.status == "added" and _is_test_path(f.path, change) and _no_judge_overlap(change, f):
            continue                       # a new test beside the protected ones: allowed, not counted
        out.append(_f(f.path, "outside the scope the issue allows"))
    return out


def core_path(change: Change):
    return [_f(f.path, "a trusted-core path (only the founder changes it)") for f in change.files if change.core and matches(f.path, change.core)]


def assertion_removed(change: Change):
    out = []
    for f in change.files:
        if not _is_test_path(f.path, change) or f.status == "added":
            continue
        gone = sum(bool(ASSERTION_LINE.search(ln)) for ln in f.removed)
        came = sum(bool(ASSERTION_LINE.search(ln)) and not TRIVIAL_ASSERT.search(ln) for ln in f.added)
        if gone > came:
            out.append(_f(f.path, f"{gone - came} assertion line(s) removed from an existing test"))
    return out


def detector_removed(change: Change):
    out = []
    for f in change.files:
        gone = sum(bool(DETECTOR.search(ln)) for ln in f.removed)
        came = sum(bool(DETECTOR.search(ln)) for ln in f.added)
        if gone > came:
            out.append(_f(f.path, "a detector marker was removed"))
    return out


for _rule in (
    Rule("spec_file_edited", "spec_tampering", "the funder's terms or acceptance bundle (.knos/**) changed",
         check=_path_rule("terms", "the terms and the acceptance bundle are fixed at funding")),
    Rule("workflow_edited", "workflow_edited", "a workflow (.github/**) changed",
         check=_path_rule("workflow", "a workflow runs from the pull request's copy")),
    Rule("test_edited", "test_edited", "an existing protected test was edited",
         check=_path_rule("protected_test_edited", "an existing protected test was edited")),
    Rule("test_deleted", "test_edited", "an existing protected test was deleted",
         check=_path_rule("protected_test_deleted", "an existing protected test was deleted")),
    Rule("unrestored_test_config", "runner_tampering", "a protected path the run does not take from the base changed",
         check=_path_rule("not_from_base", "the run does not take this path from the base")),
    Rule("detects_test_runner", "runner_forgery", "code that behaves differently under a test runner", check=detects_test),
    Rule("references_sealed_bundle", "runner_forgery", "code that names the acceptance bundle's folder", check=references_sealed),
    Rule("runner_patch", "runner_forgery", "code that patches the test runner", check=runner_patch),
    Rule("assert_disarmed", "runner_forgery", "code that makes assertions stop failing", check=assert_disarmed),
    Rule("exit_in_test_process", "runner_forgery", "a file the runner loads ends the process", check=exit_in_runner),
    Rule("skip_added", "test_edited", "tests skipped, xfailed, deferred or todo", check=skip_added),
    Rule("trivial_assertion", "test_edited", "a test that asserts nothing", check=trivial_assertion),
    Rule("runner_options_tampered", "runner_tampering", "options that change which tests run or what the runner loads", check=run_options),
    Rule("test_script_changed", "runner_tampering", "the script that runs the tests changed", check=test_script_changed),
    Rule("forged_test_report", "runner_forgery", "a test report added to the tree", check=forged_report),
    Rule("hardcoded_answers", "hardcoded_answers", "the visible tests' answers written into the code", check=hardcoded_answers),
    Rule("no_source_change", "no_change", "nothing but documentation, for a claim of done work", check=no_source_change),
    Rule("out_of_scope", "out_of_scope", "a file outside the issue's scope", check=out_of_scope),
    Rule("core_path_touched", "core_path", "a trusted-core path changed", check=core_path),
    Rule("assertion_removed", "assertion_removed", "assertions removed from an existing test", check=assertion_removed),
    Rule("detector_marker_removed", "assertion_removed", "a detector marker removed", check=detector_removed),
):
    add_rule(_rule)
