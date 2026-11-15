"""The verdict that crosses from the job that runs a pull request's code to the job that signs (knos.verdict_gate).

Every test here plays the judge machine as lost: what it hands over is whatever an attacker who escaped the sandbox
would write. The job that signs must refuse each of them before it asks GitHub for anything.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

from knos import judge
from knos import verdict_gate as vg

REPO, REPO_ID, RUN = "acme/widgets", 4242, 9001
BASE, HEAD, OTHER = "b" * 40, "a" * 40, "c" * 40
WORKFLOW = "d" * 40
BUNDLE = {"test_slug.py": b"def test_slug():\n    assert True\n"}
CHANGED = ["src/slug.py", "docs/slug.md"]


def env(**more) -> dict:
    return {"GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_ID": str(REPO_ID), "GITHUB_RUN_ID": str(RUN), "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_WORKFLOW_SHA": WORKFLOW, "GITHUB_SHA": BASE, "ImageOS": "ubuntu24", "ImageVersion": "20261001.1.0",
            "PULL": "7", "HEAD": HEAD, "ISSUE": "3", **more}


def accept(bundle: dict = BUNDLE) -> str:
    return hashlib.sha256("".join(f"{k}\0{hashlib.sha256(v).hexdigest()}\n" for k, v in sorted(bundle.items())).encode()).hexdigest()


def honest(**over) -> dict:
    v = {"v": 2, "kind": "judge", "passed": True, "repository_id": REPO_ID, "run": RUN, "attempt": 1, "workflow_sha": WORKFLOW, "pull": 7,
         "issue": 3, "head": HEAD, "base": BASE, "accept": accept(), "changed": vg.changed_hash(CHANGED), "changed_count": len(CHANGED),
         "runner": "python", "image": "ubuntu24-20261001.1.0"}
    return {**v, **over}


def line(v: dict) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


class GitHub:
    """GitHub's record, as the signing job reads it: one pull request, one comparison, one bundle on the base commit."""
    def __init__(self, files=None, head=HEAD, bundle=None, proof: str | None = None, root=("README.md",), repo_id=REPO_ID, pages=None):
        self.files = [{"filename": f, "status": "modified"} for f in CHANGED] if files is None else files
        self.head, self.bundle, self.proof, self.root, self.repo_id, self.pages = head, BUNDLE if bundle is None else bundle, proof, root, repo_id, pages
        self.asked: list[str] = []

    def __call__(self, path: str, data=None, method=None, **_kw):
        assert data is None and method is None, "the signing job's check only reads"
        self.asked.append(path)
        blobs = {hashlib.sha1(v).hexdigest(): v for v in self.bundle.values()}  # noqa: S324 - a git blob's name
        if path == f"repos/{REPO}/pulls/7":
            return {"number": 7, "head": {"sha": self.head}, "base": {"repo": {"id": self.repo_id}}}
        if path == f"repos/{REPO}/contents/.knos/acceptance?ref={BASE}":
            return [{"name": "3", "type": "dir", "sha": "e" * 40}]
        if path == f"repos/{REPO}/git/trees/{'e' * 40}?recursive=1":
            return {"tree": [{"path": k, "type": "blob", "mode": "100644", "sha": hashlib.sha1(v).hexdigest()} for k, v in self.bundle.items()]}  # noqa: S324
        if path.startswith(f"repos/{REPO}/git/blobs/"):
            return {"encoding": "base64", "content": base64.b64encode(blobs[path.rsplit("/", 1)[1]]).decode()}
        if path == f"repos/{REPO}/contents/.knos/proof.toml?ref={BASE}":
            if self.proof is None:
                err = OSError("not found")
                err.code = 404          # type: ignore[attr-defined]
                raise err
            return {"encoding": "base64", "content": base64.b64encode(self.proof.encode()).decode()}
        if path == f"repos/{REPO}/contents?ref={BASE}":
            return [{"name": n, "type": "file"} for n in self.root]
        if path == f"repos/{REPO}/compare/{BASE}...{HEAD}?per_page=1":
            return {"files": self.files}
        if path.startswith(f"repos/{REPO}/pulls/7/files?per_page=100&page="):
            return (self.pages or [])[int(path.rsplit("=", 1)[1]) - 1]
        raise AssertionError(f"the check asked GitHub for something it has no business with: {path}")


def check(text: str, github: GitHub | None = None, capsys=None, **more) -> tuple[int, str]:
    code = vg.main(["check"], env=env(VERDICT=text, **more), github=github or GitHub())
    return code, capsys.readouterr().out if capsys else ""


# ---- the honest verdict, and the same facts worked out twice ----------------------------------------------------------

def test_an_honest_verdict_is_read_held_and_checked_again_from_githubs_record(capsys):
    hub = GitHub()
    code, out = check(line(honest()), hub, capsys)
    assert code == 0, out
    assert "read as data and checked again here before anything is signed" in out
    for said in ("is the head of pull request #7", "the acceptance checks the judge ran are the 1 file(s)", "none of the 2 changed path(s)",
                 "the paths the judge was told of are exactly those"):
        assert said in out, out
    assert all("/issues" not in p and "comments" not in p for p in hub.asked)      # it reads the record and writes nothing


def test_what_the_judge_job_emits_is_exactly_what_the_signing_job_accepts(tmp_path, capsys):
    base = tmp_path / "base"
    (base / ".knos" / "acceptance" / "3").mkdir(parents=True)
    for name, body in BUNDLE.items():
        (base / ".knos" / "acceptance" / "3" / name).write_bytes(body)
    changed = tmp_path / "changed.txt"
    changed.write_text("".join(c + "\n" for c in CHANGED), encoding="utf-8")
    out_file = tmp_path / "out"
    assert vg.main(["emit", "--base", str(base), "--issue", "3", "--changed", str(changed)], env=env(GITHUB_OUTPUT=str(out_file))) == 0
    emitted = capsys.readouterr().out.strip()
    assert out_file.read_text(encoding="utf-8") == f"verdict={emitted}\n" and "\n" not in emitted
    assert json.loads(emitted) == honest() and len(emitted) < vg.MAX // 2
    assert set(json.loads(emitted)) == set(vg.SCHEMA)
    assert json.loads(emitted)["accept"] == judge.checks_hash(base / ".knos" / "acceptance" / "3")
    assert check(emitted)[0] == 0


def test_the_schema_has_no_field_of_free_text():
    """Every field is a boolean, a bounded whole number, or a string of a closed shape: nothing a later step could read
    as a sentence, a path, a name or a command."""
    for key, rule in vg.SCHEMA.items():
        if isinstance(rule, str):
            assert rule in (vg._HEX40, vg._HEX64, "judge", "|".join(vg.RUNNERS), r"[A-Za-z0-9._-]{0,48}"), key
        else:
            assert rule is bool or (isinstance(rule, tuple) and all(type(x) is int for x in rule)), key
    assert vg.RUNNERS == judge.RUNNERS


# ---- result substitution: a verdict for something else ----------------------------------------------------------------

@pytest.mark.parametrize("over, why", [
    ({"pull": 8}, "another pull request"),                  # the verdict of another pull request
    ({"head": OTHER}, "another head commit"),               # of another commit of this one
    ({"base": OTHER}, "another base commit"),               # judged against another base
    ({"issue": 4}, "another issue"),                        # another order's acceptance checks
    ({"repository_id": 4243}, "another repository"),        # another repository's run
    ({"run": RUN + 1}, "another run"),                      # a concurrent run's verdict
    ({"workflow_sha": OTHER}, "another commit of the workflow"),
    ({"attempt": 2}, "a later attempt"),
    ({"passed": False}, "did not pass"),
])
def test_a_verdict_about_anything_else_than_this_job_signs_for_is_refused(over, why, capsys):
    hub = GitHub()
    code, out = check(line(honest(**over)), hub, capsys)
    assert code == 1 and "nothing is signed" in out and why in out, out
    assert hub.asked == []          # refused on what the job knows itself, before GitHub is asked anything


def test_an_earlier_attempts_verdict_holds_when_only_the_signing_job_is_run_again(capsys):
    assert check(line(honest(attempt=1)), None, capsys, GITHUB_RUN_ATTEMPT="2")[0] == 0


def test_the_head_commit_is_githubs_not_the_verdicts(capsys):
    code, out = check(line(honest()), GitHub(head=OTHER), capsys)       # a commit was pushed after the judge ran
    assert code == 1 and "no longer the one that was judged" in out
    code, out = check(line(honest()), GitHub(repo_id=1), capsys)
    assert code == 1 and "not one of this repository" in out


def test_a_bundle_other_than_the_base_commits_is_refused(capsys):
    code, out = check(line(honest(accept="0" * 64)), None, capsys)       # the judge ran an easier suite and says so
    assert code == 1 and "not the ones on the base commit" in out
    lied = GitHub(bundle={"test_slug.py": b"def test_slug():\n    assert False\n"})
    code, out = check(line(honest()), lied, capsys)                      # ... or does not say so
    assert code == 1 and "not the ones on the base commit" in out


def test_a_changed_path_the_judges_rule_refuses_is_refused_here_too_whatever_the_judge_said(capsys):
    for path, status, code_ in ((".knos/acceptance/3/test_slug.py", "modified", "terms"), (".github/workflows/ci.yml", "added", "workflow"),
                                ("tests/test_old.py", "modified", "protected_test_edited"), ("tests/test_old.py", "removed", "protected_test_deleted")):
        assert judge.classify_path(path, {"runner": "python"}, status) == f"refused:{code_}"
        files = [{"filename": "src/slug.py", "status": "modified"}, {"filename": path, "status": status}]
        v = honest(changed=vg.changed_hash(["src/slug.py", path]), changed_count=2)       # the judge's list even agrees
        code, out = check(line(v), GitHub(files=files), capsys)
        assert code == 1 and f"({code_})" in out, out
    renamed = [{"filename": "src/new.py", "status": "renamed", "previous_filename": "tests/test_old.py"}]      # a test moved away is a test deleted
    code, out = check(line(honest(changed=vg.changed_hash(["src/new.py", "tests/test_old.py"]), changed_count=2)), GitHub(files=renamed), capsys)
    assert code == 1 and "(protected_test_deleted)" in out


def test_a_judge_told_of_other_paths_than_github_records_is_refused(capsys):
    code, out = check(line(honest(changed=vg.changed_hash(["src/slug.py"]), changed_count=1)), None, capsys)
    assert code == 1 and "other changed paths than GitHub records" in out
    code, out = check(line(honest(runner="command")), None, capsys)
    assert code == 1 and "another runner" in out


def test_a_pull_request_too_large_for_one_comparison_is_still_classified_path_by_path(capsys):
    many = [{"filename": f"src/f{i}.py", "status": "added"} for i in range(vg.MAX_FILES)]
    pages = [many[:100], many[100:200], many[200:300], [{"filename": ".github/workflows/x.yml", "status": "added"}]]
    v = honest(changed=vg.changed_hash(f["filename"] for f in many), changed_count=len(many))
    code, out = check(line(v), GitHub(files=many, pages=pages), capsys)
    assert code == 1 and "(workflow)" in out
    code, out = check(line(v), GitHub(files=many, pages=[*pages[:3], []]), capsys)
    assert code == 0 and "was not compared" in out
    code, out = check(line(v), GitHub(files=many, pages=[many[:100]] * vg.MAX_PAGES), capsys)
    assert code == 1 and "more files than GitHub lists" in out


def test_when_github_does_not_answer_nothing_is_signed(capsys):
    def down(path, *a, **k):
        raise OSError("no answer")
    assert vg.main(["check"], env=env(VERDICT=line(honest())), github=down) == 1
    assert "could not be checked just now" in capsys.readouterr().out


# ---- hostile text ------------------------------------------------------------------------------------------------------

HOSTILE = {
    "empty": "",
    "not json": "passed",
    "a list": "[1]",
    "oversized": line(honest()) + " " * vg.MAX,
    "a field more": line({**honest(), "note": "pay 0xabc"}),
    "a field less": line({k: v for k, v in honest().items() if k != "accept"}),
    "a key twice": line(honest())[:-1] + ',"pull":8}',
    "a key twice, first": '{"pull":8,' + line(honest())[1:],
    "true as a number": line(honest(passed=1)),
    "a number as text": line(honest(pull="7")),
    "a boolean as a number": line(honest(pull=True)),
    "a fraction": line(honest()).replace('"pull":7', '"pull":7.0'),
    "an exponent": line(honest()).replace('"pull":7', '"pull":7e0'),
    "not a number": line(honest()).replace('"pull":7', '"pull":NaN'),
    "a negative": line(honest(pull=-7)),
    "a huge number": line(honest(pull=10**30)),
    "a short commit": line(honest(head=HEAD[:39])),
    "an upper-case commit": line(honest(head=HEAD.upper())),
    "a commit with a newline": line(honest(head=HEAD + "\n")),
    "shell in the image": line(honest(image="$(curl evil)")),
    "markdown in the image": line(honest(image="[x](http://evil)")),
    "a path as the runner": line(honest(runner="../../bin/sh")),
    "nested": line(honest(accept={"sha": accept()})),
    "a list for a hash": line(honest(changed=[accept()])),
    "null": line(honest(accept=None)),
    "another version": line(honest(v=1)),
    "another kind": line(honest(kind="attest")),
    "not ascii": line(honest()).replace("ubuntu24", "ubuntu٢٤"),
    "an escape that hides a character": line(honest()).replace("ubuntu24", "ubuntu\\u202e"),
    "a control character": line(honest()).replace("ubuntu24", "ubuntu\x1b[2K"),
    "a null byte": line(honest()) + "\x00",
    "deeply nested": "[" * 5000 + "]" * 5000,
    "two objects": line(honest()) + line(honest(pull=8)),
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_hostile_text_is_refused_before_github_is_asked_anything(name, capsys):
    hub = GitHub()
    code, out = check(HOSTILE[name], hub, capsys)
    assert code == 1 and "nothing is signed" in out and hub.asked == [], (name, out)
    # what is said of it never repeats it: the refusal is one of the module's own sentences
    assert "evil" not in out and "0xabc" not in out and "\x1b" not in out
    with pytest.raises(vg.Refused):
        vg.read(HOSTILE[name])


def test_a_refusal_never_repeats_a_changed_paths_own_characters(capsys):
    path = ".github/workflows/x.yml\n::set-output name=verdict::ok `rm -rf` <img>"
    files = [{"filename": path, "status": "added"}]
    code, out = check(line(honest(changed=vg.changed_hash([path]), changed_count=1)), GitHub(files=files), capsys)
    assert code == 1 and "(workflow)" in out
    assert "::set-output" not in out and "`" not in out and "<img>" not in out and out.count("\n") <= 2


# ---- a verdict handed over as a file: links, folders, sizes, a second file ---------------------------------------------

def test_a_verdict_file_is_one_small_plain_file_with_one_name(tmp_path, capsys):
    good = tmp_path / "verdict.json"
    good.write_text(line(honest()), encoding="ascii")
    assert vg.read(vg.read_file(good)) == honest()
    assert vg.main(["check", "--file", str(good), "--offline"], env=env()) == 0
    capsys.readouterr()
    big = tmp_path / "big.json"
    big.write_text(line(honest()) + " " * (vg.MAX + 1), encoding="ascii")
    binary = tmp_path / "binary.json"
    binary.write_bytes(line(honest()).encode() + b"\xff")
    for bad in (big, binary, tmp_path, tmp_path / "missing.json"):
        with pytest.raises(vg.Refused):
            vg.read_file(bad)
    assert vg.main(["check", "--file", str(big), "--offline"], env=env()) == 1
    assert "larger than a verdict is" in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="links and named pipes as a POSIX runner has them")
def test_a_link_a_second_name_or_a_pipe_in_place_of_the_verdict_is_refused(tmp_path, capsys):
    secret = tmp_path / "secret"
    secret.write_text(line(honest()), encoding="ascii")       # even a link to a well-formed verdict is not a verdict
    link = tmp_path / "verdict.json"
    link.symlink_to(secret)
    with pytest.raises(vg.Refused, match="a link"):
        vg.read_file(link)
    assert vg.main(["check", "--file", str(link), "--offline"], env=env()) == 1
    assert "is a link" in capsys.readouterr().out
    hard = tmp_path / "hard.json"
    os.link(secret, hard)
    with pytest.raises(vg.Refused, match="one name"):
        vg.read_file(hard)
    pipe = tmp_path / "pipe.json"
    os.mkfifo(pipe)
    with pytest.raises(vg.Refused, match="not a plain file"):     # and reading it does not wait for a writer
        vg.read_file(pipe)
    folder = tmp_path / "linked"
    folder.symlink_to(tmp_path / "artifact", target_is_directory=True)
    (tmp_path / "artifact").mkdir()
    (tmp_path / "artifact" / "verdict.json").write_text(line(honest()), encoding="ascii")
    assert vg.main(["check", "--file", str(folder), "--offline"], env=env()) == 1


def test_an_artifact_two_jobs_wrote_into_is_not_a_verdict(tmp_path):
    """An artifact name shared with a concurrent upload: the folder then holds more than the one file."""
    art = tmp_path / "artifact"
    art.mkdir()
    (art / "verdict.json").write_text(line(honest()), encoding="ascii")
    assert vg.read(vg.from_folder(art)) == honest()
    (art / "verdict (1).json").write_text(line(honest(pull=8)), encoding="ascii")
    with pytest.raises(vg.Refused, match="something other than the one verdict file"):
        vg.from_folder(art)
    (art / "verdict (1).json").unlink()
    (art / "verdict.json").unlink()
    (art / "VERDICT.JSON").write_text(line(honest()), encoding="ascii")
    with pytest.raises(vg.Refused):
        vg.from_folder(art)


# ---- the runner, from names alone, is the judge's own answer ----------------------------------------------------------

@pytest.mark.parametrize("bundle, root, proof", [
    (["test_a.py"], [], ""), (["a_test.go"], [], ""), (["a.rs"], [], ""), (["a.test.mjs"], [], ""), (["check.sh"], [], ""),
    (["blackbox.py", "data/in.txt"], [], ""), (["cases.txt"], ["Gemfile"], ""), (["cases.txt"], ["x.gemspec"], ""), (["cases.txt"], [], ""),
    (["test_a.py"], [], 'runner = "node"\n'), (["test_a.py"], [], '[judge]\nrunner = "rust"\n'), (["test_a.py"], [], '[judge]\nrun = "make check"\n'),
])
def test_the_runner_worked_out_from_names_is_the_one_the_judge_works_out_from_the_tree(tmp_path, bundle, root, proof):
    base = tmp_path / "base"
    for name in bundle:
        f = base / ".knos" / "acceptance" / "3" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    for name in root:
        (base / name).write_text("x", encoding="utf-8")
    cfg = judge.proof_config(proof)
    assert vg.runner_from(cfg, bundle, root) == judge.runner_of(base, {**cfg, "issue": "3"})


def test_a_runner_the_configuration_names_and_knos_does_not_have_is_refused():
    with pytest.raises(vg.Refused):
        vg.runner_from({"runner": "perl"}, ["test_a.py"], [])


# ---- attest.yml: the first job's verdict, before `knos attest` reads it -----------------------------------------------

RERUN = {"v": 1, "reexecuted": True, "passed": True, "sentence": "this judge ran the suite itself", "order": "4Nd1mYw7sBfGq2tR8xKpLhVz3cJe6uA9oTiWnQbXyZaD",
         "repository": REPO, "pull": 7, "issue": 3, "head": HEAD, "base": BASE, "accept": accept(), "assurance": "black-box", "image": {},
         "artifact": {"base": "1" * 64, "pr": "2" * 64}, "environment": {"knos": "0.3.18", "runner_os": "Linux"}, "reasons": [],
         "verdict": "accepted", "reason": ""}


def test_attests_verdict_is_held_to_what_every_reader_reads_the_same_way(capsys):
    assert vg.main(["shape"], env={"KNOS_RERUN": line(RERUN)}) == 0
    assert vg.main(["shape"], env={"KNOS_RERUN": line({"v": 1, "reexecuted": False, "sentence": "x", "environment": {}})}) == 0
    assert vg.main(["shape"], env={}) == 0                       # with none, `knos attest` says what is missing
    capsys.readouterr()
    hostile = {
        "a key twice": line(RERUN)[:-1] + ',"pull":8}',
        "a field more": line({**RERUN, "token": "x"}),
        "oversized": line({**RERUN, "reasons": ["x" * 200] * 6, "sentence": "y" * 300, "environment": {str(i): "z" * 200 for i in range(16)}}) + " " * 8192,
        "a long reason": line({**RERUN, "reason": "x" * 301}),
        "too many reasons": line({**RERUN, "reasons": ["x"] * 7}),
        "nested twice": line({**RERUN, "image": {"ref": {"a": "b"}}}),
        "a control character": line(RERUN).replace("black-box", "black\x1b[2K"),
        "not ascii": line(RERUN).replace("black-box", "blаck-box"),
        "a commit that is not one": line({**RERUN, "head": "HEAD"}),
        "a repository that is a path": line({**RERUN, "repository": "a/b/../../c"}),
        "a fraction": line(RERUN).replace('"pull":7', '"pull":7.5'),
        "a list": "[]",
    }
    for name, text in hostile.items():
        assert vg.main(["shape"], env={"KNOS_RERUN": text}) == 1, name
        assert "nothing is signed" in capsys.readouterr().out, name


def test_the_shape_check_accepts_every_verdict_the_rerun_job_writes(tmp_path):
    """What knos.flow writes for a run that re-executed nothing, one that passed and one that could not decide."""
    from knos import flow
    plan = {k: RERUN[k] for k in ("order", "repository", "pull", "issue", "head", "base", "accept")} | {"image": ""}
    judged = {"passed": True, "verdict": "accepted", "reason": "", "assurance": "black-box", "reasons": [],
              "evidence": {"artifact": {"base": "1" * 64, "pr": "2" * 64}}}
    for v in (flow._rerun_verdict(None, env()), flow._rerun_verdict(plan, env(), judged),
              flow._rerun_verdict(plan, env(), why="the judge could not run here (OSError: no sandbox)")):
        text = line(v)
        vg.shape(text)
        assert not isinstance(flow._rerun_read(text), str)
    assert set(flow._RERUN_KEYS) | {"verdict", "reason"} == vg._RERUN_KEYS


def test_the_module_reaches_nothing_a_signing_job_does_not_install():
    import ast
    tree = ast.parse(Path(vg.__file__).read_text(encoding="utf-8"))
    top = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert top <= {"argparse", "base64", "hashlib", "json", "os", "re", "stat", "sys", "urllib"}, top
    local = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level}
    assert local <= {None}, local       # `from . import judge`, inside the two functions that need its rule
