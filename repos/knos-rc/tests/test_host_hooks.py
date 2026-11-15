"""`knos init --host <name>` and `knos hook proof --client <name>`, host by host.

Two things are held here. What `knos init --host` writes into a project is what that host's documentation says it
reads (the field names below are the ones cited in integrations/hosts/README.md), a second run changes nothing, the
tools a host may run unasked are the ones that only read, and the user's home is written only with --global. And one
hook answers every host in that host's own words: a recorded end-of-turn event per host (tests/_host_events.py) goes
in, and the "not done yet: this check failed" comes out in the shape that host acts on.

No host was run here. An event or an answer that its host's page does not fully state has `unconfirmed` in the name
of every test that uses it."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from _host_events import EVENTS, HERMES_BEFORE, NEEDS_CWD, _fill, deliver, event, reason

from knos import init, mcp
from knos.proof import checks, history, hook

READS = [t["name"] for t in mcp.TOOLS if t["annotations"]["readOnlyHint"]]
POSTS = ["knos_take_work", "knos_submit_work", "knos_collect"]
KNOS = ["uvx", "knos"]
SERVER = {"command": "uvx", "args": ["knos", "mcp"]}


@pytest.fixture()
def home(_isolated, monkeypatch):
    monkeypatch.setattr(init, "portable_argv", lambda: list(KNOS))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    return _isolated


def _tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def _json(folder: Path, *parts: str) -> dict:
    return json.loads(folder.joinpath(*parts).read_text(encoding="utf-8"))


def _hook(client: str) -> str:
    return f"uvx knos hook proof --client {client}"


def test_the_tools_a_host_may_run_unasked_are_the_ones_that_only_read():
    assert init.read_only_tools() == READS and init.posting_tools() == POSTS
    assert "knos_find_work" in READS and not set(READS) & set(POSTS)


# ---- what each route writes, in the fields the host's page names ----------------------------------------------------

def _cursor(p: Path, rep: dict) -> list[str]:
    assert _json(p, ".cursor", "mcp.json") == {"mcpServers": {"knos": {"type": "stdio", **SERVER}}}
    hooks = _json(p, ".cursor", "hooks.json")
    assert hooks["version"] == 1 and set(hooks) == {"version", "hooks"}
    assert hooks["hooks"] == {"afterAgentResponse": [{"command": _hook("cursor")}],
                              "stop": [{"command": _hook("cursor"), "timeout": 600}]}
    return [a[len("Mcp(knos:"):-1] for a in _json(p, ".cursor", "cli.json")["permissions"]["allow"]]


def _gemini(p: Path, rep: dict) -> list[str]:
    got = _json(p, ".gemini", "settings.json")
    server = got["mcpServers"]["knos"]
    assert {k: server[k] for k in SERVER} == SERVER and set(server) == {"command", "args", "includeTools"}
    [group] = got["hooks"]["AfterAgent"]
    [handler] = group["hooks"]
    assert handler["type"] == "command" and handler["command"] == _hook("gemini") and handler["name"] == "knos"
    assert handler["timeout"] == 600_000                          # Gemini CLI counts a hook's timeout in milliseconds
    return server["includeTools"]


def _copilot(p: Path, rep: dict) -> list[str]:
    hooks = _json(p, ".github", "hooks", "knos.json")
    assert hooks == {"version": 1, "hooks": {"agentStop": [
        {"type": "command", "bash": _hook("copilot"), "powershell": _hook("copilot"), "timeoutSec": 600}]}}
    assert _json(p, ".vscode", "mcp.json") == {"servers": {"knos": {"type": "stdio", **SERVER}}}
    [paste] = rep["manual"]                                       # the cloud agent's servers are a repository setting
    entry = json.loads(paste[paste.index("{"):])["mcpServers"]["knos"]
    assert entry["type"] == "local" and {k: entry[k] for k in SERVER} == SERVER
    return entry["tools"]


def _opencode(p: Path, rep: dict) -> list[str]:
    got = _json(p, "opencode.json")
    assert got["$schema"] == "https://opencode.ai/config.json"
    assert got["mcp"] == {"knos": {"type": "local", "command": ["uvx", "knos", "mcp"], "enabled": True}}
    assert got["tools"] == {f"knos_{t}": False for t in POSTS}    # every tool that posts is off; the rest are the reads
    plugin = (p / ".opencode" / "plugins" / "knos.js").read_text(encoding="utf-8")
    assert 'const KNOS = ["uvx", "knos"]' in plugin and "export const Knos = async ({ client, $, directory })" in plugin
    assert 'event.type !== "session.idle"' in plugin and "hook proof --client opencode" in plugin
    return [t["name"] for t in mcp.TOOLS if got["tools"].get(f"knos_{t['name']}", True)]


def _roo(p: Path, rep: dict) -> list[str]:
    server = _json(p, ".roo", "mcp.json")["mcpServers"]["knos"]
    assert {k: server[k] for k in SERVER} == SERVER and server["disabled"] is False
    return server["alwaysAllow"]


def _cline(p: Path, rep: dict) -> list[str]:
    assert "Before you say that work here is done" in (p / ".clinerules" / "knos.md").read_text(encoding="utf-8")
    [paste] = rep["manual"]                                       # Cline keeps its servers in the home: not written
    return json.loads(paste[paste.index("{"):])["knos"]["autoApprove"]


def _windsurf(p: Path, rep: dict) -> list[str]:
    assert _json(p, ".windsurf", "hooks.json") == {"hooks": {"post_cascade_response": [
        {"command": _hook("windsurf"), "powershell": _hook("windsurf"), "show_output": True}]}}
    [paste] = rep["manual"]
    off = json.loads(paste[paste.index("{"):])["knos"]["disabledTools"]
    return [t["name"] for t in mcp.TOOLS if t["name"] not in off]


def _goose(p: Path, rep: dict) -> list[str] | None:
    plugin = p / ".agents" / "plugins" / "knos"
    assert set(_json(plugin, "plugin.json")) == {"name", "version", "description"}
    assert _json(plugin, "hooks", "hooks.json") == {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": _hook("goose"), "timeout": 600}]}]}}
    [paste] = rep["manual"]
    assert "type: stdio" in paste and 'cmd: "uvx"' in paste and 'args: ["knos", "mcp"]' in paste
    return None                                                   # its page names no field that limits a server's tools


def _aider(p: Path, rep: dict) -> list[str] | None:
    lines = (p / ".aider.conf.yml").read_text(encoding="utf-8").splitlines()
    assert lines[1:] == [f'test-cmd: "{_hook("aider")}"', "auto-test: true"] and lines[0].startswith("# knos-guard")
    return None                                                   # aider has no MCP client


def _hermes(p: Path, rep: dict) -> list[str]:
    assert not rep["files"]                                       # Hermes reads nothing from a project
    [paste] = rep["manual"]
    return _hermes_block(paste[paste.index("# knos-guard"):])


def _hermes_block(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    assert f'- command: "{_hook("hermes")}"' in lines and 'command: "uvx"' in lines and 'args: ["knos", "mcp"]' in lines
    try:
        import yaml
    except ModuleNotFoundError:                                   # not a dependency: without it, the line itself
        [include] = [line for line in lines if line.startswith("include: ")]
        return json.loads(include[len("include: "):])
    doc = yaml.safe_load(text)
    assert set(doc) == {"mcp_servers", "hooks"} and set(doc["hooks"]) == {"pre_verify", "pre_llm_call"}
    assert doc["hooks"]["pre_verify"] == [{"command": _hook("hermes"), "timeout": 300}]      # 300 is Hermes's cap
    assert {k: doc["mcp_servers"]["knos"][k] for k in SERVER} == SERVER
    return doc["mcp_servers"]["knos"]["tools"]["include"]


ROUTES = {"cursor": _cursor, "gemini": _gemini, "copilot": _copilot, "opencode": _opencode, "roo": _roo, "cline": _cline,
          "windsurf": _windsurf, "goose": _goose, "aider": _aider, "hermes": _hermes}


def test_every_host_knos_names_has_a_route_and_a_test():
    assert set(init.ROUTES) == set(ROUTES) and all(gate in init.GATES for _route, gate, _name in init.ROUTES.values())
    assert {h for h, (_r, gate, _n) in init.ROUTES.items() if gate == "no"} == {"cline", "roo"}
    assert init.ROUTES["windsurf"][1] == "annotate" and init.ROUTES["aider"][1] == "each edit"


@pytest.mark.parametrize("host", sorted(ROUTES))
def test_a_route_writes_what_its_host_reads_into_the_project_only_and_a_second_run_changes_nothing(host, home, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    before = _tree(home)
    rep = init.project(host, project)
    allowed = ROUTES[host](project, rep)
    assert allowed is None or allowed == READS, f"{host} would run or offer something other than the reading tools"
    assert all(changed for _path, _what, changed in rep["files"])
    assert all(Path(path).is_relative_to(project) for path, _what, _changed in rep["files"])
    assert _tree(home) == before, f"{host}: the home was written without --global"
    wrote = _tree(project)
    again = init.project(host, project)
    assert _tree(project) == wrote and not any(changed for _path, _what, changed in again["files"])
    assert [p for p, _w, _c in again["files"]] == [p for p, _w, _c in rep["files"]] and again["manual"] == rep["manual"]
    said: list[str] = []
    assert init.project_cli(host, False, said.append, project) == 0                 # and it says what it wrote
    assert all(any(str(path) in line for line in said) for path, _what, _changed in rep["files"])
    assert said[-1].startswith(f'Can it stop a false "done"? {init.ROUTES[host][1]}:')


def test_a_route_keeps_what_the_project_already_had(home, tmp_path):
    project = tmp_path / "project"
    (project / ".cursor").mkdir(parents=True)
    (project / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    (project / ".cursor" / "hooks.json").write_text(json.dumps(
        {"version": 1, "hooks": {"stop": [{"command": "./mine.sh"}, {"command": "old-knos hook proof --client cursor"}]}}), encoding="utf-8")
    (project / ".cursor" / "cli.json").write_text(json.dumps({"permissions": {"allow": ["Shell(ls)"], "deny": ["Shell(rm)"]}}), encoding="utf-8")
    init.project("cursor", project)
    assert set(_json(project, ".cursor", "mcp.json")["mcpServers"]) == {"other", "knos"}
    assert _json(project, ".cursor", "hooks.json")["hooks"]["stop"] == [{"command": "./mine.sh"}, {"command": _hook("cursor"), "timeout": 600}]
    perms = _json(project, ".cursor", "cli.json")["permissions"]
    assert perms["allow"] == ["Shell(ls)", *(f"Mcp(knos:{t})" for t in READS)] and perms["deny"] == ["Shell(rm)"]
    # a settings file Knos cannot read is left exactly as it is, and the command says so
    (project / ".gemini").mkdir()
    (project / ".gemini" / "settings.json").write_text("{ not json", encoding="utf-8")
    said: list[str] = []
    assert init.project_cli("gemini", False, said.append, project) == 1 and "left it alone" in said[0]
    assert (project / ".gemini" / "settings.json").read_text(encoding="utf-8") == "{ not json"
    assert init.project_cli("emacs", False, said.append, project) == 1 and "has no project install" in said[-1]
    assert init.project("vscode", project)["host"] == "copilot"                    # one route for Copilot's three hosts


def test_global_writes_the_home_only_for_a_host_that_reads_nothing_else_and_never_rewrites_yaml_it_did_not_write(home, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rep = init.project("hermes", project, everywhere=True)
    [(path, _what, changed)] = rep["files"]
    assert Path(path) == home / ".hermes" / "config.yaml" and changed and not rep["manual"]
    assert _hermes_block(Path(path).read_text(encoding="utf-8")) == READS
    wrote = _tree(home)
    assert not init.project("hermes", project, everywhere=True)["files"][0][2] and _tree(home) == wrote
    # a config that already has servers or hooks is the user's: Knos gives the lines and writes nothing
    Path(path).write_text("model: x\nmcp_servers:\n  other:\n    command: y\n", encoding="utf-8")
    rep = init.project("hermes", project, everywhere=True)
    assert not rep["files"] and "already sets mcp_servers" in rep["manual"][0]
    assert Path(path).read_text(encoding="utf-8") == "model: x\nmcp_servers:\n  other:\n    command: y\n"
    rep = init.project("cline", project, everywhere=True)
    server = _json(home, ".cline", "mcp.json")["mcpServers"]["knos"]
    assert server == {**SERVER, "disabled": False, "autoApprove": READS} and not rep["manual"]
    # aider's file in a project that already names a test command is left alone too
    (project / ".aider.conf.yml").write_text("test-cmd: pytest -q\n", encoding="utf-8")
    rep = init.project("aider", project)
    assert not rep["files"] and (project / ".aider.conf.yml").read_text(encoding="utf-8") == "test-cmd: pytest -q\n"


def test_a_command_with_a_space_in_its_path_is_one_word_to_the_hosts_shell(home, monkeypatch, tmp_path):
    exe = str(tmp_path / "my tools" / "knos")
    monkeypatch.setattr(init, "portable_argv", lambda: [exe])
    init.project("cursor", tmp_path)
    [stop] = _json(tmp_path, ".cursor", "hooks.json")["hooks"]["stop"]
    assert stop["command"] == f'"{exe.replace(os.sep, "/")}" hook proof --client cursor'
    assert _json(tmp_path, ".cursor", "mcp.json")["mcpServers"]["knos"]["command"] == exe


# ---- one hook, each host's event in and each host's answer out ------------------------------------------------------

SAID = "All tests pass."
FAILED = "3 failed in test_calc.py"


def _runners(good: bool) -> dict:
    ok = lambda name: (lambda repo, claim, cfg: checks.Result(name, True, name, {}))  # noqa: E731
    return {"pypi": ok("pypi"), "author": ok("author"), "ci": ok("ci"),
            "tests": lambda repo, claim, cfg: checks.Result("tests", good, "ok" if good else FAILED, {})}


def _edited(knos_home: Path) -> None:
    """As after an edit: Knos keeps the test run of an unchanged tree and would not run the tests again."""
    (knos_home / "proof-cache.json").unlink(missing_ok=True)


def _cases() -> list:
    return [pytest.param(c, id=c if EVENTS[c][1] else f"{c}-unconfirmed") for c in sorted(EVENTS)]


@pytest.mark.parametrize("client", _cases())
def test_a_false_done_gets_that_hosts_not_done_yet_and_a_true_one_gets_nothing(client, knos_home, repo, monkeypatch):
    if client in NEEDS_CWD:
        monkeypatch.chdir(repo)
    out, code = deliver(client, repo, SAID, history.NullStore(), _runners(False))
    why = reason(client, out)
    assert code == 0 and FAILED in why and "Knos could not prove what your last message claims" in why
    _edited(knos_home)
    assert deliver(client, repo, SAID, history.NullStore(), _runners(True), "-b") == ("", 0)
    assert deliver(client, repo, "I looked at the parser.", history.NullStore(), _runners(False), "-c") == ("", 0)   # no claim


def test_aider_has_no_event_so_its_test_command_fails_with_the_reason_and_passes_when_the_checks_do(knos_home, repo, monkeypatch):
    """aider runs its test command after each edit and gives the model what it printed when the exit code is not 0
    (https://aider.chat/docs/usage/lint-test.html). There is no message to read: the command stands for "tests pass"."""
    monkeypatch.chdir(repo)
    out, code = hook.respond("aider", {}, history.NullStore(), _runners(False))
    assert code == 1 and FAILED in out and not out.startswith("{")
    _edited(knos_home)
    assert hook.respond("aider", {}, history.NullStore(), _runners(True)) == ("", 0)
    monkeypatch.setattr("sys.stdin", None)                       # and it never waits on a terminal for an event
    monkeypatch.setattr(hook, "respond", lambda client, payload: (f"{client}:{payload}", 1))
    assert hook.main_proof(["--client", "aider"]) == 1


def test_an_event_that_is_not_an_agent_finishing_is_let_through_unjudged(knos_home, repo):
    red = _runners(False)
    stop = event("cursor", repo, SAID)
    deliver("cursor", repo, SAID, history.NullStore(), _runners(True))               # afterAgentResponse was kept
    _edited(knos_home)
    for status in ("aborted", "error"):                                             # a person stopped it; the run failed
        assert hook.respond("cursor", {**stop, "status": status}, history.NullStore(), red) == ("", 0)
    assert reason("cursor", hook.respond("cursor", stop, history.NullStore(), red)[0])
    # Cursor's stop without an afterAgentResponse before it has nothing to judge
    assert hook.respond("cursor", {**stop, "conversation_id": "never-spoke"}, history.NullStore(), red) == ("", 0)
    interrupted = {**event("copilot", repo, SAID), "stopReason": "user_interrupt"}
    assert hook.respond("copilot", interrupted, history.NullStore(), red) == ("", 0)
    assert hook.respond("gemini", {}, history.NullStore(), red) == ("", 0)           # an empty event: nothing to judge
    assert hook._client(["--client", "nobody"]) == "claude" and hook._client([]) == "claude" and hook._client(["--client"]) == "claude"
    assert all(hook._client(["--client", c]) == c for c in hook.CLIENTS)


def test_vscode_running_the_copilot_file_is_answered_in_vscodes_words_unconfirmed(knos_home, repo):
    """.github/hooks/knos.json is Copilot's format, and VS Code runs it too (it maps agentStop to its Stop). The
    command then says `--client copilot` while the event is VS Code's, which is told apart by `hookEventName`."""
    out, _ = hook.respond("copilot", event("vscode", repo, SAID), history.NullStore(), _runners(False))
    assert FAILED in reason("vscode", out)


def test_after_three_blocks_on_the_same_evidence_every_host_lets_the_agent_stop(knos_home, repo, monkeypatch, capsys):
    for client in ("cursor", "gemini", "hermes"):
        for _ in range(hook.MAX_BLOCKS):
            assert reason(client, deliver(client, repo, SAID, history.NullStore(), _runners(False))[0])
        out, code = deliver(client, repo, SAID, history.NullStore(), _runners(False))
        assert code == 0 and "decision" not in out and "followup_message" not in out and "action" not in out
        said = json.loads(out)["systemMessage"] if out else capsys.readouterr().err
        assert "stopping anyway" in said, client


def test_hermes_is_told_what_was_refused_here_before_the_agent_speaks_again(knos_home, repo):
    before = _fill(HERMES_BEFORE, {"cwd": str(repo)})
    store = history.SibylStore.for_repo(repo)
    assert hook.respond("hermes", before, store, _runners(False)) == ("", 0)         # nothing refused yet: nothing said
    assert reason("hermes", deliver("hermes", repo, SAID, store, _runners(False))[0])
    out, code = hook.respond("hermes", before, history.SibylStore.for_repo(repo), None)
    told = json.loads(out)
    assert code == 0 and set(told) == {"context"} and "Knos refused 1 of 1 claims of done" in told["context"]
    assert "Still owed, whatever the message says: tests" in told["context"]
    assert hook.respond("hermes", before, history.NullStore(), None) == ("", 0)      # no Sibyl: nothing to tell
