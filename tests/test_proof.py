"""Proof: compares what a change claims with what the repository and its checks show. The Stop hook blocks an unproven "done", lets a stop through
after 3 blocks on unchanged evidence, and Sibyl history is load-bearing: the replay of Knos's own releases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knos.proof import checks, claims, history, hook

import _replay as replay

DATA = Path(__file__).parent / "data" / "release_replay.json"


def _sibyl(tmp_path):
    from sibyl_memory_client import MemoryClient
    return history.SibylStore(MemoryClient.local(str(tmp_path / "proof.db"), tenant_id="repo"))


def test_claims_are_read_by_kind_not_phrasing():
    c = claims.read("Knos 0.3.4 is shipped: tagged, on PyPI, 801 passed, CI is green. "
                    "Removed src/knos/bundle.py. Live at https://drexthealpha.github.io/Knos/.")
    assert {"release", "pypi", "tests", "ci", "deleted", "urls"} <= c.kinds
    assert c.deleted == ["src/knos/bundle.py"] and c.urls == ["https://drexthealpha.github.io/Knos/"]
    assert c.version == "0.3.4"
    assert not claims.read("I looked at the parser; here is what I think we should do.").says_done


def test_a_ticked_box_is_a_claim_and_words_the_author_did_not_assert_are_not():
    """A pull request template's checklist is the author's to tick. BerriAI/litellm#34321, the site's false example,
    ticked "My PR passes all CI/CD checks": 0.3.13 read that as no claim, because it read CI only before "passes",
    while the site and the Agent PR Index read the claim it is. An unticked box, an HTML comment (where a template's
    instructions live) and the original prompt an agent quotes are words the author did not assert."""
    checklist = ("## Pre-Submission checklist\r\n\r\n<!-- Please make sure all tests pass before asking for a review -->\r\n"
                 "- [x] I have added meaningful tests\r\n- [x] My PR passes all CI/CD checks (e.g., lint, format, unit tests)\r\n"
                 "- [ ] I have received a Greptile **Confidence Score of at least 4/5** before requesting a maintainer review\r\n")
    assert claims.read(checklist).kinds == {"ci"}
    assert claims.read(checklist.replace("- [x] My PR", "- [ ] My PR")).kinds == set()
    for words, kinds in (("- [X] My PR passes all unit tests", {"tests"}), ("It passed all required CI/CD checks.", {"ci"}),
                         ("All checks passed.", {"ci"}), ("all CI checks have passed", {"ci"}), ("It bypasses all checks.", set())):
        assert claims.read(words).kinds == kinds, words
    for box in ("- [ ] All tests pass", "* [ ] CI is green", "+ [ ] 801 passed", "1. [ ] the suite is green", "> - [ ] every job passes",
                "  - [ ] Deployed to https://knos.dev/x", "- [ ] passes all CI/CD checks\r", "2) [ ] all checks passed",
                "1. - [ ] tests pass"):
        assert claims.read(box).kinds == set() and not claims.read(box).urls, box
        assert claims.read(box.replace("[ ]", "[x]")).kinds, box                  # ticked, the same words are a claim
    assert claims.read("Fixes #7.\n<details>\n<summary>Original prompt</summary>\n\n> Make sure all tests pass.\n</details>").kinds == set()
    assert claims.read("<details><summary>pytest</summary>\n\n801 passed\n</details>").kinds == {"tests"}   # the author's own log
    assert claims.read("<!-- a template's words -->\nAll tests pass.\n<!-- -->").kinds == {"tests"}
    assert claims.read("Removed a stray `<!--` from README.md. All tests pass.").kinds >= {"tests"}         # left open: hides nothing
    assert claims.said("a<!-- b\nc -->d\n- [ ] e\nf") == "a \nd\n\nf"                                   # lines stay lines


def test_a_hedged_negated_or_instructional_sentence_claims_nothing():
    """The gate refuses a claim a failed check contradicts, so what is not a claim must not be read as one: "tests
    should pass" is a hope, "make sure CI is green" an instruction, "tests don't pass yet" the opposite. The words are
    the Agent PR Index's. Each pair is one sentence, asserted and not."""
    pairs = (("All tests pass.", "All tests should pass."),
             ("CI is green.", "Please make sure CI is green."),
             ("The tests pass.", "Please ensure the tests pass."),
             ("The tests pass.", "The tests do not pass."),
             ("Tests pass.", "Tests don't pass yet."),
             ("Tests pass.", "TODO: make tests pass."),
             ("Tests pass.", "Tests must pass before merging."),
             ("CI passes.", "CI will pass once the cache is warm."),
             ("801 passed.", "If 801 passed, merge it."),
             ("All checks passed.", "Verify that all checks passed."),
             ("My PR passes all CI/CD checks.", "My PR would pass all CI/CD checks."),
             ("Unit tests pass.", "Unit tests pass, except the flaky e2e job that fails on main too."))
    for asserted, hedged in pairs:
        assert claims.read(asserted).kinds & {"tests", "ci"}, asserted
        assert not claims.read(hedged).kinds & {"tests", "ci"}, hedged
    # a hedge is read in its own sentence: the claim beside it stands, on one line or on two
    assert claims.read("All tests pass. I did not touch the docs.").kinds == {"tests"}
    assert claims.read("Tests should pass.\nCI is green.").kinds == {"ci"}
    # a template's own words are not a hedge (as in the index): ticked, the box is still the claim
    assert claims.read("- [x] Local tests pass. **Your PR cannot be merged unless tests pass**").kinds == {"tests"}
    assert claims.read("801 passed, 0 failed.").kinds == {"tests"}
    # the other kinds are not read this way: a bare "done" still sends the stop hook to the tests
    assert claims.read("Done. The tests should pass.").kinds == {"done"}


def test_any_description_is_read_in_time_linear_in_its_length():
    """A description is anyone's words, and the gate, `knos check` and the MCP tool read it. Blank lines were each a
    place a bare "done" could start, read to the end of the run: 8,000 of them took over a minute. GitHub keeps a
    description to 65,536 characters; none of these shapes may take seconds at that length."""
    import time
    for shape in ("\n", "\r\n", " ", ": ", ".\n", "- [ ] a\n", "<!--", "<details><summary>original prompt", "passes all ", "tests ",
                  "1", "is ", "removed a", "http://a"):
        body = (shape * (65_536 // len(shape) + 1))[:65_536]
        start = time.perf_counter()
        claims.read(body)
        assert time.perf_counter() - start < 5, repr(shape)


def test_replay_sibyl_blocks_031_and_032_and_null_store_passes_them(tmp_path, repo):
    data = json.loads(DATA.read_text(encoding="utf-8"))
    store = _sibyl(tmp_path)
    replay.seed(store, data["history"])
    assert {r["require"] for r in history.rules(store)} == {"ci"}          # learned from 0.2.0 false done
    got = {v: ok for v, ok, _ in replay.with_sibyl(store, data["replay"], repo)}
    assert got == {"0.3.0": True, "0.3.1": False, "0.3.2": False, "0.3.3": True}
    base = {v: ok for v, ok, _ in replay.null_baseline(data["replay"], repo)}
    assert base == {"0.3.0": True, "0.3.1": True, "0.3.2": True, "0.3.3": True}   # wrongly passes 0.3.1, 0.3.2
    assert {x.failed for x in history.lint(store)} == {"ci"}


def test_the_stop_hook_blocks_then_lets_go_after_three_on_unchanged_evidence(tmp_path, repo, knos_home):
    payload = {"cwd": str(repo), "session_id": "s1", "last_assistant_message": "All done: CI is green."}
    fail = {"ci": lambda r, c, cfg: checks.Result("ci", False, "CI failed for abc", {"sha": "abc"})}
    said = [hook.stop(payload, history.NullStore(), fail)[0] for _ in range(4)]
    assert said == ["block", "block", "block", "warn"]
    ok = {"ci": lambda r, c, cfg: checks.Result("ci", True, "green", {"sha": "abc"})}
    assert hook.stop(payload, history.NullStore(), ok)[0] == "allow"
    assert hook.stop({**payload, "last_assistant_message": "Here is a plan."}, history.NullStore())[0] == "allow"


def test_the_stop_hook_reads_claude_codes_transcript(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(r) for r in [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Shipped; tests pass."}]}}]) + "\n",
        encoding="utf-8")
    assert hook.last_message({"transcript_path": str(t)}) == "Shipped; tests pass."


def test_checks_run_by_knos_not_the_agent(tmp_path, repo):
    assert not checks.deleted(repo, ["README.md"]).ok if (repo / "README.md").exists() else True
    assert checks.deleted(repo, ["nope.txt"]).ok
    assert checks.urls(["https://x.test/a"], getter=lambda u: (404, b"")).ok is False
    assert checks.urls(["https://x.test/a"], getter=lambda u: (200, b"")).ok
    (repo / "pyproject.toml").write_text('[project]\nname = "demo-pkg"\nversion = "9.9.9"\n', encoding="utf-8")
    assert checks.pypi(repo, getter=lambda u: (404, b"")).ok is False
    runs = {("run", "list"): (0, json.dumps([{"databaseId": 1, "status": "completed", "conclusion": "failure",
                                               "workflowName": "tests"}])),
            ("run", "view"): (0, json.dumps({"jobs": [{"name": "pytest", "conclusion": "failure"}]}))}
    got = checks.ci(repo, "abc123", runner=lambda a: runs[tuple(a[:2])])
    assert not got.ok and "tests/pytest: failure" in got.detail


def test_a_bare_done_is_a_claim_and_runs_the_tests_when_there_is_a_test_command(tmp_path, repo, knos_home):
    for said in ("Done.", "All done!", "It's fixed.", "The task is complete.", "Everything is implemented.",
                 "I updated the parser.\nDone."):
        assert "done" in claims.read(said).kinds, said
    for said in ("It is not done yet.", "Here is a plan.", "What should be done about the parser?",
                 "I have done some reading."):
        assert "done" not in claims.read(said).kinds, said
    payload = {"cwd": str(repo), "session_id": "s-done", "last_assistant_message": "Done."}
    assert hook.stop(payload, history.NullStore())[0] == "allow"        # no test command here: nothing to run
    (repo / "package.json").write_text('{"scripts": {"test": "node -e \\"process.exit(1)\\""}}', encoding="utf-8")
    assert checks.test_command(repo) == "npm test"
    fail = {"tests": lambda r, c, cfg: checks.Result("tests", False, "`npm test`: 1 failing", {})}
    verdict, why = hook.stop(payload, history.NullStore(), fail)
    assert verdict == "block" and "npm test" in why


def test_the_test_command_follows_the_language(tmp_path):
    for name, body, want in (("pyproject.toml", "[project]\nname='x'\n", "pytest -q"), ("Cargo.toml", "[package]\n", "cargo test"),
                             ("go.mod", "module x\n", "go test ./..."), ("package.json", '{"scripts":{"test":"vitest"}}', "npm test")):
        d = tmp_path / name.replace(".", "_")
        d.mkdir()
        (d / name).write_text(body, encoding="utf-8")
        assert checks.test_command(d) == want
    assert checks.test_command(tmp_path) == "" and checks.test_command(tmp_path, "make test") == "make test"


# ---- a check that starts with `python` runs with Knos's own interpreter ------------------------------------------

def _store_alias_first_on_path(folder: Path, monkeypatch) -> None:
    """Put a `python` and a `python3` that run nothing first on PATH, as a Windows machine has them: the Microsoft
    Store alias prints a hint and exits 9009 (on a POSIX shell that status is 9009 mod 256 = 49)."""
    import os
    folder.mkdir()
    for name in ("python", "python3"):
        if os.name == "nt":
            (folder / f"{name}.cmd").write_text("@echo Python was not found\r\n@exit /b 9009\r\n", encoding="utf-8")
        else:
            (folder / name).write_text("#!/bin/sh\necho Python was not found\nexit 49\n", encoding="utf-8")
            (folder / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(folder) + os.pathsep + os.environ["PATH"])


def _interpreter_under(folder: Path, marker: Path) -> str:
    """A working interpreter at a path with spaces: a wrapper that notes it ran, then runs this Python."""
    import os
    import sys
    folder.mkdir(parents=True)
    if os.name == "nt":
        exe = folder / "python.cmd"
        exe.write_text(f'@echo off\r\necho ran> "{marker}"\r\n"{sys.executable}" %*\r\n', encoding="utf-8")
    else:
        exe = folder / "python"
        exe.write_text(f'#!/bin/sh\necho ran > "{marker}"\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    return str(exe)


def test_a_check_that_starts_with_python_runs_with_the_interpreter_knos_runs_under(tmp_path, repo, knos_home, monkeypatch):
    import sys
    _store_alias_first_on_path(tmp_path / "alias", monkeypatch)
    ok, fail = 'import sys; sys.exit(0)', 'import sys; sys.exit(3)'
    assert checks._run(f'python -c "{ok}"', repo)[0] != 0               # what the shell alone finds: the alias
    for word in ("python", "python3"):
        r = checks.custom(repo, "c", f'{word} -c "{ok}"')
        assert r.ok and r.evidence == {"command": f'{word} -c "{ok}"', "exit": 0}, r.detail   # the command as written
    assert checks.tests(repo, f'python3 -c "{ok}"').ok                  # `tests = "python3 ..."` in a non-Python repo
    # the interpreter lives under a path with spaces (C:\Program Files\Python312, ~/Library/Application Support/...)
    marker = tmp_path / "ran"
    monkeypatch.setattr(sys, "executable", _interpreter_under(tmp_path / "Program Files" / "Python 3", marker))
    assert checks.custom(repo, "spaces", f'python -c "{ok}"').ok and marker.exists()
    marker.unlink()
    r = checks.custom(repo, "spaces", f'python3 -c "{fail}"')           # and its own exit code is the check's
    assert not r.ok and r.evidence["exit"] == 3 and marker.exists()
    # the way the Stop hook reaches it: .knos/proof.toml, a "done", no test command in this repo
    (repo / ".knos").mkdir()
    (repo / ".knos" / "proof.toml").write_text(f'[[check]]\nname = "manifests parse"\nrun = "python -c \\"{ok}\\""\n', "utf-8")
    payload = {"cwd": str(repo), "session_id": "s-python", "last_assistant_message": "Done."}
    assert hook.stop(payload, history.NullStore())[0] == "allow"
    (repo / ".knos" / "proof.toml").write_text(f'[[check]]\nname = "manifests parse"\nrun = "python -c \\"{fail}\\""\n', "utf-8")
    verdict, why = hook.stop(payload, history.NullStore())
    assert verdict == "block" and "custom:manifests parse" in why and "exited 3" in why


def test_only_a_first_word_of_python_or_python3_is_replaced_and_the_path_is_quoted_for_the_shell():
    import os
    exe = r"C:\Program Files\Python312\python.exe" if os.name == "nt" else "/opt/my tools/bin/python3"
    quoted = f'"{exe}"' if os.name == "nt" else f"'{exe}'"
    assert checks.with_python("python -m pytest -q", exe) == quoted + " -m pytest -q"
    assert checks.with_python("python3 scripts/x.py --check", exe) == quoted + " scripts/x.py --check"
    assert checks.with_python("  python\tx.py", exe) == quoted + "\tx.py" and checks.with_python("python", exe) == quoted
    for other in ("python3.12 x.py", "pythonw x.py", "python-config --libs", "pytest -q", "PYTHONPATH=src python x.py",
                  "cd sub && python x.py", "/usr/bin/python x.py", '"python" x.py', "npm test", ""):
        assert checks.with_python(other, exe) == other, other


def test_a_checks_output_that_is_not_text_is_reported_not_raised(repo):
    r = checks.custom(repo, "bytes", 'python -c "import sys; sys.stdout.buffer.write(bytes([255, 254, 10])); sys.exit(3)"')
    assert not r.ok and r.evidence["exit"] == 3


# ---- knos init -----------------------------------------------------------------------------------------------------
# What `knos init` writes depends on the machine in two ways, and neither may decide a test: which coding agents are
# installed (conftest hides this machine's from every test), and where the knos script is (the fixture below).

@pytest.fixture()
def knos_script(_isolated, monkeypatch):
    """A knos script of the test's own. `knos init` writes the script beside its interpreter, else one on PATH, else
    `python -m knos` (init.own_script): a checkout run without installing it, or a stale knos on PATH, would otherwise
    change what these tests read back."""
    from knos import init
    script = _isolated / "venv" / "bin" / "knos"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(init, "own_script", lambda: str(script))
    return script


def test_knos_is_started_by_the_script_beside_its_interpreter_else_one_on_path_else_the_module(tmp_path, monkeypatch):
    import os
    import sys

    from knos import init
    name = "knos.exe" if os.name == "nt" else "knos"
    venv, elsewhere = tmp_path / "venv" / "bin", tmp_path / "on path"
    venv.mkdir(parents=True)
    elsewhere.mkdir()
    python = str(venv / ("python.exe" if os.name == "nt" else "python"))
    monkeypatch.setattr(sys, "executable", python)
    monkeypatch.setenv("PATH", str(elsewhere))                         # nothing of this machine's
    assert init.own_script() is None and init.knos_argv() == [python, "-m", "knos"]
    assert init.mcp_server() == (python, ["-m", "knos", "mcp"])
    assert init.hook_cmd("codex") == f'"{python.replace(os.sep, "/")}" -m knos hook proof --client codex #knos-guard'
    (elsewhere / name).write_text("#!/bin/sh\n", encoding="utf-8")
    (elsewhere / name).chmod(0o755)
    same = lambda a, b: os.path.normcase(a) == os.path.normcase(b)     # noqa: E731 - Windows finds knos.EXE
    assert same(init.own_script(), str(elsewhere / name))              # one on PATH, when there is none of its own
    (venv / name).write_text("#!/bin/sh\n", encoding="utf-8")
    assert init.own_script() == str(venv / name)                       # its own, before a stale one on PATH
    assert init.mcp_server() == (str(venv / name), ["mcp"])
    assert init.hook_cmd("claude") == f'"{str(venv / name).replace(os.sep, "/")}" hook proof --client claude #knos-guard'


def test_an_agent_found_on_path_gets_the_hook_before_it_has_a_config_folder(knos_home, _isolated, knos_script, tmp_path, monkeypatch):
    """Claude Code and Codex are also found by their CLI (a fresh install has no ~/.codex yet). The agents of the
    machine running the tests are hidden from every test (conftest), so this one puts a `codex` on PATH itself."""
    import os

    from knos import init
    home = _isolated
    assert not init.present("codex") and not init.present("claude")    # whatever this machine has installed
    folder = tmp_path / "bin"
    folder.mkdir()
    exe = folder / ("codex.cmd" if os.name == "nt" else "codex")
    exe.write_text("@echo codex\r\n" if os.name == "nt" else "#!/bin/sh\necho codex\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(folder) + os.pathsep + os.environ["PATH"])
    assert init.present("codex") and not init.present("claude")
    rep = init.install()
    assert [h for h, _ in rep["done"]] == ["codex"] and [h for h, _ in rep["mcp"]] == ["codex"]
    assert ("claude", "not installed here") in rep["skipped"]
    hooks = json.loads((home / ".codex" / "hooks.json").read_text())["hooks"]
    assert "hook proof --client codex" in hooks["Stop"][0]["hooks"][0]["command"]
    init.undo()
    assert "knos" not in (home / ".codex" / "hooks.json").read_text() and not (home / ".codex" / "config.toml").exists()


def test_init_installs_the_stop_hook_and_undo_removes_it(knos_home, _isolated, knos_script):
    from knos import init
    home = _isolated
    (home / ".claude").mkdir()
    settings = home / ".claude" / "settings.json"
    settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}}), "utf-8")
    rep = init.install()
    assert [h for h, _ in rep["done"]] == ["claude"] and ("codex", "not installed here") in rep["skipped"]
    data = json.loads(settings.read_text())
    assert set(data["hooks"]) == {"Stop"} and data["model"] == "x"
    cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert cmds[0] == "mine" and "hook proof --client claude" in cmds[1] and len(cmds) == 2
    init.install()                                                     # a second init changes nothing
    assert json.loads(settings.read_text()) == data
    assert (home / ".claude" / "settings.json.knos-backup").exists()
    init.undo()
    after = json.loads(settings.read_text())
    assert [h["command"] for e in after["hooks"]["Stop"] for h in e["hooks"]] == ["mine"] and after["model"] == "x"


def test_init_removes_what_older_versions_installed(knos_home, _isolated, knos_script):
    from knos import init
    home = _isolated
    (home / ".claude").mkdir()
    old = {"hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "knos hook guard --client claude #knos-guard"}]},
                                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}],
                     "SessionStart": [{"hooks": [{"type": "command", "command": "knos hook start --client claude #knos-guard"}]}],
                     "Stop": [{"hooks": [{"type": "command", "command": "knos hook proof --client claude #knos-guard"}]}]}}
    (home / ".claude" / "settings.json").write_text(json.dumps(old), "utf-8")
    # an older install whose interpreter is gone (a host then fails to start the server at all)
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"knos": {"command": "C:/python.exe", "args": ["-m", "knos", "mcp"]},
                                                                  "other": {"command": "x"}}}), "utf-8")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('model = "x"\n\n[mcp_servers.knos]\ncommand = "C:/python.exe"\nargs = ["-m", "knos", "mcp"]\n\n[other]\na = 1\n', "utf-8")
    rep = init.install()
    assert any("MCP server" in x for x in rep["removed"])
    hooks = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]
    assert set(hooks) == {"PreToolUse", "Stop"} and json.dumps(hooks).count("knos-guard") == 1
    assert hooks["PreToolUse"] == [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}]
    command, args = init.mcp_server()                                  # the old entry is replaced by this version's
    assert args == ["mcp"] and Path(command).is_absolute()
    assert json.loads((home / ".claude.json").read_text())["mcpServers"] == {
        "other": {"command": "x"}, "knos": {"type": "stdio", "command": command, "args": ["mcp"]}}
    toml = (home / ".codex" / "config.toml").read_text()
    assert toml == f'model = "x"\n\n[other]\na = 1\n\n[mcp_servers.knos]\ncommand = {json.dumps(command)}\nargs = ["mcp"]\n'
    assert init.install()["removed"] == []                             # and this version's is not an old one
    rep = init.undo()                                                  # undo takes this version's out as well
    assert json.loads((home / ".claude.json").read_text()) == {"mcpServers": {"other": {"command": "x"}}}
    assert (home / ".codex" / "config.toml").read_text() == 'model = "x"\n\n[other]\na = 1\n'
    assert {h for h, _ in rep["mcp"]} == {"claude", "codex"}


def test_init_removes_an_older_knos_server_registered_for_one_project(knos_home, _isolated, knos_script, capsys):
    """Claude Code keeps a server added for one project (`claude mcp add`, its default local scope) under
    projects.<path>.mcpServers in ~/.claude.json, and there it wins over the one knos registers for the user: an older
    install's entry, or one whose interpreter is gone, kept failing to start (spawn C:/python.exe ENOENT) after
    `knos init`. Such entries go; a project's own working knos server and every other server stay."""
    from knos import init
    home = _isolated
    (home / ".claude").mkdir()
    working = {"type": "stdio", "command": str(knos_script), "args": ["mcp"]}
    projects = {"C:\\Users\\me\\Desktop": {"mcpServers": {"knos": {"command": "C:/python.exe", "args": ["-m", "knos.mcp"]},
                                                          "other": {"command": "x"}}, "allowedTools": []},
                "/home/me/gone": {"mcpServers": {"knos": {"type": "stdio", "command": "C:/python.exe", "args": ["-m", "knos", "mcp"]}}},
                "/home/me/fine": {"mcpServers": {"knos": working}},
                "/home/me/none": {"mcpServers": {}}, "/home/me/odd": {"mcpServers": "not a table"}}
    (home / ".claude.json").write_text(json.dumps({"projects": projects, "numStartups": 3}), "utf-8")
    rep = init.install()
    assert sorted(x for x in rep["removed"] if "project" in x) == [
        f"the knos MCP server of the project /home/me/gone in {home / '.claude.json'}",
        f"the knos MCP server of the project C:\\Users\\me\\Desktop in {home / '.claude.json'}"]
    data = json.loads((home / ".claude.json").read_text())
    assert data["numStartups"] == 3 and data["mcpServers"]["knos"]["args"] == ["mcp"]
    assert data["projects"] == {"C:\\Users\\me\\Desktop": {"mcpServers": {"other": {"command": "x"}}, "allowedTools": []},
                                "/home/me/gone": {"mcpServers": {}}, "/home/me/fine": {"mcpServers": {"knos": working}},
                                "/home/me/none": {"mcpServers": {}}, "/home/me/odd": {"mcpServers": "not a table"}}
    assert init.install()["removed"] == []                             # nothing older is left
    # and `knos init` says what it took out as what it was: a server whose command is gone did not move to knos-labs
    data["projects"]["/home/me/gone"]["mcpServers"]["knos"] = {"command": "C:/python.exe", "args": ["-m", "knos", "mcp"]}
    (home / ".claude.json").write_text(json.dumps(data), "utf-8")
    from knos.cli import main
    assert main(["init", "--hosts", "claude"]) == 0
    said = capsys.readouterr().out.replace("\n", "")
    assert f"removed the knos MCP server of the project /home/me/gone in {home / '.claude.json'} (an older Knos's, or one whose command is gone)" in said
    assert "knos-labs" not in said


def test_init_registers_the_mcp_server_with_every_host_that_is_here_and_undo_puts_the_files_back(knos_home, _isolated, knos_script):
    from knos import init
    home = _isolated
    for folder in (".claude", ".codex", ".cursor", ".gemini"):
        (home / folder).mkdir()
    as_written = lambda data: json.dumps(data, indent=2) + "\n"  # noqa: E731
    before = {
        home / ".claude.json": as_written({"numStartups": 7, "mcpServers": {"zeta": {"command": "z"}, "alpha": {"command": "a"}},
                                           "projects": {"/r": {"allowedTools": []}}}),
        home / ".gemini" / "settings.json": as_written({"theme": "Dracula", "selectedAuthType": "oauth-personal"}),
        home / ".codex" / "config.toml": '# mine\nmodel = "o3"\n\n[mcp_servers.other]\ncommand = "x"   # keep\n',
    }
    for path, text in before.items():
        path.write_text(text, "utf-8")
    rep = init.install()
    assert [h for h, _ in rep["mcp"]] == ["claude", "codex", "cursor", "gemini"] and rep["removed"] == []
    assert [h for h, _ in rep["done"]] == ["claude", "codex"]          # the Stop hook stays with the two that have one
    command, args = init.mcp_server()
    entry = {"type": "stdio", "command": command, "args": ["mcp"]}
    claude = json.loads((home / ".claude.json").read_text())
    assert list(claude) == ["numStartups", "mcpServers", "projects"] and claude["projects"] == {"/r": {"allowedTools": []}}
    assert list(claude["mcpServers"]) == ["zeta", "alpha", "knos"] and claude["mcpServers"]["knos"] == entry
    assert json.loads((home / ".cursor" / "mcp.json").read_text()) == {"mcpServers": {"knos": entry}}
    gemini = json.loads((home / ".gemini" / "settings.json").read_text())
    assert gemini == {"theme": "Dracula", "selectedAuthType": "oauth-personal",
                      "mcpServers": {"knos": {"command": command, "args": ["mcp"]}}}
    toml = (home / ".codex" / "config.toml").read_text()
    assert toml == before[home / ".codex" / "config.toml"] + f'\n[mcp_servers.knos]\ncommand = {json.dumps(command)}\nargs = ["mcp"]\n'
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    assert tomllib.loads(toml)["mcp_servers"] == {"other": {"command": "x"}, "knos": {"command": command, "args": ["mcp"]}}
    after = {p: p.read_text() for p in [*before, home / ".cursor" / "mcp.json"]}
    init.install()                                                     # a second init changes nothing
    assert {p: p.read_text() for p in after} == after
    for path, text in before.items():                                  # each file as it was before Knos first changed it
        assert path.with_name(path.name + ".knos-backup").read_text() == text
    rep = init.undo()
    assert [h for h, _ in rep["mcp"]] == ["claude", "codex", "cursor", "gemini"] and rep["removed"] == []
    assert {p: p.read_text() for p in before} == before                # byte for byte
    assert not (home / ".cursor" / "mcp.json").exists()                # the file Knos created is gone again
    assert init.undo()["mcp"] == []


def test_init_leaves_a_working_knos_server_and_everything_else_in_a_users_files_alone(knos_home, _isolated, knos_script):
    """A `knos mcp` entry that still starts (another install's, or one a registry wrote) is not touched; Codex's TOML
    keeps its comments, its line endings and its other tables whatever shape the old knos table had; a file knos
    cannot read is skipped; the backup keeps the original's permissions."""
    import os
    import sys

    from knos import init
    home = _isolated
    for folder in (".claude", ".codex"):
        (home / folder).mkdir()
    working = {"command": sys.executable, "args": ["-m", "knos", "mcp"], "env": {"GH_TOKEN": "x"}}
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"knos": working}}, indent=2) + "\n", "utf-8")
    os.chmod(home / ".claude.json", 0o600)
    toml = home / ".codex" / "config.toml"
    old = ('model = "o3"\r\n\r\n[mcp_servers."knos"]   # old\r\ncommand = "C:/gone/python.exe"\r\nargs = ["-m", "knos", "mcp"]\r\n'
           '[mcp_servers.knos.env]\r\nA = "1"\r\n\r\n# about the next table\r\n[mcp_servers.other]\r\ncommand = "x"\r\n')
    toml.write_bytes(old.encode())
    rep = init.install()
    assert json.loads((home / ".claude.json").read_text())["mcpServers"]["knos"] == working      # left exactly as it was
    assert not (home / ".claude.json.knos-backup").exists()
    command, _ = init.mcp_server()
    got = toml.read_bytes().decode()
    assert got == ('model = "o3"\r\n\r\n# about the next table\r\n[mcp_servers.other]\r\ncommand = "x"\r\n'
                   f'\r\n[mcp_servers.knos]\r\ncommand = {json.dumps(command)}\r\nargs = ["mcp"]\r\n')
    assert any("config.toml" in x for x in rep["removed"])
    # the user adds a setting to the table knos wrote: a later init keeps it, and undo leaves a table that is no longer only knos's
    toml.write_bytes((got + 'startup_timeout_sec = 20\r\n').encode())
    kept = toml.read_bytes()
    init.install()
    assert toml.read_bytes() == kept
    # a file that is not text, or not TOML, is skipped and never rewritten
    toml.write_bytes(b"\xff\xfe not utf-8")
    rep = init.install()
    assert toml.read_bytes() == b"\xff\xfe not utf-8" and any(h == "codex" for h, _ in rep["skipped"])
    toml.write_bytes(b"[mcp_servers.knos]\n[mcp_servers.knos]\n")
    init.install()
    assert toml.read_bytes() == b"[mcp_servers.knos]\n[mcp_servers.knos]\n"
    # a dead entry in a private file: replaced, and the backup is as private as the original
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"knos": {"command": "/gone/knos", "args": ["mcp"]}}}), "utf-8")
    os.chmod(home / ".claude.json", 0o600)
    init.install()
    assert json.loads((home / ".claude.json").read_text())["mcpServers"]["knos"]["command"] == command
    if os.name != "nt":
        assert (home / ".claude.json.knos-backup").stat().st_mode & 0o777 == 0o600
        assert (home / ".claude.json").stat().st_mode & 0o777 == 0o600


def test_init_touches_cursor_and_gemini_only_when_they_are_installed(knos_home, _isolated, knos_script):
    from knos import init
    home = _isolated
    (home / ".claude").mkdir()
    rep = init.install()
    assert [h for h, _ in rep["mcp"]] == ["claude"] and not (home / ".cursor").exists() and not (home / ".gemini").exists()
    assert {h for h, _ in rep["skipped"]} == {"codex"}                 # the two without a hook are not even mentioned
    rep = init.install(["cursor", "gemini", "vim"])                    # named, and still not here
    assert rep["mcp"] == [] and not (home / ".cursor").exists()
    assert dict(rep["skipped"])["cursor"] == "not installed here" and "unknown host" in dict(rep["skipped"])["vim"]


def test_init_keeps_a_knos_server_someone_extended_and_another_install_s_is_replaced(knos_home, _isolated, knos_script):
    from knos import init
    home = _isolated
    (home / ".cursor").mkdir()
    command, _ = init.mcp_server()
    mine = {"command": command, "args": ["mcp"], "env": {"GH_TOKEN": "t"}}
    path = home / ".cursor" / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"knos": mine}}), "utf-8")
    assert init.install(["cursor"])["removed"] == [] and json.loads(path.read_text())["mcpServers"]["knos"] == mine
    path.write_text(json.dumps({"mcpServers": {"knos": {"command": "/old/venv/bin/knos", "args": ["mcp"]}, "x": {"command": "x"}}}), "utf-8")
    rep = init.install(["cursor"])
    assert rep["removed"] == [f"the knos MCP server in {path}"]
    assert json.loads(path.read_text())["mcpServers"] == {"x": {"command": "x"}, "knos": {"type": "stdio", "command": command, "args": ["mcp"]}}
    bad = home / ".cursor" / "mcp.json"
    bad.write_text(json.dumps({"mcpServers": ["knos"]}), "utf-8")      # not a table of servers: left exactly as it is
    rep = init.install(["cursor"])
    assert rep["mcp"] == [] and "left it alone" in dict(rep["skipped"])["cursor"] and json.loads(bad.read_text()) == {"mcpServers": ["knos"]}


def test_knos_init_prints_one_line_for_each_hook_and_each_mcp_server(knos_home, _isolated, knos_script, capsys):
    from knos.cli import main
    home = _isolated
    (home / ".claude").mkdir()
    (home / ".gemini").mkdir()
    assert main(["init"]) == 0
    said = capsys.readouterr().out
    assert f"Stop hook for claude: {home / '.claude' / 'settings.json'}" in said.replace("\n", "")
    assert f"MCP server for claude: {home / '.claude.json'}" in said.replace("\n", "")
    assert f"MCP server for gemini: {home / '.gemini' / 'settings.json'}" in said.replace("\n", "")
    assert "knos_bounties" in said and "Undo: knos init --undo" in said
    assert main(["init", "--undo"]) == 0
    said = capsys.readouterr().out.replace("\n", "")
    assert f"removed from gemini: {home / '.gemini' / 'settings.json'}" in said and "Knos is out of your agents' settings." in said
    assert not (home / ".claude.json").exists() and not (home / ".gemini" / "settings.json").exists()


def test_a_settings_file_knos_cannot_read_is_left_alone(knos_home, _isolated, knos_script):
    from knos import init
    (_isolated / ".claude").mkdir()
    bad = _isolated / ".claude" / "settings.json"
    bad.write_text("{not json", "utf-8")
    rep = init.install()
    assert bad.read_text() == "{not json" and rep["done"] == [] and "left it alone" in rep["skipped"][0][1]


def test_a_hook_name_from_an_older_version_does_nothing(knos_home, capsys):
    from knos.cli import main
    for name in ("guard", "start", "safety"):
        assert main(["hook", name, "--client", "claude"]) == 0
    assert capsys.readouterr().out == ""


def test_ci_reads_gh_json_followed_by_a_notice(tmp_path):
    from knos.proof import checks
    notice = "\nA new release of gh is available: 2.80.0\n"

    def gh(args):
        if args[1] == "list":
            return 0, '[{"databaseId": 1, "status": "completed", "conclusion": "failure", "workflowName": "ci"}]' + notice
        return 0, '{"jobs": [{"name": "tests", "conclusion": "failure"}]}' + notice
    r = checks.ci(tmp_path, "a" * 40, runner=gh)
    assert not r.ok and "ci/tests: failure" in r.detail
