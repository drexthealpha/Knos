"""`knos accept init`: a black-box acceptance bundle made from a reference implementation (knos.accept).

The reference here is a slugify command that reads a line on stdin and prints the answer. The bundle made from it is held
to what docs/TAMPER.md asks of one: `judge.black_box` says it is black-box, the real judge accepts a right fix and rejects
a wrong one, the reference passes its own bundle and a command that only echoes does not."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from knos import accept, cli, judge

posix = pytest.mark.skipif(os.name == "nt", reason="the judge runs on ubuntu-latest")

REFERENCE = "import re, sys\nprint(re.sub(r'[^a-z0-9]+', '-', sys.stdin.readline().lower()).strip('-'))\n"
WRONG = "import re, sys\nprint(re.sub(r'[^a-z0-9]+', '-', sys.stdin.readline().lower()))\n"       # forgets to strip the ends


@pytest.fixture
def ref(tmp_path) -> str:
    """The reference command: python on a script that lives outside the repository."""
    script = tmp_path / "reference.py"
    script.write_text(REFERENCE, encoding="utf-8")
    return shlex.join([sys.executable, str(script)])


def script(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return shlex.join([sys.executable, str(path)])


# ---- the inputs -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", accept.KINDS)
def test_inputs_are_distinct_single_lines_edge_cases_first_and_the_same_for_a_seed(kind):
    got = accept.inputs(kind, 40, seed=7)
    assert got == accept.inputs(kind, 40, seed=7) and got != accept.inputs(kind, 40, seed=8)
    assert len(got) == len(set(got)) == 40 and all("\n" not in x and "\r" not in x and len(x) <= 100 for x in got)
    assert got[:len(accept._EDGES[kind])] == accept._EDGES[kind]                      # the edge cases are in, and first
    assert accept.inputs(kind, 3, seed=7) == accept._EDGES[kind][:3] and accept.inputs(kind, 1, seed=1) == accept._EDGES[kind][:1]
    if kind != "text":
        assert all(x == "" or all(w.lstrip("-").isdigit() for w in x.split()) for x in got)


def test_an_unknown_kind_of_input_is_refused_in_words():
    with pytest.raises(accept.Refused, match="--input is one of text, int, ints; 'floats' is none of them"):
        accept.inputs("floats", 5, 1)


def test_answers_are_compared_without_trailing_spaces_and_blank_lines_and_nothing_else():
    assert accept.norm("a  \nb\t \n\n\n") == "a\nb" and accept.norm("a\r\nb\r\n") == "a\nb" and accept.norm("") == "" and accept.norm("\n") == ""
    assert accept.norm("  a") == "  a" and accept.norm("A") != accept.norm("a") and accept.norm("a\n\nb") == "a\n\nb"


# ---- recording the reference ----------------------------------------------------------------------------------------------
def test_the_reference_is_run_on_each_input_and_its_answers_are_recorded(ref):
    got = accept.record(shlex.split(ref), ["Hello, World!", "  Rock & Roll -- 2  ", ""])
    assert got == [{"input": "Hello, World!", "output": "hello-world"}, {"input": "  Rock & Roll -- 2  ", "output": "rock-roll-2"}, {"input": "", "output": ""}]


def test_a_reference_that_fails_wavers_or_is_missing_is_refused_with_the_case(tmp_path, monkeypatch):
    fails = script(tmp_path, "fails.py", "import sys\nline = sys.stdin.readline()\nsys.exit('boom on ' + line.strip()) if 'b' in line else print('ok')\n")
    with pytest.raises(accept.Refused, match=r"exited 1 on case 2, the input 'b': boom on b"):
        accept.record(shlex.split(fails), ["a", "b"])
    wavers = script(tmp_path, "wavers.py", "import random\nprint(random.random())\n")
    with pytest.raises(accept.Refused, match=r"answered case 1, the input 'x', differently the second time: a check needs one answer"):
        accept.record(shlex.split(wavers), ["x"])
    silent = script(tmp_path, "silent.py", "pass\n")
    with pytest.raises(accept.Refused, match="printed nothing for every input"):
        accept.record(shlex.split(silent), ["x", "y"])
    with pytest.raises(accept.Refused, match="the reference command was not found: 'no-such-reference-command'"):
        accept.record(["no-such-reference-command"], ["x"])
    monkeypatch.setattr(accept, "TIMEOUT", 1)
    slow = script(tmp_path, "slow.py", "import time\ntime.sleep(5)\n")
    with pytest.raises(accept.Refused, match="took more than 1 seconds on the input 'x'"):
        accept.record(shlex.split(slow), ["x"])


# ---- the bundle ---------------------------------------------------------------------------------------------------------
def test_the_bundle_is_black_box_and_the_reference_passes_it_while_an_echo_does_not(tmp_path, ref):
    made = accept.scaffold(tmp_path / "repo", 12, ref, run="python3 slug.py", cases=25, kind="text", seed=99)
    folder = tmp_path / "repo" / ".knos" / "acceptance" / "12"
    assert made.folder == folder and made.files == ("blackbox.py", "cases.json", "README.md") and (made.cases, made.seed) == (25, 99)
    files = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert sorted(files) == ["README.md", "blackbox.py", "cases.json"] and judge.black_box(files) == ""        # black-box by the mechanical test
    assert b"KNOS_RUN" in files["blackbox.py"] and not any(b"KNOS_TREE" in raw for raw in files.values())
    spec = json.loads(files["cases.json"])
    assert spec["run"] == ["python3", "slug.py"] and spec["input"] == "text" and spec["seed"] == 99 and spec["issue"] == 12 and len(spec["cases"]) == 25
    assert spec["cases"][0] == {"input": "", "output": ""} and {"input": "Hello, World!", "output": "hello-world"} in spec["cases"]
    assert "reference.py" not in files["cases.json"].decode()                                                   # where the funder keeps the reference is not published
    # the same seed gives the same cases
    again = accept.scaffold(tmp_path / "again", 12, ref, cases=25, seed=99)
    assert json.loads((again.folder / "cases.json").read_text())["cases"] == spec["cases"]
    assert json.loads((again.folder / "cases.json").read_text())["run"] == shlex.split(ref)                      # --run defaults to --from


@posix
def test_the_real_judge_accepts_a_right_fix_and_rejects_a_wrong_one(tmp_path, ref):
    run = shlex.join([sys.executable, "slug.py"])
    base = tmp_path / "base"
    accept.scaffold(base, 7, ref, run=run, cases=30, seed=5)
    (base / "slug.py").write_text("import sys\nprint('todo')\n", encoding="utf-8")                              # the base does not solve it
    for name, body in (("good", REFERENCE), ("wrong", WRONG), ("echo", "import sys\nprint(sys.stdin.readline().strip())\n")):
        shutil.copytree(base, tmp_path / name)
        (tmp_path / name / "slug.py").write_text(body, encoding="utf-8")
    cfg = {"issue": "7"}
    good = judge.judge(base, tmp_path / "good", cfg)
    assert good["passed"] and good["evidence"]["runner"] == "blackbox", good["reasons"]
    for bad in ("wrong", "echo"):
        got = judge.judge(base, tmp_path / bad, cfg)
        assert not got["passed"], bad
    # and the pull request cannot touch the check
    shutil.copytree(base, tmp_path / "edits")
    (tmp_path / "edits" / "slug.py").write_text(REFERENCE, encoding="utf-8")
    (tmp_path / "edits" / ".knos" / "acceptance" / "7" / "cases.json").write_text("{}", encoding="utf-8")
    assert judge.judge(base, tmp_path / "edits", cfg)["reasons"] == ["touches protected path .knos/acceptance/7/cases.json"]


def test_the_judge_says_which_case_failed_and_what_it_printed(tmp_path, ref):
    made = accept.scaffold(tmp_path / "repo", 3, ref, cases=10, seed=2)
    module = _load(made.folder)
    wrong = lambda argv, stdin: (0, accept.norm(WRONG_OUT(stdin)).encode() + b"\n", b"")  # noqa: E731
    why = module.check(wrong)
    assert why.startswith("case ") and ", the input " in why and "it printed" in why and "expected" in why
    assert module.check(lambda argv, stdin: (3, b"", b"no such file\nslug.py")) == "case 1, the input '': the command exited 3: no such file slug.py"
    import subprocess
    def slow(argv, stdin):
        raise subprocess.TimeoutExpired(argv, 60)
    assert module.check(slow) == "case 1, the input '': the command took more than 60 seconds"
    assert module.check(lambda argv, stdin: (0, b"\xff\xfe", b"")).startswith("case 1")             # bytes that are not text are an answer that differs, not a crash


def WRONG_OUT(stdin: bytes) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", stdin.decode().lower())


def _load(folder: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bundle_under_test", folder / "blackbox.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_readme_says_what_the_bundle_cannot_do_and_a_table_of_the_answers_does_pass(tmp_path, ref):
    made = accept.scaffold(tmp_path / "repo", 4, ref, run="python3 slug.py", cases=12, seed=1)
    readme = (made.folder / "README.md").read_text(encoding="utf-8")
    assert "12 inputs (text, seed 1)" in readme and "`python3 slug.py`" in readme and "/knos fund <amount>` on issue 4" in readme
    assert "answer exactly them from a table" in readme and "write that as `blackbox.py` yourself" in readme and "KNOS_TREE" not in readme
    # the limit, as a test: a table of the recorded answers passes, which is why more cases and a generating check exist
    table = {c["input"]: c["output"] for c in json.loads((made.folder / "cases.json").read_text())["cases"]}
    module = _load(made.folder)
    assert module.check(lambda argv, stdin: (0, (table[stdin.decode().rstrip("\n")] + "\n").encode(), b"")) is None


# ---- refusals leave nothing ---------------------------------------------------------------------------------------------
def test_scaffold_refuses_in_words_and_leaves_nothing_behind(tmp_path, ref):
    root = tmp_path / "repo"
    for kwargs, word in (({"issue": 0}, "--issue is the issue's number"), ({"issue": True}, "--issue is the issue's number"),
                         ({"issue": 1, "cases": 0}, "--cases is from 1 to 200"), ({"issue": 1, "cases": 201}, "--cases is from 1 to 200"),
                         ({"issue": 1, "kind": "floats"}, "--input is one of"), ({"issue": 1, "reference": ""}, "--from is empty"),
                         ({"issue": 1, "reference": "echo 'unclosed"}, "--from is not a command line"),
                         ({"issue": 1, "run": ""}, None), ({"issue": 1, "reference": "no-such-reference-command"}, "was not found")):
        args = {"reference": ref, **kwargs}
        if word is None:
            accept.scaffold(root, args.pop("issue"), args.pop("reference"), **args)       # an empty --run is the same as none: it defaults
            shutil.rmtree(root)
            continue
        with pytest.raises(accept.Refused, match=word):
            accept.scaffold(root, args.pop("issue"), args.pop("reference"), **args)
        assert not (root / ".knos").exists(), kwargs
    # an echo cannot be told from a right answer by these inputs: nothing is left behind
    echo = script(tmp_path, "echo.py", "import sys\nprint(sys.stdin.readline().strip())\n")
    with pytest.raises(accept.Refused, match="only prints its input back passes this bundle"):
        accept.scaffold(root, 9, echo, cases=5, seed=1)
    assert not (root / ".knos" / "acceptance" / "9").exists()
    # a folder that is there is not replaced without --force
    accept.scaffold(root, 2, ref, cases=5, seed=1)
    (root / ".knos" / "acceptance" / "2" / "mine.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(accept.Refused, match="exists already"):
        accept.scaffold(root, 2, ref, cases=5, seed=1)
    assert (root / ".knos" / "acceptance" / "2" / "mine.txt").read_text(encoding="utf-8") == "keep"
    accept.scaffold(root, 2, ref, cases=6, seed=2, force=True)
    assert len(json.loads((root / ".knos" / "acceptance" / "2" / "cases.json").read_text())["cases"]) == 6


def test_your_own_inputs_replace_the_generated_ones(tmp_path, ref):
    given = tmp_path / "in.txt"
    given.write_text("Hello, World!\nHello, World!\nRock & Roll\n\n", encoding="utf-8")
    made = accept.scaffold(tmp_path / "repo", 5, ref, given=given)
    spec = json.loads((made.folder / "cases.json").read_text())
    assert [c["input"] for c in spec["cases"]] == ["Hello, World!", "Rock & Roll", ""] and spec["input"] == "given" and spec["seed"] is None and made.seed is None
    assert "3 inputs (given, seed none)" in (made.folder / "README.md").read_text(encoding="utf-8")
    for body, word in (("", "holds 0 distinct lines"), ("x" * 2001, "at most 2000 characters"), ("a KNOS_TREE b\n", "KNOS_TREE")):
        given.write_text(body, encoding="utf-8")
        with pytest.raises(accept.Refused, match=word):
            accept.scaffold(tmp_path / "other", 6, ref, given=given)
    with pytest.raises(accept.Refused, match="cannot be read as text"):
        accept.scaffold(tmp_path / "other", 6, ref, given=tmp_path / "missing.txt")
    assert not (tmp_path / "other" / ".knos").exists()


# ---- the command --------------------------------------------------------------------------------------------------------
def say(capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    rc = cli.main(list(args))
    return rc, capsys.readouterr().out


def test_knos_accept_init_writes_the_bundle_and_says_what_to_do_next(tmp_path, capsys, ref):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    rc, text = say(capsys, "accept", "init", "--issue", "12", "--from", ref, "--cases", "20", "--seed", "4", "--in", str(repo))
    lines = text.splitlines()
    assert rc == 0 and lines[0] == "Wrote .knos/acceptance/12/ (blackbox.py, cases.json, README.md): 20 cases recorded from the reference command, seed 4."
    assert lines[1] == "The reference passes its own bundle, and a command that only echoes its input does not."
    assert lines[2].startswith("Commit it to the default branch before issue #12 is funded (/knos fund <amount>): it is black-box, so Knos pays on this check alone.")
    assert (repo / ".knos" / "acceptance" / "12" / "blackbox.py").is_file()
    # again without --force: one line, and the folder is untouched
    rc, text = say(capsys, "accept", "init", "--issue", "12", "--from", ref, "--in", str(repo))
    assert rc == 1 and text == f"{repo / '.knos' / 'acceptance' / '12'} exists already. Look at it, or give --force to replace it.\n"
    rc, text = say(capsys, "accept", "init", "--issue", "13", "--from", ref, "--inputs", str(tmp_path / "x"), "--cases", "5", "--in", str(repo))
    assert (rc, text) == (1, "Give --inputs or --cases, not both: --inputs is the cases.\n")
    rc, text = say(capsys, "accept", "init", "--issue", "13", "--from", "no-such-reference-command", "--in", str(repo))
    assert rc == 1 and text == "the reference command was not found: 'no-such-reference-command'\n"
    rc, text = say(capsys, "accept", "init", "--issue", "13", "--from", ref, "--in", str(tmp_path))                  # not a repository
    assert rc == 1 and "is not inside a git repository" in text
    assert say(capsys, "accept", "init", "--from", ref)[0] == 2                                                      # --issue is required


def test_knos_accept_is_listed_under_the_repositorys_workflows_and_has_its_own_help(capsys):
    rc, text = say(capsys, "--help")
    assert rc == 0 and "│ accept " in text[text.index("For a repository's workflows"):text.index("For money")]
    rc, text = say(capsys, "accept")
    assert rc == 0 and "init" in text
    rc, text = say(capsys, "accept", "init", "--help")
    assert rc == 0 and all(opt in text for opt in ("--from", "--cases", "--issue", "--input", "--run", "--seed", "--inputs", "--in", "--force"))


# ---- what the site's task form is tested against ----------------------------------------------------------------------
RECORDED = Path(__file__).resolve().parent / "web" / "recorded" / "acceptance_bundle.json"
RECORDED_NOTE = ("What the site's form for a task with no repository (web/task.js) must write: the command line split as shlex.split(posix=True) does, and the three files accept.bundle "
                 "makes from the pairs given (answers normalised by accept.norm), for the inputs below. tests/web/site.mjs runs web/task.js on the same inputs and compares byte for byte. "
                 "Written by `python tests/test_accept.py`; test_the_sites_recorded_bundles_are_what_accept_bundle_writes fails when they differ from what the code writes now.")
COMMANDS = ["python3 slugify.py", "a 'b c' \"d e\"", "a\\ b", '"a\\"b"', '"a\\\\b"', '"a\\nb"', "''", 'a "" b', "it's", "a\\", '"unterminated', "a\tb\nc  d", '--x="a b"', "'a'\"b\"c", "node \"my solution.js\" --flag 'a b' it\\'s", "  lead and trail  ", ""]
PAIRS = {
    "plain": (12, "python3 slugify.py", [("Hello, World!", "hello-world\n"), ("  Spaces  ", "spaces"), ("a--b", "a-b"), ("100%", "100"), ("x", "x")]),
    "text that json escapes": (7, "node \"my solution.js\" --flag 'a b' it\\'s", [("École \"quoted\"", "ecole-quoted  \n\n"), ("中文 and 😀", "\n\nzhong-wen\r\nsecond line   \n"), ("back\\slash", "back/slash"),
                                                                                  ("tab\there", "tab here"), ("  keep the spaces  ", "  indented answer"), ("é", "e")]),
    "a large issue number and an empty answer": (1_000_000_000, "./run.sh", [("one", "1"), ("two", "2"), ("three", ""), ("four", "4"), ("five", "5"), ("six", "6"), ("seven", "7")]),
}


def recorded_bundles() -> dict:
    import shlex as _shlex
    shells = []
    for command in COMMANDS:
        try:
            shells.append({"command": command, "argv": _shlex.split(command)})
        except ValueError:
            shells.append({"command": command, "error": True})
    bundles = []
    for name, (issue, command, pairs) in PAIRS.items():
        argv = _shlex.split(command)
        cases = [{"input": i, "output": accept.norm(o)} for i, o in pairs]
        files = accept.bundle(issue, argv, cases, "given", None)
        bundles.append({"name": name, "issue": issue, "command": command, "argv": argv, "pairs": [{"input": i, "output": o} for i, o in pairs], "cases": cases,
                        "files": {k: v.decode("utf-8") for k, v in files.items()}})
    return {"note": RECORDED_NOTE, "shell": shells, "bundles": bundles, "limits": {"MAX_CASES": accept.MAX_CASES, "MAX_INPUT": accept.MAX_INPUT}}


def test_the_sites_recorded_bundles_are_what_accept_bundle_writes():
    assert json.loads(RECORDED.read_text(encoding="utf-8")) == json.loads(json.dumps(recorded_bundles())), "regenerate: python tests/test_accept.py"
    # and every one of them is black-box, as the site says
    for b in json.loads(RECORDED.read_text(encoding="utf-8"))["bundles"]:
        assert judge.black_box({k: v.encode("utf-8") for k, v in b["files"].items()}) == ""


if __name__ == "__main__":
    RECORDED.write_text(json.dumps(recorded_bundles(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", RECORDED)
