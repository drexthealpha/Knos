"""`knos preflight` (knos.preflight): the supplier learns what an order holds a change to before submitting it.

Offline from a terms file; exit 0 only when ready; a refusal comes with its code, its two sentences and the exact
line of the terms; a test the supplier adds is allowed and not counted; what was refused before under the same terms
is recalled from the memory engine, and with the engine absent it works and says memory is off."""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path

import pytest

from knos import cli, ghwords, preflight, terms
from knos.proof import history

ROOT = Path(__file__).resolve().parents[1]
MERGE = {"accept": "", "checks": [{"app": 15368, "name": "lint"}, {"app": 15368, "name": "unit"}], "deny": [".github/**", ".knos/**"],
         "mode": "merge", "paths": ["src/**", "tests/**"], "reserve": 7, "v": 1}
TESTS = {**MERGE, "mode": "tests", "accept": "cd" * 32, "paths": []}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True, encoding="utf-8")


@pytest.fixture()
def work(repo):
    """The conftest's repository with a test suite on its base branch, and a branch `work` to change things on."""
    (repo / "tests").mkdir()
    (repo / "tests" / "test_auth.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")
    (repo / "tests" / "conftest.py").write_text("", encoding="utf-8")
    (repo / "pyproject.toml").write_text('[project]\nname = "demo"\n\n[tool.pytest.ini_options]\naddopts = "-q"\n', encoding="utf-8")
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "tests")
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-qb", "work")
    return repo


@pytest.fixture()
def commands():
    """`knos preflight` and `knos keep` on the command line, whether or not cli._MODULES names the module yet."""
    cli.load()
    if "preflight" not in {c.name for c in cli._app.registered_commands}:
        preflight.register(cli._app, cli._HELP)


def _terms_file(folder: Path, t: dict, pretty: bool = False) -> Path:
    path = folder / "terms.json"
    path.write_text(json.dumps(t, indent=1, sort_keys=True) if pretty else terms.canonical(t).decode("ascii"), encoding="utf-8")
    return path


def _by_path(report: dict) -> dict:
    return {r["path"]: r for r in report["changes"]}


def test_the_terms_are_read_from_their_line_a_pretty_file_or_a_published_template():
    one = preflight.read_terms(terms.canonical(MERGE).decode("ascii"))
    assert one["hash"] == terms.terms_hash(MERGE) == preflight.read_terms(json.dumps(MERGE, indent=2))["hash"]
    published = json.loads((ROOT / "terms" / "bugfix" / "1.json").read_text(encoding="utf-8"))
    got = preflight.read_terms(json.dumps(published))
    assert got["hash"] == published["terms_hash"] and got["source"] == "template bugfix 1"
    for bad in ("not json", "{}", json.dumps({**MERGE, "mode": "vibes"})):
        with pytest.raises(preflight.Unreadable):
            preflight.read_terms(bad)


def test_a_change_inside_the_terms_is_ready_and_one_outside_names_the_line_that_says_so(work, tmp_path):
    (work / "src" / "auth.py").write_text("def login():\n    return 1\n", encoding="utf-8")
    report = preflight.check(work, _terms_file(tmp_path, MERGE, pretty=True), use_memory=False)
    assert report["ready"] is True and report["fixes"] == [] and report["checks"] == ["lint", "unit"]
    assert _by_path(report)["src/auth.py"]["class"] == "allowed" and report["memory"]["on"] is False
    (work / ".github").mkdir()
    (work / ".github" / "ci.yml").write_text("on: push\n", encoding="utf-8")       # not committed, not even tracked: still part of the change
    (work / "README.md").write_text("# changed\n", encoding="utf-8")
    report = preflight.check(work, _terms_file(tmp_path, MERGE, pretty=True), use_memory=False)
    rows = _by_path(report)
    assert report["ready"] is False and len(report["fixes"]) == 2
    denied, outside = rows[".github/ci.yml"], rows["README.md"]
    assert (denied["class"], denied["code"], denied["status"]) == ("refused", "terms.denied-path", "A")
    assert (denied["happened"], denied["do"]) == ghwords.REFUSALS["terms.denied-path"]
    lines = (tmp_path / "terms.json").read_text(encoding="utf-8").splitlines()
    assert denied["says"]["text"] == '".github/**",' and lines[denied["says"]["line"] - 1].strip() == '".github/**",'
    assert (outside["code"], outside["says"]["clause"]) == ("terms.out-of-scope", "paths: src/**, tests/**")
    assert lines[outside["says"]["line"] - 1].strip() == '"src/**",'
    one_line = preflight.check(work, _terms_file(tmp_path, MERGE), use_memory=False)
    assert _by_path(one_line)[".github/ci.yml"]["says"] == {"source": "terms file", "clause": "deny: .github/**", "line": 1, "text": '"deny":[".github/**",".knos/**"]'}


def test_in_tests_mode_a_new_test_is_allowed_and_not_counted_and_an_edited_test_or_its_configuration_is_refused(work, tmp_path):
    (work / "src" / "auth.py").write_text("def login():\n    return 1\n", encoding="utf-8")
    (work / "tests" / "test_regression.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")
    ready = preflight.check(work, _terms_file(tmp_path, TESTS), issue="7", use_memory=False)
    rows = _by_path(ready)
    assert ready["ready"] is True and rows["tests/test_regression.py"]["class"] == "allowed_not_counted" and rows["src/auth.py"]["class"] == "allowed"
    assert "tests/**" in [p["pattern"] for p in ready["protected"]] and "--issue 7" in ready["next"][0]
    (work / "tests" / "test_auth.py").write_text("def test_login():\n    pass\n", encoding="utf-8")
    (work / "tests" / "conftest.py").write_text("import os\n", encoding="utf-8")
    (work / "pyproject.toml").write_text('[project]\nname = "demo"\n\n[tool.pytest.ini_options]\naddopts = "-q -p no:x"\n', encoding="utf-8")
    report = preflight.check(work, _terms_file(tmp_path, TESTS), issue="7", use_memory=False)
    rows = _by_path(report)
    assert report["ready"] is False
    assert {p: rows[p].get("code") for p in rows} == {"src/auth.py": None, "tests/test_regression.py": None, "tests/test_auth.py": "judge.protected-test-edited",
                                                     "tests/conftest.py": "judge.protected-test-edited", "pyproject.toml": None}
    # the pytest section of pyproject.toml is taken from the base: the edit is allowed and decides nothing, as the judge has it
    assert rows["pyproject.toml"]["class"] == "allowed_not_counted" and "from the base" in rows["pyproject.toml"]["why"]
    assert rows["tests/test_auth.py"]["says"]["clause"] == "mode: tests (the judge protects tests/**)" and '"mode":"tests"' in rows["tests/test_auth.py"]["says"]["text"]
    (work / "pyproject.toml").write_text('[project]\nname = "demo2"\n\n[tool.pytest.ini_options]\naddopts = "-q"\n', encoding="utf-8")
    assert _by_path(preflight.check(work, _terms_file(tmp_path, TESTS), issue="7", use_memory=False))["pyproject.toml"]["class"] == "allowed"
    only_tests = preflight.run(preflight.read_terms(terms.canonical(TESTS).decode("ascii")), [("A", "tests/test_new.py")])
    assert only_tests["ready"] is False and "not counted" in only_tests["fixes"][0]
    merge = preflight.run(preflight.read_terms(terms.canonical(MERGE).decode("ascii")), [("M", "tests/test_auth.py")])
    assert merge["ready"] is True and merge["changes"][0]["class"] == "allowed"          # an order paid on a merge has no judge to protect tests


def test_it_recalls_what_was_refused_before_under_the_same_terms_and_remembers_its_own_result(knos_home, work, tmp_path):
    thash, other = terms.terms_hash(TESTS), terms.terms_hash(MERGE)
    store = history.SibylStore.for_repo(work)
    for pull in (3, 5, 8):
        history.refused(store, "repo", thash, pull, "judge.test-config", "tests/conftest.py", "dana", 1_790_000_000 + pull)
    history.refused(store, "repo", thash, 8, "judge.test-config", "tests/conftest.py", "dana", 1_790_000_099)      # the same refusal, judged again: one memory
    history.refused(store, "repo", thash, 9, "judge.acceptance-failed", "", "eve", 1_790_000_100)
    history.refused(store, "repo", other, 4, "terms.denied-path", ".github/ci.yml", "dana", 1_790_000_101)        # other terms: not recalled
    history.refused(store, "elsewhere", thash, 2, "judge.test-config", "tests/conftest.py", "dana", 1_790_000_102)  # another repository: not recalled
    (work / "tests" / "conftest.py").write_text("import os\n", encoding="utf-8")
    report = preflight.check(work, _terms_file(tmp_path, TESTS), supplier="Dana")
    said = [w["said"] for w in report["memory"]["warnings"]]
    assert said == ["3 earlier submissions were refused for touching tests/conftest.py: your change touches it too.",
                    "1 earlier submission was refused for your change does not pass the acceptance checks."]
    assert report["memory"]["on"] is True and report["memory"]["remembered"] is True and report["ready"] is False
    assert report["memory"]["record"]["rejected"] == 4 and report["memory"]["record"]["pulls"]["rejected"] == [3, 4, 5, 8]
    assert "Remembered: 3 earlier submissions were refused for touching tests/conftest.py" in preflight.words(report)
    preflight.check(work, _terms_file(tmp_path, TESTS), supplier="Dana")                                           # the same change again: one memory
    kept = history.preflights(history.SibylStore.for_repo(work), "repo", thash)
    assert len(kept) == 1 and kept[0]["ready"] is False and kept[0]["found"] == [{"code": "judge.protected-test-edited", "path": "tests/conftest.py"}]
    assert history.refused_before(history.NullStore(), "repo", thash) == []


def test_a_refusal_remembered_under_a_terms_hash_is_recalled_by_the_next_preflight_under_the_same_hash(knos_home, work, tmp_path):
    """Through knos.proof.history and the memory engine, nothing else: the first preflight has nothing to recall; a
    refusal is then remembered under the terms' hash (what a settlement does when it refuses); the next preflight under
    the same terms prints it, and one under other terms does not."""
    pytest.importorskip("sibyl_memory_client", reason="the memory engine (sibyl-memory-client) is not installed: there is nothing to recall from")
    thash = terms.terms_hash(TESTS)
    (work / "src").mkdir(exist_ok=True)
    (work / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    first = preflight.check(work, _terms_file(tmp_path, TESTS), issue="7")
    assert first["terms_hash"] == thash and first["memory"]["on"] is True and first["memory"]["warnings"] == []
    assert "Remembered:" not in preflight.words(first)
    history.refused(history.SibylStore.for_repo(work), "repo", thash, 12, "judge.acceptance-failed", "", "dana", 1_790_000_000)
    again = preflight.check(work, _terms_file(tmp_path, TESTS), issue="7")
    assert [w["said"] for w in again["memory"]["warnings"]] == ["1 earlier submission was refused for your change does not pass the acceptance checks."]
    assert "Remembered: 1 earlier submission was refused for your change does not pass the acceptance checks." in preflight.words(again).splitlines()
    assert again["memory"]["said"] == "Memory is on: this result is remembered in the memory engine."
    other = preflight.check(work, _terms_file(tmp_path, MERGE), issue="7")
    assert other["terms_hash"] != thash and other["memory"]["on"] is True and other["memory"]["warnings"] == []


def test_a_memory_store_that_does_not_answer_is_given_a_bounded_wait_and_one_clear_line(work, tmp_path, monkeypatch):
    """A preflight once hung on the store and printed nothing. The answer about the change never depends on memory:
    a store that does not answer in its time is left behind, and the report says memory is off."""
    import threading
    release = threading.Event()

    class Stuck:
        def __getattr__(self, name):
            if name in ("held", "_knos_until"):
                raise AttributeError(name)
            return lambda *a, **k: release.wait(60) and []

    monkeypatch.setenv("KNOS_MEMORY_WAIT", "0.05")
    (work / "src").mkdir(exist_ok=True)
    (work / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    try:
        report = preflight.run(preflight.read_terms(terms.canonical(MERGE).decode("ascii")), [("A", "src/auth.py")], tree=work, store=Stuck(),
                               repo="repo", memory={"on": True, "said": "Memory is on: this result is remembered in the memory engine."})
        assert report["ready"] is True and report["memory"]["on"] is False and report["memory"]["warnings"] == []
        assert report["memory"]["said"] == "Memory is off: the memory engine did not answer within 0.05 seconds. Nothing is recalled or remembered."
        assert report["memory"]["said"] in preflight.words(report).splitlines() and "remembered" not in report["memory"]
        monkeypatch.setattr(history.SibylStore, "for_repo", classmethod(lambda cls, repo: release.wait(60) and None))
        store, said = preflight.memory(work)                       # the store that does not open in time: the same line, and a store that keeps nothing
        assert isinstance(store, history.NullStore) and said == {"on": False, "said": report["memory"]["said"]}
        whole = preflight.check(work, _terms_file(tmp_path, MERGE))
        assert whole["fixes"] == [f for f in whole["fixes"] if "memory" not in f.lower()], whole["fixes"]
        assert whole["memory"] == {"on": False, "said": report["memory"]["said"], "warnings": []} and "changes" in whole
    finally:
        release.set()
    assert preflight.bounded(lambda: 7) == 7
    with pytest.raises(KeyError):
        preflight.bounded(lambda: {}["x"])


def test_with_the_memory_engine_absent_it_still_works_and_says_memory_is_off(work, tmp_path, monkeypatch):
    real = builtins.__import__

    def without_the_engine(name, *args, **kwargs):
        if name.split(".")[0] == "sibyl_memory_client":
            raise ImportError("No module named 'sibyl_memory_client'")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_the_engine)
    (work / "src" / "auth.py").write_text("def login():\n    return 1\n", encoding="utf-8")
    report = preflight.check(work, _terms_file(tmp_path, MERGE))
    assert report["ready"] is True and report["memory"]["on"] is False and report["memory"]["warnings"] == []
    assert report["memory"]["said"].startswith("Memory is off: the memory engine (sibyl-memory-client) is not installed.")
    assert "Memory is off" in preflight.words(report)


def test_the_command_exits_zero_only_when_ready_and_works_with_no_git_from_a_list_of_changes(knos_home, work, tmp_path, capsys, commands, monkeypatch):
    def no_network(*_a, **_k):
        raise AssertionError("preflight with a terms file asks the network for nothing")
    monkeypatch.setattr("knos.judge.github", no_network)
    file = _terms_file(tmp_path, MERGE)
    (work / "src" / "auth.py").write_text("def login():\n    return 1\n", encoding="utf-8")
    assert cli.main(["preflight", "--terms", str(file), "--tree", str(work)]) == 0
    said = capsys.readouterr().out
    assert "Ready: nothing in this change would be refused by the terms." in said and "Checked: lint, unit" in said and "Protected: .github/**, .knos/**" in said
    changed = tmp_path / "changed.txt"
    changed.write_text("M\tsrc/auth.py\nA\t.knos/policy.yml\nR100\tsrc/a.py\tdocs/a.py\n", encoding="utf-8")
    assert cli.main(["preflight", "--terms", str(file), "--tree", str(tmp_path), "--changed", str(changed), "--no-memory", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False and {r["path"]: r["class"] for r in report["changes"]} == \
        {".knos/policy.yml": "refused", "docs/a.py": "refused", "src/a.py": "allowed", "src/auth.py": "allowed"}
    assert cli.main(["preflight", "--tree", str(work)]) == 1
    assert "Name the terms" in capsys.readouterr().out
    assert cli.main(["preflight", "--terms", str(file), "--tree", str(tmp_path / "nowhere")]) == 1          # no checkout: not ready, and it says what to give
    assert "give --changed FILE" in capsys.readouterr().out


def test_the_terms_are_read_from_the_funded_issue_and_an_agent_gets_the_same_report(knos_home, work, tmp_path):
    line = terms.canonical(MERGE).decode("ascii")
    book = {"repos/acme/app/issues/12/comments?per_page=100&page=1": [{"body": "hello"}, {"body": f"knos-fund: aaa.bbb.ccc\nknos-terms: {line}\n"}],
            "repos/acme/app/issues/13/comments?per_page=100&page=1": [{"body": "nothing here"}]}

    def get(path):
        if path not in book:
            raise OSError("HTTP 404")
        return book[path]
    (work / "src" / "auth.py").write_text("def login():\n    return 1\n", encoding="utf-8")
    report = preflight.mcp({"path": str(work), "issue": "acme/app#12"}, get)
    assert report["ready"] is True and report["terms_hash"] == terms.terms_hash(MERGE) and report["terms_source"] == "acme/app#12"
    assert preflight.mcp({"path": str(work), "terms": str(_terms_file(tmp_path, MERGE))})["terms_hash"] == report["terms_hash"]
    for issue in ("acme/app#13", "acme/app#99", "nonsense"):
        got = preflight.mcp({"path": str(work), "issue": issue}, get)
        assert got["ready"] is False and len(got["fixes"]) == 1
    assert set(preflight.MCP_TOOL["properties"]) == {"path", "terms", "issue", "base", "supplier"} and preflight.MCP_TOOL["required"] == ["path"]


def test_keep_writes_the_suppliers_own_copy_with_the_bundle_command_as_it_is(knos_home, work, tmp_path):
    store = history.SibylStore.for_repo(work)
    history.preflight_seen(store, "repo", "ab" * 32, True, [], "dana", "t1", 1_790_000_000)
    history.appeal_outcome(store, "repo", "evl_" + "0" * 24, "open", "dana", 41, "stale fixture", "", "", 1_790_000_001)
    asked = []

    def bundle(argv):
        asked.append(argv)
        Path(argv[argv.index("--out") + 1]).write_bytes(b"tar")
        return 0
    got = preflight.keep("Order111", tmp_path / "copy", work, "dana", bundle=bundle)
    assert asked == [["bundle", "make", "Order111", "--out", str(tmp_path / "copy" / "evidence.bundle.tar")]]
    assert got["files"] == ["REFUSALS.md", "evidence.bundle.tar", "supplier.json"] and got["bundle"] == "evidence.bundle.tar"
    mine = json.loads((tmp_path / "copy" / "supplier.json").read_text(encoding="utf-8"))
    assert len(mine["preflights"]) == 1 and mine["appeals"][0]["state"] == "open" and mine["record"]["appealed"] == 1 and mine["memory"]["on"] is True
    assert ghwords.refusal_table() in (tmp_path / "copy" / "REFUSALS.md").read_text(encoding="utf-8")
    assert preflight.keep("Order111", tmp_path / "copy2", work, bundle=lambda argv: 1)["bundle"] is None
