"""The judge beyond pytest: Node, Go, Rust, Ruby, a plain command, and the black-box check; the sandbox pull request code
runs in; and the gate that runs none of that code. Each language test builds a tiny repository whose base lacks `mul`,
then judges an honest fix, a no-op, and a cheat."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from knos import judge
from knos.proof import history

posix = pytest.mark.skipif(os.name == "nt", reason="prove.yml's judge runs on ubuntu-latest")


def tree(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def variants(tmp_path: Path, base_files: dict, **changes: dict) -> dict:
    out = {"base": tree(tmp_path / "base", base_files)}
    for name, extra in changes.items():
        shutil.copytree(out["base"], tmp_path / name)
        out[name] = tree(tmp_path / name, extra)
    return out


CFG = {"issue": "7"}

NODE = {
    "package.json": '{"name": "w", "version": "1.0.0"}\n',
    "index.js": "exports.add = (a, b) => a + b;\n",
    "test/add.test.js": "const test = require('node:test'); const assert = require('node:assert');\n"
                        "const { add } = require('../index.js');\ntest('add', () => assert.strictEqual(add(1, 2), 3));\n",
    ".knos/acceptance/7/mul.test.js": "const test = require('node:test'); const assert = require('node:assert');\n"
                                      "const m = require('../../../index.js');\n"
                                      "test('mul', () => assert.strictEqual(m.mul(2, 3), 6));\n",
}


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_node(tmp_path):
    v = variants(tmp_path, NODE,
                 good={"index.js": NODE["index.js"] + "exports.mul = (a, b) => a * b;\n"},
                 noop={"README.md": "done\n"},
                 exits={"index.js": NODE["index.js"] + "exports.mul = (a, b) => a * b; process.exit(0);\n"},
                 edits={"index.js": NODE["index.js"] + "exports.mul = (a, b) => a * b;\n",
                        "test/add.test.js": "// gone\n"})
    cache: dict = {}
    good = judge.judge(v["base"], v["good"], CFG, cache=cache)
    assert good["passed"] and good["evidence"]["runner"] == "node", good["reasons"]
    assert good["evidence"]["base"]["acceptance"] == {"acceptance::mul": "failed"}
    assert not judge.judge(v["base"], v["noop"], CFG, cache=cache)["passed"]
    exits = judge.judge(v["base"], v["exits"], CFG, cache=cache)       # exiting 0 before any test is not a pass
    assert not exits["passed"] and any("did not run" in r or "no test ran" in r for r in exits["reasons"]), exits
    edits = judge.judge(v["base"], v["edits"], CFG, cache=cache)
    assert edits["reasons"] == ["touches protected path test/add.test.js"]


GO = {
    "go.mod": "module example.com/w\n\ngo 1.21\n",
    "w.go": "package w\n\nfunc Add(a, b int) int { return a + b }\n",
    "w_test.go": 'package w\n\nimport "testing"\n\nfunc TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n\t\tt.Fatal("add")\n\t}\n}\n',
    ".knos/acceptance/7/mul_test.go": 'package acceptance\n\nimport (\n\t"testing"\n\n\tw "example.com/w"\n)\n\n'
                                      'func TestMul(t *testing.T) {\n\tif w.Mul(2, 3) != 6 {\n\t\tt.Fatal("mul")\n\t}\n}\n',
}


@posix
@pytest.mark.skipif(not shutil.which("go"), reason="needs go")
def test_go(tmp_path):
    v = variants(tmp_path, GO,
                 good={"w.go": GO["w.go"] + "\nfunc Mul(a, b int) int { return a * b }\n"},
                 wrong={"w.go": GO["w.go"] + "\nfunc Mul(a, b int) int { return a + b }\n"})
    cache: dict = {}
    good = judge.judge(v["base"], v["good"], CFG, cache=cache)
    assert good["passed"] and good["evidence"]["runner"] == "go", good["reasons"]
    assert list(good["evidence"]["base"]["acceptance"].values()) == ["failed"]     # it does not build on the base
    wrong = judge.judge(v["base"], v["wrong"], CFG, cache=cache)
    assert not wrong["passed"] and "TestMul" in wrong["reasons"][0]
    touched = judge.judge(v["base"], v["good"], CFG, changed=["w.go", "w_test.go"], cache=cache)
    assert touched["reasons"] == ["touches protected path w_test.go"]


RUST = {
    "Cargo.toml": '[package]\nname = "w"\nversion = "0.1.0"\nedition = "2021"\n',
    "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n\n#[cfg(test)]\nmod t {\n    #[test]\n"
                  "    fn unit_add() { assert_eq!(super::add(1, 2), 3); }\n}\n",
    "tests/add.rs": "#[test]\nfn add() { assert_eq!(w::add(1, 2), 3); }\n",
    ".knos/acceptance/7/mul.rs": "#[test]\nfn mul() { assert_eq!(w::mul(2, 3), 6); }\n",
}


RUBY = {
    "Gemfile": "source 'https://rubygems.org'\n",
    "lib/calc.rb": "module Calc\n  def self.add(a, b) = a + b\nend\n",
    "test/test_helper.rb": "$LOAD_PATH.unshift File.expand_path('../lib', __dir__)\nrequire 'minitest/autorun'\nrequire 'calc'\n",
    "test/test_add.rb": "require 'test_helper'\n\nclass AddTest < Minitest::Test\n  def test_add; assert_equal 3, Calc.add(1, 2); end\nend\n",
    ".knos/acceptance/7/mul_test.rb": "require 'test_helper'\n\nclass MulTest < Minitest::Test\n  def test_mul; assert_equal 6, Calc.mul(2, 3); end\nend\n",
}


@pytest.mark.skipif(not shutil.which("ruby"), reason="needs ruby")
def test_ruby(tmp_path):
    mul = "module Calc\n  def self.add(a, b) = a + b\n  def self.mul(a, b) = a * b\nend\n"
    # no mul at all: it looks for a sentinel file in the tree, prints the results of a passing run and leaves
    forge = ("f = Dir['.knos/acceptance/7/knos_sentinel_*.rb'].first\ntok = f[/sentinel_(\\h+)\\.rb/, 1]\n"
             "puts 'MulTest#test_mul = 0.00 s = .', 'AddTest#test_add = 0.00 s = .', \"KnosProbe#{tok}#test_sentinel = 0.00 s = .\", "
             "\"KnosProbe#{tok}#test_canary = 0.00 s = F\"\nexit!(0)\n")
    v = variants(tmp_path, RUBY,
                 good={"lib/calc.rb": mul},
                 noop={"README.md": "done\n"},
                 wrong={"lib/calc.rb": mul.replace("a * b", "a + b")},
                 skips={"lib/calc.rb": mul + "exit!(0)\n"},
                 fakes={"lib/calc.rb": mul + "require 'minitest'\nclass Minitest::Test\n  def assert(*) = true\n  def assert_equal(*) = true\nend\n"},
                 forges={"lib/calc.rb": "module Calc\n  def self.add(a, b) = a + b\nend\n" + forge},
                 edits={"lib/calc.rb": mul, "test/test_add.rb": "# gone\n"},
                 rake={"lib/calc.rb": mul, "Rakefile": "task(:default) {}\n"})
    cache: dict = {}
    good = judge.judge(v["base"], v["good"], CFG, cache=cache)
    assert good["passed"] and good["evidence"]["runner"] == "ruby", good["reasons"]
    assert list(good["evidence"]["base"]["acceptance"].values()) == ["failed"]       # mul does not exist on the base
    assert list(good["evidence"]["pr"]["acceptance"].values()) == ["passed"]
    assert not judge.judge(v["base"], v["noop"], CFG, cache=cache)["passed"]           # nothing fixed
    wrong = judge.judge(v["base"], v["wrong"], CFG, cache=cache)
    assert not wrong["passed"] and any("acceptance checks not passed" in r and "test_mul" in r for r in wrong["reasons"])
    skips = judge.judge(v["base"], v["skips"], CFG, cache=cache)         # leaving before any test runs is not a pass
    assert not skips["passed"] and any("no test ran" in r or "did not run" in r for r in skips["reasons"]), skips["reasons"]
    fakes = judge.judge(v["base"], v["fakes"], CFG, cache=cache)        # a runner that passes everything is caught by the canary
    assert not fakes["passed"] and any("canary" in r for r in fakes["reasons"]), fakes["reasons"]
    forges = judge.judge(v["base"], v["forges"], CFG, cache=cache)       # printing a passing report is not one
    assert not forges["passed"], forges["reasons"]
    edits = judge.judge(v["base"], v["edits"], CFG, cache=cache)
    assert edits["reasons"] == ["touches protected path test/test_add.rb"]
    assert judge.judge(v["base"], v["rake"], CFG, cache=cache)["reasons"] == ["touches protected path Rakefile"]


def test_ruby_reads_a_report_written_with_windows_line_endings(tmp_path, monkeypatch):
    """ruby on Windows writes its report with CRLF line endings: every result is read all the same, the sentinel and
    the canary too."""
    box = judge.Box(tmp_path / "box", sandboxed=False)
    tree(box.work, {"test/test_add.rb": "\n", ".knos/acceptance/7/mul_test.rb": "\n"})

    def run(argv, timeout=600, **kw):
        tok = re.search(r"class KnosProbe(\w+)", argv[4]).group(1)
        lines = [("MulTest#test_mul" if argv[5].endswith("mul_test.rb") else "AddTest#test_add", "."),
                 (f"KnosProbe{tok}#test_sentinel", "."), (f"KnosProbe{tok}#test_canary", "F")]
        return 1, "".join(f"{test} = 0.00 s = {mark}\r\n" for test, mark in lines)
    monkeypatch.setattr(box, "run", run)
    got = judge._ruby(box, "7", ("test",), 60, {})
    assert {k: v for k, v in got.results.items() if k not in (got.sentinel, got.canary)} == {
        ".knos/acceptance/7/mul_test.rb::MulTest#test_mul": "passed", "test/test_add.rb::AddTest#test_add": "passed"}
    assert got.accept == {".knos/acceptance/7/mul_test.rb::MulTest#test_mul"}
    assert got.results[got.sentinel] == "passed" and got.results[got.canary] == "failed"


def test_ruby_is_chosen_by_the_gemfile_or_a_gemspec_or_by_name(tmp_path):
    for name, files in (("gemfile", {"Gemfile": "\n"}), ("gemspec", {"w.gemspec": "\n"})):
        assert judge.runner_of(tree(tmp_path / name, files), {"issue": "7"}) == "ruby"
    assert judge.runner_of(tree(tmp_path / "named", {"README.md": "\n"}), {"runner": "ruby"}) == "ruby"
    assert judge.runner_of(tree(tmp_path / "none", {"README.md": "\n"}), {"issue": "7"}) == "python"
    assert judge.runner_of(tree(tmp_path / "py", {"Gemfile": "\n", ".knos/acceptance/7/test_x.py": "\n"}), {"issue": "7"}) == "python"
    assert {"Rakefile", ".rspec", "test/test_helper.rb", "spec/spec_helper.rb"} <= set(judge.protected_patterns({}, "ruby"))


@posix
@pytest.mark.skipif(not shutil.which("cargo"), reason="needs cargo")
def test_rust(tmp_path):
    v = variants(tmp_path, RUST,
                 good={"src/lib.rs": RUST["src/lib.rs"] + "\npub fn mul(a: i32, b: i32) -> i32 { a * b }\n"},
                 drops={"src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\npub fn mul(a: i32, b: i32) -> i32 { a * b }\n"})
    cache: dict = {}
    good = judge.judge(v["base"], v["good"], CFG, cache=cache)
    assert good["passed"] and good["evidence"]["runner"] == "rust", good["reasons"]
    drops = judge.judge(v["base"], v["drops"], CFG, cache=cache)       # deleting the unit test is seen
    assert not drops["passed"] and any("fewer than the base" in r for r in drops["reasons"]), drops["reasons"]


@posix
def test_a_plain_command_judges_any_language(tmp_path):
    v = variants(tmp_path, {"out.txt": "hello\n", ".knos/acceptance/7/check": "grep -q world out.txt\n"},
                 good={"out.txt": "hello\nworld\n"}, noop={"other.txt": "x\n"})
    good = judge.judge(v["base"], v["good"], CFG)
    assert good["passed"] and good["evidence"]["runner"] == "command"
    assert not judge.judge(v["base"], v["noop"], CFG)["passed"]
    same = judge.judge(v["good"], v["good"], CFG)
    assert "already pass on the base" in same["reasons"][0]


BOX = {
    "calc.py": "def double(x):\n    return x\n",
    ".knos/acceptance/7/blackbox.py":
        "import os, subprocess, sys\n"
        "got = subprocess.run([os.environ['KNOS_RUN'], sys.executable, '-c', 'import calc; print(calc.double(21))'],\n"
        "                     capture_output=True, timeout=60)\n"
        "sys.exit(0 if got.stdout.decode().strip().splitlines()[-1:] == ['42'] else 1)\n",
}


@posix
def test_the_black_box_check_cannot_be_forged_from_inside(tmp_path):
    forge = ("import os, sys\n"
             "def double(x):\n    return x\n"
             "open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i-ran'), 'w').close()\n"
             "os._exit(0)\n")                                 # the cheat that fools an exit-code check
    v = variants(tmp_path, BOX, good={"calc.py": "def double(x):\n    return 2 * x\n"}, forge={"calc.py": forge},
                 edits={"calc.py": "def double(x):\n    return 2 * x\n", ".knos/acceptance/7/blackbox.py": "raise SystemExit(0)\n"})
    good = judge.judge(v["base"], v["good"], CFG)
    assert good["passed"] and good["evidence"]["runner"] == "blackbox", good["reasons"]
    assert not judge.judge(v["base"], v["forge"], CFG)["passed"]
    assert judge.judge(v["base"], v["edits"], CFG)["reasons"] == ["touches protected path .knos/acceptance/7/blackbox.py"]


def test_a_suites_last_words_are_one_bounded_line_of_plain_text():
    said = "collected 3\r\n\x1b[31mFAILED\x1b[0m case 2:\texpected 42,\x00 got\x07 21\u202e\u200b\n\n"
    assert judge.last_words(said) == "collected 3 FAILED case 2: expected 42, got 21"
    assert judge.last_words("") == "" and judge.last_words(" \n\x1b[0m\x00") == ""
    long = judge.last_words("first line\n" + "x" * 400 + " the end")
    assert len(long) == 300 and long.endswith(" the end") and "first" not in long
    assert judge.last_words("a b c d", most=3) == "c d" and judge.last_words("abcdef", most=3) == "def"
    assert judge.last_words("caf\u00e9 \u00e7a va: 2 \u2260 3") == "caf\u00e9 \u00e7a va: 2 \u2260 3"      # text in any language stays


@posix
def test_a_failed_black_box_suite_says_its_last_words_in_the_reason(tmp_path):
    box = {**BOX, ".knos/acceptance/7/blackbox.py": BOX[".knos/acceptance/7/blackbox.py"].replace(
        "sys.exit(0 if", "ok = got.stdout.decode().strip().splitlines()[-1:] == ['42']\n"
                         "print('double(21): expected 42,\\x1b[31m got ' + got.stdout.decode().strip() + '\\x07\\n' + 'z' * 400 if not ok else 'ok')\n"
                         "sys.exit(0 if")}
    v = variants(tmp_path, box, good={"calc.py": "def double(x):\n    return 2 * x\n"}, wrong={"calc.py": "def double(x):\n    return 3 * x\n"})
    assert judge.judge(v["base"], v["good"], CFG)["reasons"] == []
    [why] = judge.judge(v["base"], v["wrong"], CFG)["reasons"]
    head = "pr: acceptance checks not passed: acceptance::blackbox (the suite's last words: "
    assert why.startswith(head) and why.endswith("z)") and len(why) == len(head) + 300 + 1
    assert "\x1b" not in why and "\x07" not in why and "\n" not in why
    short = {**box, ".knos/acceptance/7/blackbox.py": box[".knos/acceptance/7/blackbox.py"].replace("'z' * 400", "''")}
    v = variants(tmp_path / "short", short, wrong={"calc.py": "def double(x):\n    return 3 * x\n"})
    assert judge.judge(v["base"], v["wrong"], CFG)["reasons"] == [head + "double(21): expected 42, got 63)"]


PY = {
    "pkg/__init__.py": "def add(a, b):\n    return a + b\n",
    "tests/test_add.py": "from pkg import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    ".knos/acceptance/7/test_mul.py": "from pkg import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
}
SPY = '''
import os, pathlib, socket
def mul(a, b):
    return a * b
seen = {"uid": os.getuid(), "env": sorted(k for k in os.environ if k.startswith(("GITHUB", "SECRET", "KNOS", "ACTIONS"))),
        "wrote": False, "net": False}
try:
    pathlib.Path(os.environ.get("VICTIM", "%s")).write_text("passed=true")
    seen["wrote"] = True
except OSError:
    pass
try:
    socket.create_connection(("1.1.1.1", 53), timeout=1).close()
    seen["net"] = True
except OSError:
    pass
import json
pathlib.Path("spy.json").write_text(json.dumps(seen))
'''


@posix
def test_the_sandbox_keeps_pull_request_code_from_the_judges_files_and_the_network(tmp_path, monkeypatch):
    if not judge.sandbox_available():
        v = variants(tmp_path, PY, good={"pkg/__init__.py": PY["pkg/__init__.py"] + "def mul(a, b):\n    return a * b\n"})
        got = judge.judge(v["base"], v["good"], CFG, sandbox="require")
        assert not got["passed"] and "no sandbox on this machine" in got["reasons"][0]   # it refuses, never runs unboxed
        pytest.skip("no sandbox here (needs Linux with root or passwordless sudo)")
    victim = tmp_path / "judge-output.txt"
    victim.write_text("passed=false")
    monkeypatch.setenv("GITHUB_OUTPUT", str(victim))
    monkeypatch.setenv("SECRET_TOKEN", "s3cret")
    v = variants(tmp_path, PY, spy={"pkg/__init__.py": PY["pkg/__init__.py"] + SPY % victim})
    got = judge.judge(v["base"], v["spy"], CFG, sandbox="require", setup="cp spy.json /dev/null 2>/dev/null; true")
    assert got["passed"], got["reasons"]                               # an honest fix passes inside the sandbox
    assert got["evidence"]["sandbox"] == {"user": judge.SANDBOX_UID, "network": "setup only"}
    assert victim.read_text() == "passed=false"                        # it could not write the judge's file


@posix
def test_setup_runs_in_each_tree_before_its_tests(tmp_path):
    needs = "import pathlib\nfrom pkg import mul\n\n\ndef test_mul():\n    assert pathlib.Path('installed').exists() and mul(2, 3) == 6\n"
    v = variants(tmp_path, {**PY, ".knos/acceptance/7/test_mul.py": needs},
                 good={"pkg/__init__.py": PY["pkg/__init__.py"] + "def mul(a, b):\n    return a * b\n"})
    assert not judge.judge(v["base"], v["good"], CFG)["passed"]                     # without setup the check cannot pass
    got = judge.judge(v["base"], v["good"], CFG, setup="touch installed")
    assert got["passed"], got["reasons"]
    broke = judge.judge(v["base"], v["good"], CFG, setup="exit 3")
    assert not broke["passed"] and "setup failed (exit 3)" in broke["reasons"][0]


# ---- the gate: no pull request code runs ---------------------------------------------------------------------------

RUNS = [{"name": "tests (ubuntu)", "status": "completed", "conclusion": "failure", "details_url": "https://x/runs/9/job/1"},
        {"name": "lint", "status": "completed", "conclusion": "success", "details_url": "https://x/runs/9/job/2"},
        {"name": "prove / check", "status": "in_progress", "conclusion": None, "details_url": "https://x/runs/5/job/1"}]


def test_the_gate_refuses_a_description_that_says_tests_pass_when_a_check_failed(tmp_path):
    from sibyl_memory_client import MemoryClient
    store = history.SibylStore(MemoryClient.local(str(tmp_path / "sibyl.db"), tenant_id="knos-judge"))
    base = tree(tmp_path / "base", {"README.md": "x\n"})
    lie = judge.gate(base, "", store, "o/r", "agent", "Fixed the parser. All tests pass.", RUNS)
    assert not lie["passed"] and "tests (ubuntu)" in lie["reasons"][0] and lie["evidence"]["mode"] == "merge"
    assert judge.gate(base, "", store, "o/r", "agent", "Fixed the parser.", RUNS)["passed"]          # no claim made
    assert judge.gate(base, "", store, "o/r", "agent", "All tests pass.", RUNS[1:])["passed"]        # the claim is true
    assert judge.gate(base, "", store, "o/r", "agent", "All tests pass.", None)["passed"]            # GitHub unreadable
    learned = judge.gate(base, "", store, "o/r", "agent", "Fixed.", [])["evidence"]["required_by_history"]
    assert learned == ["tamper:false-claim"]                           # Sibyl remembers the false claim for this repo


def test_knos_own_jobs_are_not_evidence_about_the_pull_request(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    assert judge.claim_check("CI is green", RUNS) == []               # run 9 is this workflow run
    monkeypatch.setenv("GITHUB_RUN_ID", "5")
    assert "tests (ubuntu)" in judge.claim_check("CI is green", RUNS)[0]
    own = [{"name": "prove / check", "status": "completed", "conclusion": "failure", "details_url": ""}]
    assert judge.claim_check("CI is green", own) == []


def test_check_runs_waits_for_ci_only_when_the_description_makes_a_claim():
    calls, naps = [], []
    pending = {"check_runs": [{"name": "tests", "status": "in_progress"}]}
    done = {"check_runs": [{"name": "tests", "status": "completed", "conclusion": "failure"}]}

    def get(url):
        calls.append(url)
        return pending if len(calls) < 3 else done
    got = judge.check_runs("o/r", "a" * 40, wait=600, body="tests pass", get=get, sleep=naps.append)
    assert got == done["check_runs"] and len(calls) == 3 and naps == [15, 15]
    calls.clear()
    assert judge.check_runs("o/r", "a" * 40, wait=600, body="no claim", get=get, sleep=naps.append) == pending["check_runs"]
    assert len(calls) == 1

    def boom(url):
        raise OSError("down")
    assert judge.check_runs("o/r", "a" * 40, get=boom) is None


def test_cli_gate_writes_evidence_and_exits_1_on_a_false_claim(tmp_path, capsys):
    from knos.cli import main
    base = tree(tmp_path / "base", {"README.md": "x\n"})
    (tmp_path / "body.md").write_text("Done. CI is green.", encoding="utf-8")
    (tmp_path / "checks.json").write_text(json.dumps({"check_runs": RUNS}), encoding="utf-8")
    (tmp_path / "pr.diff").write_text("", encoding="utf-8")
    args = ["proof", "gate", "--base", str(base), "--diff", str(tmp_path / "pr.diff"), "--store", str(tmp_path / "mem"),
            "--repo", "o/r", "--agent", "a", "--body-file", str(tmp_path / "body.md"),
            "--checks-file", str(tmp_path / "checks.json"), "--evidence", str(tmp_path / "ev.json")]
    assert main(args) == 1
    said = capsys.readouterr().out
    assert "NO  claim: the description says CI is green" in said and "not proven" in said
    ev = json.loads((tmp_path / "ev.json").read_text())
    assert ev["passed"] is False and ev["evidence"]["checks_seen"] == 3
    assert (tmp_path / "mem" / "sibyl.db").exists()


@pytest.mark.skipif(not judge.sandbox_available(), reason="needs the sandbox")
def test_the_sandbox_reaches_an_interpreter_under_a_private_directory(tmp_path):
    """A judge installed in a virtualenv under a directory other users may not enter (a home directory, pipx) still
    runs: the directories above the interpreter are made traversable, never listable."""
    private = tmp_path / "home"
    (private / "bin").mkdir(parents=True)
    private.chmod(0o700)
    exe = private / "bin" / "python"
    exe.symlink_to(sys.executable)
    assert judge._sandbox_cannot_run(str(exe)) is None
    assert private.stat().st_mode & 0o007 == 0o001
    assert "No such file" in (judge._sandbox_cannot_run(str(private / "bin" / "missing")) or "")


def test_black_box_is_a_mechanical_test_that_agrees_with_the_runner_the_judge_picks(tmp_path):
    """knos.judge.black_box decides whether a bounty may be paid by its checks alone. The benchmark's bundles
    (docs/TAMPER.md): the three black-box ones pass it and the three that import the submission do not, and whatever
    passes it is run by the blackbox runner."""
    bench = Path(__file__).parent / "bench_tamper"

    def bundle(repo: Path, issue: str) -> dict:
        folder = repo / ".knos" / "acceptance" / issue
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    for sample in ("sample", "sample_node", "sample_ruby"):
        repo = bench / sample
        cfg = judge.proof_config((repo / ".knos" / "proof.toml").read_text(encoding="utf-8") if (repo / ".knos" / "proof.toml").is_file() else None)
        assert judge.black_box(bundle(repo, "2"), cfg) == "" and judge.runner_of(repo, {**cfg, "issue": "2"}) == "blackbox", sample
        assert judge.black_box(bundle(repo, "1"), cfg) == "load the pull request's code into the process that judges it", sample
        assert judge.runner_of(repo, {**cfg, "issue": "1"}) != "blackbox", sample
    entry = b'out=$("$KNOS_RUN" ./run)\n[ "$out" = 4 ]\n'
    ok = {"blackbox.sh": entry, "data/cases.json": b"[]"}
    assert judge.black_box(ok) == "" and judge.black_box(ok, {}) == "" and judge.black_box(ok, {"runner": "blackbox"}) == ""
    assert judge.black_box({"blackbox": entry}) == "" and judge.black_box({"blackbox.py": b"import os\nos.environ['KNOS_RUN']\n"}) == ""
    # each way out of the blackbox runner, as runner_of reads it; and each way the entry could load the submission
    for files, cfg, why in ((ok, {"runner": "python"}, "share a process with the pull request's code (runner `python`)"),
                            (ok, {"judge": {"runner": "command"}}, "share a process with the pull request's code (runner `command`)"),
                            (ok, {"judge": {"run": "make check"}}, "are a `[judge] run` command, run inside the pull request's tree"),
                            (ok, {"_error": "unreadable .knos/proof.toml"}, "cannot be checked: `.knos/proof.toml` is not valid TOML"),
                            ({"test_x.py": b"import calc\n"}, {}, "load the pull request's code into the process that judges it"),
                            ({"check.sh": entry}, {}, "load the pull request's code into the process that judges it"),
                            ({"deep/blackbox.sh": entry}, {}, "load the pull request's code into the process that judges it"),
                            ({"blackbox.sh": b"exit 0\n"}, {}, "never run the pull request's code through `$KNOS_RUN`"),
                            ({"blackbox.sh": entry, "lib.py": b"import os, sys\nsys.path.insert(0, os.environ['KNOS_TREE'])\n"}, {},
                             "open the pull request's tree themselves (`KNOS_TREE`)")):
        assert judge.black_box(files, cfg) == why, (files, cfg)
        named = tree(tmp_path / str(len(list(tmp_path.iterdir()))), {f".knos/acceptance/7/{n}": "x" for n in files})
        # where the judge's own choice of runner can be told from the files' names, it is not the blackbox runner either
        if "KNOS" not in why and "_error" not in cfg and "deep/blackbox.sh" not in files:
            assert judge.runner_of(named, {**cfg, "issue": "7"}) != "blackbox", (files, cfg)
    assert judge.proof_config(None) == {} and judge.proof_config('runner = "go"\n[judge]\nrun = "x"\n') == {"runner": "go", "judge": {"run": "x"}}
    assert judge.proof_config("runner = [") == {"_error": "unreadable .knos/proof.toml"}
