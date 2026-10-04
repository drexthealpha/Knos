"""Every way to install Knos (docs/INSTALL.md) starts one server and one hook, and each file a host reads is what that
host's own documentation says it reads:

    .claude-plugin/marketplace.json, plugin/   the plugin Claude Code and Codex install (the hook and the server)
    gemini-extension.json                      the Gemini CLI extension (the server)
    docs/INSTALL.md                            the Cursor and VS Code links, the Codex and Copilot snippets
    action.yml                                 the free check as a GitHub Action, for a `pull_request` workflow
    .github/workflows/release.yml              what a release attaches, and publishes once a registry token exists
    glama.json                                 who may claim the listing on Glama

A manifest with a wrong key is not an error anywhere: the host skips it and nothing is installed. So the keys are
checked here, against what `knos init` writes for the same host."""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = "drexthealpha/Knos"
SERVER = {"command": "uvx", "args": ["knos", "mcp"]}     # `uvx knos mcp`: a machine with uv and nothing else can run it
PLATFORMS = ("darwin", "linux", "win32")                  # what Node calls them, and so what Gemini CLI looks for


def _text(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _json(*parts: str) -> dict:
    return json.loads(_text(*parts))


def _toml(text: str) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:   # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib.loads(text)


def _yaml(text: str) -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(text)
    if True in doc:               # YAML 1.1 reads the key `on` as True
        doc["on"] = doc.pop(True)
    return doc


def _version() -> str:
    return _toml(_text("pyproject.toml"))["project"]["version"]


def _fences(lang: str) -> list[str]:
    """The bodies of the page's code blocks in one language."""
    return [body for name, body in re.findall(r"^```(\w*)\n(.*?)^```$", _text("docs", "INSTALL.md"), re.S | re.M) if name == lang]


def _argv(hooks: dict) -> dict:
    """A hooks table with each command as the arguments a shell would run. `knos init` ends its own lines with a
    marker comment, to find them again in a file it shares with the user; a comment is no part of the command."""
    return {event: [{**group, "hooks": [{**h, "command": shlex.split(h["command"], comments=True)} for h in group["hooks"]]}
                    for group in groups] for event, groups in hooks.items()}


def _bash(script: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    """A workflow step's script, run as the runner runs `shell: bash`."""
    return subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                          env={**os.environ, **env}, cwd=str(cwd), capture_output=True, text=True, check=False)


def _needs(*tools: str) -> None:
    missing = [t for t in tools if not shutil.which(t)]
    if os.name == "nt" or missing:
        pytest.skip(f"needs {', '.join(tools)} on a POSIX shell")


# ---- the plugin and the extension ---------------------------------------------------------------------------------

def test_what_each_host_installs_is_what_knos_init_writes_with_uvx_in_place_of_the_installed_command(_isolated, monkeypatch):
    """`knos init` writes the path of the command it runs from. The plugin, the extension and the page's snippets
    write `uvx knos` in its place, and differ in nothing else: the event, the timeout, the server entry, per host."""
    from knos import init
    home = _isolated
    for folder in (".claude", ".codex", ".cursor", ".gemini"):
        (home / folder).mkdir()
    monkeypatch.setattr(init, "knos_argv", lambda: ["uvx", "knos"])
    rep = init.install()
    assert not rep["skipped"] and [h for h, _ in rep["mcp"]] == ["claude", "codex", "cursor", "gemini"]
    wrote = lambda *parts: json.loads(home.joinpath(*parts).read_text(encoding="utf-8"))  # noqa: E731
    # the server, for the two hosts that install it from a manifest in this repository
    claude = {"mcpServers": {"knos": {"type": "stdio", **SERVER}}}
    assert _json("plugin", ".mcp.json") == claude and wrote(".claude.json") == claude
    assert _json("gemini-extension.json")["mcpServers"] == wrote(".gemini", "settings.json")["mcpServers"] == {"knos": SERVER}
    # the hook: Claude Code reads hooks/hooks.json, Codex the file its own manifest names
    assert _argv(_json("plugin", "hooks", "hooks.json")["hooks"]) == _argv(wrote(".claude", "settings.json")["hooks"])
    assert _argv(_json("plugin", "hooks", "codex.json")["hooks"]) == _argv(wrote(".codex", "hooks.json")["hooks"])
    for file, host in (("hooks.json", "claude"), ("codex.json", "codex")):
        [group] = _json("plugin", "hooks", file)["hooks"]["Stop"]
        [handler] = group["hooks"]
        assert shlex.split(handler["command"]) == ["uvx", "knos", "hook", "proof", "--client", host] and handler["timeout"] == 600
    # the page's snippets for the hosts that have no manifest: Codex's config (as `codex mcp add` writes it) and Cursor's
    [codex] = [f for f in _fences("toml") if "mcp_servers" in f]
    assert codex == (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    cursor = wrote(".cursor", "mcp.json")["mcpServers"]["knos"]
    assert {k: cursor[k] for k in SERVER} == SERVER


def test_the_marketplace_lists_one_plugin_and_both_hosts_find_their_manifest_in_it():
    market = _json(".claude-plugin", "marketplace.json")
    assert market["name"] == "knos" and market["owner"]["name"] and market["description"]
    [entry] = market["plugins"]
    # a relative source starts with ./ and resolves from the repository root, not from .claude-plugin/
    assert entry == {"name": "knos", "source": "./plugin"} and (ROOT / "plugin").is_dir()
    claude, codex = _json("plugin", ".claude-plugin", "plugin.json"), _json("plugin", ".codex-plugin", "plugin.json")
    assert claude["name"] == entry["name"]              # a different name in the manifest and nobody can install it
    assert claude["description"] and claude["author"]["name"] and claude["license"] == "MIT"
    assert urlsplit(claude["homepage"]).scheme == "https"                # a homepage that is no URL fails the load
    assert not {"hooks", "mcpServers"} & set(claude)     # Claude Code finds hooks/hooks.json and .mcp.json by itself
    # Codex installs the same plugin from the same marketplace. Its manifest differs in one thing: the hooks file,
    # because a hook says which host runs it. Naming a file replaces the default hooks/hooks.json for Codex.
    assert codex == {**claude, "hooks": "./hooks/codex.json"} and (ROOT / "plugin" / "hooks" / "codex.json").is_file()
    for file in ("hooks.json", "codex.json"):
        hooks = _json("plugin", "hooks", file)
        assert set(hooks) == {"hooks"} and set(hooks["hooks"]) == {"Stop"}     # without the wrapper the file is not read


def test_the_gemini_extension_is_the_server_and_nothing_else_even_installed_from_the_whole_repository():
    ext = _json("gemini-extension.json")
    assert set(ext) == {"name", "version", "description", "mcpServers"} and re.fullmatch(r"[a-z0-9-]+", ext["name"])
    assert ext["description"] == _json("server.json")["description"]       # one sentence for the server, wherever it is listed
    # Without a release archive Gemini CLI installs the repository itself, and would load these from its root.
    for name in ("hooks", "commands", "skills", "agents", "policies", "GEMINI.md"):
        assert not (ROOT / name).exists(), f"{name} at the repository root would become part of the Gemini extension"


def test_the_registries_name_the_same_server_and_its_owner():
    server = _json("server.json")
    [package] = server["packages"]
    # a registry client turns this into `uvx knos mcp`
    assert (package["registryType"], package["identifier"], package["transport"]) == ("pypi", "knos", {"type": "stdio"})
    assert [a["value"] for a in package["packageArguments"]] == SERVER["args"][1:] and SERVER["args"][0] == package["identifier"]
    assert server["name"] in _text("docs", "INSTALL.md")
    glama = _json("glama.json")
    assert glama == {"$schema": "https://glama.ai/mcp/schemas/server.json", "maintainers": [REPO.split("/")[0]]}


def test_a_manifest_that_states_a_version_states_the_packages():
    """Claude Code keeps a user on the copy they have until the plugin's version changes, Codex files its copy under
    that version, and Gemini CLI shows the extension's version beside the release tag. All three move with the
    package (pyproject.toml)."""
    stated = {"/".join(parts): _json(*parts)["version"] for parts in (
        ("gemini-extension.json",), ("plugin", ".claude-plugin", "plugin.json"), ("plugin", ".codex-plugin", "plugin.json"))}
    stale = {where: got for where, got in stated.items() if got != _version()}
    assert not stale, f"pyproject.toml says {_version()}; these do not: {stale}"


# ---- docs/INSTALL.md -----------------------------------------------------------------------------------------------

def test_every_link_and_snippet_on_the_install_page_starts_the_same_server():
    from knos import mcp
    page = _text("docs", "INSTALL.md")
    seen = {}
    for url in re.findall(r"(?:https://|cursor://|vscode:)[^\s)]+", page):
        parts = urlsplit(url)
        if parts.scheme == "vscode":                     # vscode:mcp/install?<the whole entry, name included, URL-encoded>
            entry = json.loads(unquote(parts.query))
            name = entry.pop("name")
        elif "config=" in parts.query:
            query = parse_qs(parts.query, strict_parsing=True)
            [name], [config] = query["name"], query["config"]
            entry = json.loads(base64.b64decode(config, validate=True) if "cursor" in parts.netloc else config)
        else:
            continue
        assert (name, entry) == ("knos", SERVER), url
        seen[parts.scheme, parts.netloc] = url
    # one link a browser opens and one in the editor's own scheme, for each editor
    assert set(seen) == {("https", "cursor.com"), ("cursor", "anysphere.cursor-deeplink"), ("https", "vscode.dev"), ("vscode", "")}
    assert all(f"]({seen[key]})" in page for key in (("https", "cursor.com"), ("https", "vscode.dev")))   # the two GitHub renders
    # every JSON snippet: an entry named knos, under the key its host reads
    entries = [doc[key]["knos"] for doc in map(json.loads, _fences("json")) for key in ("mcpServers", "servers") if key in doc]
    assert len(entries) == len(_fences("json")) == 3 and all({k: e[k] for k in SERVER} == SERVER for e in entries)
    [copilot] = [e for e in entries if "tools" in e]
    tools = [t["name"] for t in mcp.TOOLS]
    # Copilot runs an allowed tool without asking, so the page allows them by name: every one, and each only reads
    assert copilot["type"] == "local" and copilot["tools"] == tools and all(t["annotations"]["readOnlyHint"] for t in mcp.TOOLS)
    assert all(f"`{t}`" in page.split("\n| For |")[0] for t in tools)      # and the page's opening names each of them
    # every command line that carries the server
    lines = [shlex.split(line, comments=True) for block in _fences("bash") for line in block.splitlines() if line.strip()]
    by_start = lambda *words: [line for line in lines if line[:len(words)] == list(words)]  # noqa: E731
    [codex] = by_start("codex", "mcp", "add")
    assert codex == ["codex", "mcp", "add", "knos", "--", SERVER["command"], *SERVER["args"]]
    [vscode] = by_start("code", "--add-mcp")
    assert json.loads(vscode[2]) == {"name": "knos", **SERVER}
    # the plugin's install id is <plugin>@<marketplace>, and the repository is the marketplace
    market = _json(".claude-plugin", "marketplace.json")
    plugin = f"{market['plugins'][0]['name']}@{market['name']}"
    for want in (["claude", "plugin", "marketplace", "add", REPO], ["claude", "plugin", "install", plugin],
                 ["codex", "plugin", "marketplace", "add", REPO], ["codex", "plugin", "add", plugin],
                 ["gemini", "extensions", "install", f"https://github.com/{REPO}"], ["pip", "install", "knos"],
                 ["uvx", "knos", "--version"], ["knos", "init"]):
        assert want in lines, want


def test_the_install_page_names_one_release_and_says_why_two_registries_are_missing():
    page = _text("docs", "INSTALL.md")
    [(tag, tarball)] = re.findall(
        r"npm install https://github\.com/drexthealpha/Knos/releases/download/v([\d.]+)/knos-settle-([\d.]+)\.tgz", page)
    [crate] = [f for f in _fences("toml") if "dependencies" in f]
    dep = _toml(crate)["dependencies"]["knos-oidc-interface"]
    assert dep == {"git": f"https://github.com/{REPO}", "tag": f"v{tag}"} and tarball == tag
    assert set(re.findall(r"drexthealpha/Knos@v([\d.]+)", page)) == {tag}
    # and no sentence about it names another release (a third party's action pin is the comment after its sha: `# v10.2.0`)
    assert set(re.findall(r"(?<!# )\bv(\d+\.\d+\.\d+)\b", page)) == {tag}
    # The page is written for the release being built, and pyproject.toml moves at the release itself: until then the
    # page may be ahead of it. It may never name an older release than the package's.
    as_numbers = lambda v: tuple(int(x) for x in v.split("."))  # noqa: E731
    assert as_numbers(tag) >= as_numbers(_version()), f"docs/INSTALL.md installs {tag}; pyproject.toml is at {_version()}"
    # the same file name and the same crate as the ones the release makes
    assert json.loads(_text("sdk", "settle", "package.json"))["name"] == "knos-settle"
    assert 'name = "knos-oidc-interface"' in _text("crates", "knos-oidc-interface", "Cargo.toml")
    release = _text(".github", "workflows", "release.yml")
    for registry, secret in (("npm", "NPM_TOKEN"), ("crates.io", "CARGO_REGISTRY_TOKEN")):
        assert f"is not on {registry}." in page and f"`{secret}`" in page and f"secrets.{secret}" in release
    # every link into the repository leads to a file, and every link into the page to a heading
    for target in re.findall(r"\]\((\.\./[^)#]+)\)", page):
        assert (ROOT / "docs" / target).resolve().exists(), target
    slug = lambda h: re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-")  # noqa: E731
    headings = {slug(h) for h in re.findall(r"^#+ (.+)$", page, re.M)}
    anchors = re.findall(r"\]\(#([^)]+)\)", page)
    assert anchors and set(anchors) <= headings, set(anchors) - headings


# ---- action.yml ----------------------------------------------------------------------------------------------------

def _action() -> dict:
    return _yaml(_text("action.yml"))


def _step(named: str) -> dict:
    [step] = [s for s in _action()["runs"]["steps"] if named in str(s.get("name", ""))]
    return step


def test_the_action_is_the_free_check_with_a_read_only_token_and_pinned_parts():
    doc = _action()
    assert doc["name"] == "Knos check" and doc["runs"]["using"] == "composite"
    assert len(doc["description"]) < 125                 # GitHub Marketplace refuses to list a longer one
    steps = doc["runs"]["steps"]
    body = json.dumps(doc["runs"])
    # nothing a `pull_request` run from a fork does not have
    assert "secrets." not in body and "id-token" not in body and "pull_request_target" not in body
    scripts = [s["run"] for s in steps if "run" in s]
    assert all(s.get("shell") == "bash" for s in steps if "run" in s)
    assert not any("${{" in script for script in scripts)             # what a pull request says reaches a script as data
    assert not any("actions/checkout" in str(s.get("uses", "")) for s in steps)
    assert all('"$RUNNER_TEMP/knos-check"' in script for script in scripts[1:])     # nothing lands in the caller's workspace
    # knos is this action's own commit (the one the caller pinned), with the dependencies uv.lock names
    install, gate = _step("install knos"), _step("knos proof gate")
    assert install["env"] == {"KNOS": "${{ github.action_path }}"} and gate["env"]["KNOS"] == "${{ github.action_path }}"
    assert shlex.split(install["run"]) == ["uv", "sync", "--quiet", "--frozen", "--python", "3.12", "--project", "$KNOS"]
    locked = next(p for p in _toml(_text("uv.lock"))["package"] if p["name"] == "knos")
    declared = {re.match(r"[A-Za-z0-9_.-]+", d).group(0).lower() for d in _toml(_text("pyproject.toml"))["project"]["dependencies"]}
    assert {d["name"] for d in locked["dependencies"]} == declared, "uv.lock no longer covers pyproject.toml: run `uv lock`"
    # the gate, without the memory a `pull_request` run could not save (check.yml, the workflow a repository calls,
    # runs `knos check`: the same check, with a funded issue's terms added)
    [command] = re.findall(r"knos proof gate (.*?); then", gate["run"], re.S)
    assert set(re.findall(r"--[a-z-]+", command)) == {"--base", "--diff", "--evidence", "--repo", "--agent", "--body-file", "--head", "--wait"}
    assert "--wait 600" in gate["run"] and '--head "$HEAD"' in gate["run"]
    assert "uv run --quiet --frozen --no-sync --project \"$KNOS\" knos proof gate" in gate["run"]
    assert doc["outputs"]["passed"]["value"] == "${{ steps.gate.outputs.passed }}" and gate["id"] == "gate"
    # every action it uses, and every one the install page tells a reader to use, is a commit listed in action_pins.json
    pins = _json("scripts", "action_pins.json")["pins"]
    used = re.findall(r"uses:\s*([\w./-]+)@(\S+)(?:\s+#\s*(\S+))?",
                      _text("action.yml").split("\nruns:")[1] + _text("docs", "INSTALL.md"))
    theirs = [(name, ref, tag) for name, ref, tag in used if name != REPO]
    assert {name for name, _ref, _tag in theirs} == {"astral-sh/setup-uv"}
    for name, ref, tag in theirs:
        assert re.fullmatch(r"[0-9a-f]{40}", ref) and pins[f"{name}@{tag}"] == ref, (name, ref, tag)


def test_the_workflow_the_install_page_gives_is_a_pull_request_workflow_of_its_own():
    from knos import judge
    [workflow] = [_yaml(f) for f in _fences("yaml") if REPO in f]
    assert set(workflow["on"]) == {"pull_request"} and workflow["permissions"] == {}
    assert "edited" in workflow["on"]["pull_request"]["types"]           # a description changed is a claim changed
    # One job, and Knos's own by its name. The judge never reads the jobs of its own run as evidence, so a test job
    # beside it would not count; and it tells its earlier runs on a commit from the checks it judges by their name.
    [(name, job)] = workflow["jobs"].items()
    failed = lambda check: [{"name": check, "status": "completed", "conclusion": "failure"}]  # noqa: E731
    assert judge.claim_check("All tests pass.", failed(name)) == [] and judge.claim_check("All tests pass.", failed("test"))
    assert job["permissions"] == {"contents": "read", "checks": "read"}
    [step] = job["steps"]
    assert re.fullmatch(r"drexthealpha/Knos@v[\d.]+", step["uses"]) and set(step) == {"uses"}
    # the Copilot agent's setup file: the job name is the one GitHub looks for, and all it does is install uv
    [setup] = [_yaml(f) for f in _fences("yaml") if "copilot-setup-steps" in f]
    [(name, job)] = setup["jobs"].items()
    assert name == "copilot-setup-steps" and job["permissions"] == {"contents": "read"}
    assert [s["uses"].split("@")[0] for s in job["steps"]] == ["astral-sh/setup-uv"]


_FAKE_GITHUB = '''\
"""api.github.com, from a file: what the job under test reads, and nothing from the network."""
import io, json, os, urllib.error, urllib.request

_pages = json.load(open(os.environ["FAKE_GITHUB"], encoding="utf-8"))


def _urlopen(req, *args, **kwargs):
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    path = url.split("api.github.com/", 1)[1]
    with open(os.environ["FAKE_GITHUB_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"path": path, "token": isinstance(req, urllib.request.Request)
                              and req.get_header("Authorization")}) + "\\n")
    if path not in _pages:
        raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b"{}"))
    return io.BytesIO(json.dumps(_pages[path]).encode())


urllib.request.urlopen = _urlopen
'''


def test_the_gitlab_job_checks_the_github_pull_request_of_its_own_pipeline(tmp_path):
    """The page's .gitlab-ci.yml job, its script run line by line as a GitLab runner runs it (bash, -e, -o pipefail),
    once per pipeline. pip is stood in for (it would download) and GitHub is a file: `knos` is this checkout's. Each
    pipeline reads the pull request GitLab named for it, its description and its head commit's checks, and fails on a
    false "tests pass"; a pull request GitHub does not answer for fails too, rather than pass unread."""
    _needs("bash")
    [workflow] = [_yaml(f) for f in _fences("yaml") if "# .gitlab-ci.yml" in f]
    [(name, job)] = workflow.items()
    assert name == "knos" and job["image"].startswith("python:3")
    # a pipeline GitLab runs for a GitHub pull request, the only kind that has one
    assert job["rules"] == [{"if": '$CI_PIPELINE_SOURCE == "external_pull_request_event"'}]
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python").write_text('#!/bin/sh\nif [ "$1 $2 $3" = "-m pip install" ]; then shift 3; echo "$@" >> "$PIP_LOG"; exit 0; fi\n'
                                 'exec "$KNOS_PYTHON" "$@"\n', encoding="utf-8")
    (fake / "knos").write_text('#!/bin/sh\nexec "$KNOS_PYTHON" -m knos "$@"\n', encoding="utf-8")
    for tool in ("python", "knos"):
        (fake / tool).chmod(0o755)
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(_FAKE_GITHUB, encoding="utf-8")
    red, green = "a" * 40, "b" * 40
    pages = {"repos/octo/widgets/pulls/12": {"number": 12, "body": "Slugs get dashes. All tests pass.", "head": {"sha": red}},
             "repos/octo/widgets/pulls/13": {"number": 13, "body": "Slugs get dashes. All tests pass.", "head": {"sha": green}},
             f"repos/octo/widgets/commits/{red}/check-runs?per_page=100&page=1":
                 {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "failure"}]},
             f"repos/octo/widgets/commits/{green}/check-runs?per_page=100&page=1":
                 {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "success"}]}}
    (tmp_path / "github.json").write_text(json.dumps(pages), encoding="utf-8")

    def pipeline(number: int, **more: str) -> tuple[subprocess.CompletedProcess, list[str], list[dict]]:
        run = tmp_path / f"pipeline-{number}"
        run.mkdir()
        env = {"CI_PIPELINE_SOURCE": "external_pull_request_event", "CI_EXTERNAL_PULL_REQUEST_IID": str(number),
               "KNOS_GITHUB_REPOSITORY": "octo/widgets",                       # the project's CI/CD variable: one value
               "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "KNOS_PYTHON": sys.executable,
               "PYTHONPATH": f"{site}{os.pathsep}{ROOT / 'src'}", "HOME": str(run), "XDG_CONFIG_HOME": str(run),
               "FAKE_GITHUB": str(tmp_path / "github.json"), "FAKE_GITHUB_LOG": str(run / "github.log"),
               "PIP_LOG": str(run / "pip.log"), "GH_TOKEN": "", "GITHUB_TOKEN": "", **more}
        done = _bash("\n".join(job["script"]), env, run)
        log = run / "github.log"
        reads = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        return done, (run / "pip.log").read_text(encoding="utf-8").split(), reads

    # the description says tests pass and a check failed at the head commit: the job fails, and says why
    done, pip, reads = pipeline(12)
    assert pip == [f"knos=={_version()}"]                                      # the release this page documents
    assert done.returncode == 1, done.stdout + done.stderr
    assert "failed at the head commit" in done.stdout and "unit" in done.stdout
    assert [r["path"] for r in reads] == ["repos/octo/widgets/pulls/12", f"repos/octo/widgets/commits/{red}/check-runs?per_page=100&page=1"]
    # the next pipeline, under the same project variables, checks its own pull request, which is true
    done, _pip, reads = pipeline(13, GH_TOKEN="glpat_masked_read_token")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "no finished check failed" in done.stdout
    assert [r["path"] for r in reads][0] == "repos/octo/widgets/pulls/13"
    assert all(r["token"] == "Bearer glpat_masked_read_token" for r in reads)       # the masked variable reaches GitHub
    # GitHub has no such pull request (or would not answer): no verdict, and the job does not pass
    done, _pip, reads = pipeline(14)
    assert done.returncode != 0 and "GitHub has nothing at repos/octo/widgets/pulls/14" in done.stdout


def test_the_action_reads_a_pull_request_without_running_it_and_judges_what_it_read(tmp_path):
    """The action's own steps, run as the runner runs them, against a throwaway origin: the base commit checked out,
    the diff from the merge base, the description byte for byte, then the gate on exactly those files. Only uv is
    stood in for (it would download): `uv run ... knos` here is this checkout's knos. GitHub is out of reach, as it is
    for a job without `checks: read`."""
    _needs("bash", "git", "jq")
    git = lambda cwd, *args: subprocess.run(  # noqa: E731
        ["git", "-c", "user.name=Tess Marlow", "-c", "user.email=tess@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    git(src, "init", "-q", "-b", "main")
    (src / "CONTRIBUTING.md").write_text("# Rules\n\n- Do not leave print() debug statements in code.\n", encoding="utf-8")
    (src / "app" / "slug.py").write_text("def slug(s):\n    return s.lower()\n", encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "base")
    base = git(src, "rev-parse", "HEAD")
    heads = {}
    for number, body in ((7, 'def slug(s):\n    print("debug", s)\n    return s.lower().replace(" ", "-")\n'),
                         (8, 'def slug(s):\n    return s.lower().replace(" ", "-")\n')):
        git(src, "checkout", "-q", "-b", f"pr{number}", "main")
        (src / "app" / "slug.py").write_text(body, encoding="utf-8")
        git(src, "commit", "-q", "-am", "slugs get dashes")
        heads[number] = git(src, "rev-parse", "HEAD")
    origin = tmp_path / "host" / "octo" / "widgets"
    origin.parent.mkdir(parents=True)
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(src, "push", "-q", str(origin), "main:refs/heads/main", "pr7:refs/pull/7/head", "pr8:refs/pull/8/head")
    workspace, fake = tmp_path / "workspace", tmp_path / "bin"
    workspace.mkdir()
    fake.mkdir()
    (fake / "uv").write_text('#!/bin/sh\n[ "$1" = sync ] && exit 0\nwhile [ "$1" != knos ]; do shift; done\nshift\n'
                             'exec "$KNOS_PYTHON" -m knos "$@"\n', encoding="utf-8")
    (fake / "uv").chmod(0o755)
    said = 'Slugs get dashes. `$(touch pwned)` "quoted" $HOME'           # a description is text, whatever it says
    steps = [s for s in _action()["runs"]["steps"] if "run" in s]

    def run(number: int, head: str, event: str = "pull_request", uv: str = "") -> tuple[list, Path]:
        temp = tmp_path / f"runner-{number}-{head[:7]}-{event}{uv}"
        temp.mkdir()
        for file in ("output", "summary"):                                   # the runner hands a step both, empty
            (temp / file).write_text("", encoding="utf-8")
        env = {"HEAD": head, "BASE": base, "NUM": str(number), "BODY": said, "AUTHOR": "tess", "KNOS": str(ROOT),
               "GH_TOKEN": "ghs_not_a_real_token", "GITHUB_SERVER_URL": (tmp_path / "host").as_uri(),
               "GITHUB_REPOSITORY": "octo/widgets", "GITHUB_EVENT_NAME": event, "RUNNER_TEMP": str(temp),
               "GITHUB_OUTPUT": str(temp / "output"), "GITHUB_STEP_SUMMARY": str(temp / "summary"),
               "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "KNOS_PYTHON": uv or sys.executable,
               "PYTHONPATH": str(ROOT / "src"), "NO_PROXY": "", "no_proxy": "",
               "HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}     # nothing listens there
        done = []
        for step in steps:
            done.append(_bash(step["run"], env, workspace))
            if done[-1].returncode:
                break
        return done, temp

    # a clean pull request passes, and the job says that it could not see the commit's checks
    done, temp = run(8, heads[8])
    assert [r.returncode for r in done] == [0, 0, 0], [r.stderr for r in done]
    work = temp / "knos-check"
    assert git(work / "base", "rev-parse", "HEAD") == base and (work / "base" / "CONTRIBUTING.md").is_file()
    assert (work / "body.md").read_text(encoding="utf-8") == said
    diff = (work / "pr.diff").read_text(encoding="utf-8")
    assert "+++ b/app/slug.py" in diff and '+    return s.lower().replace(" ", "-")' in diff
    assert (temp / "output").read_text(encoding="utf-8").split() == [f"evidence={work / 'evidence.json'}", "passed=true"]
    assert json.loads((work / "evidence.json").read_text(encoding="utf-8"))["reasons"] == []
    assert "::warning title=Knos check::" in done[2].stdout and "checks: read" in done[2].stdout
    assert (temp / "summary").read_text(encoding="utf-8") == ""
    # the token went with the fetch and stayed nowhere: not in the clone, not in the log (its encoding is masked)
    assert "ghs_not_a_real_token" not in "".join(r.stdout + r.stderr for r in done) and done[1].stdout.startswith("::add-mask::")
    assert not any(b"ghs_not_a_real_token" in f.read_bytes() or b"extraheader" in f.read_bytes()
                   for f in (work / "base" / ".git").glob("config*"))
    # one that breaks a rule of the base branch's CONTRIBUTING fails, and the summary says which rule and where
    done, temp = run(7, heads[7])
    assert [r.returncode for r in done] == [0, 0, 1]
    assert (temp / "output").read_text(encoding="utf-8").split()[-1] == "passed=false"
    heading, reason = (temp / "summary").read_text(encoding="utf-8").splitlines()
    assert heading.startswith("### Knos") and reason.startswith("- repo rule: app/slug.py:2") and "CONTRIBUTING.md:3" in reason
    assert not list(workspace.iterdir()) and not (tmp_path / "pwned").exists()     # the workspace is the caller's
    # what it says when it cannot go on, and that it stops there
    done, temp = run(7, "", event="push")
    assert [r.returncode for r in done] == [0, 1] and "this run is a push" in done[1].stdout
    done, temp = run(7, heads[8])                                            # the event named a head that has since moved
    assert [r.returncode for r in done] == [0, 1] and "newer head commit" in done[1].stdout
    done, temp = run(8, heads[8], uv="false")                                # knos itself cannot start: no verdict, no pass
    assert [r.returncode for r in done] == [0, 0, 1] and "before it reached a verdict" in done[2].stdout
    assert "passed=" not in (temp / "output").read_text(encoding="utf-8") and (temp / "summary").read_text(encoding="utf-8") == ""


# ---- a release -----------------------------------------------------------------------------------------------------

def _job(name: str) -> tuple[dict, dict]:
    job = _yaml(_text(".github", "workflows", "release.yml"))["jobs"][name]
    [step] = [s for s in job["steps"] if "run" in s]
    return job, step


def _gemini_picks(assets: list[str], platform: str, arch: str) -> str | None:
    """Which release asset Gemini CLI installs as the extension (its findReleaseAsset): one named for the platform,
    else the only asset there is, else none, and then it takes the tag's source archive."""
    for prefix in (f"{platform}.{arch}.", f"{platform}."):
        for name in assets:
            if name.lower().startswith(prefix):
                return name
    return assets[0] if len(assets) == 1 and not any(p in assets[0].lower() for p in PLATFORMS) else None


def test_a_release_attaches_the_extension_under_the_names_gemini_cli_looks_for(tmp_path):
    _needs("bash", "jq", "tar")
    job, step = _job("gemini")
    # behind the release gate: it needs the test job of the same run, and the release it attaches to
    assert job["needs"] == ["tests", "github-release"] and "if" not in job and job["permissions"] == {"contents": "write"}
    shutil.copy(ROOT / "gemini-extension.json", tmp_path)
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$GH_LOG"\n', encoding="utf-8")
    (fake / "gh").chmod(0o755)
    env = {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(tmp_path / "gh.log"), "GH_TOKEN": "x",
           "GITHUB_REPOSITORY": REPO}
    r = _bash(step["run"], {**env, "TAG": "v0.0.0"}, tmp_path)               # a tag the manifest does not carry
    assert r.returncode != 0 and not list(tmp_path.glob("*.tar.gz")) and not (tmp_path / "gh.log").exists()
    tag = f"v{_version()}"
    r = _bash(step["run"], {**env, "TAG": tag}, tmp_path)
    assert r.returncode == 0, r.stderr
    archives = [f"{platform}.knos.tar.gz" for platform in PLATFORMS]
    uploaded = (tmp_path / "gh.log").read_text(encoding="utf-8").split()
    assert uploaded[:3] == ["release", "upload", tag] and uploaded[-3:] == ["--clobber", "--repo", REPO]
    assert sorted(uploaded[3:-3]) == archives == sorted(p.name for p in tmp_path.glob("*.tar.gz"))
    for archive in archives:                                                  # the manifest at the archive's root, alone
        listed = subprocess.run(["tar", "-tzf", archive], cwd=str(tmp_path), capture_output=True, text=True, check=True)
        assert listed.stdout.split() == ["gemini-extension.json"]
    # Why the job exists: the client's tarball used to be a release's only asset, Gemini CLI takes an only asset for
    # the extension, and it cannot unpack a .tgz. With the archives beside it, every platform gets the extension.
    tarball = f"knos-settle-{_version()}.tgz"
    release = _text(".github", "workflows", "release.yml")
    assert "npm pack --pack-destination ../../dist" in release and 'gh release create "$TAG" dist/*' in release
    assert _gemini_picks([tarball], "linux", "x64") == tarball and not tarball.endswith((".tar.gz", ".zip"))
    for platform in PLATFORMS:
        for arch in ("x64", "arm64"):
            assert _gemini_picks([tarball, *archives], platform, arch) == f"{platform}.knos.tar.gz"
    assert _gemini_picks([tarball, *archives], "freebsd", "x64") is None and (ROOT / "gemini-extension.json").is_file()


def test_a_release_publishes_to_a_registry_only_when_its_token_exists(tmp_path):
    _needs("bash")
    for name, secret, variable, package, publish in (
            ("crates", "CARGO_REGISTRY_TOKEN", "CARGO_REGISTRY_TOKEN", "knos-oidc-interface", "cargo publish --locked"),
            ("npmjs", "NPM_TOKEN", "NODE_AUTH_TOKEN", "knos-settle", "npm publish --provenance --access public")):
        job, step = _job(name)
        assert job["needs"] == ["tests", "pypi"] and "if" not in job           # behind the release gate, after PyPI
        # the token is in one step's environment, and in no file: npm is given the variable's name
        assert step["env"] == {variable: f"${{{{ secrets.{secret} }}}}", "TAG": "${{ github.ref_name }}"}
        assert json.dumps(job).count("secrets.") == 1 and "${{" not in step["run"]
        # without it: one line that says so, and the job passes without having touched anything
        r = _bash(step["run"], {variable: "", "TAG": "v9.9.9"}, tmp_path)
        [line] = r.stdout.splitlines()
        assert r.returncode == 0 and line.startswith("::notice ") and secret in line and f"{package} v9.9.9" in line
        assert not list(tmp_path.iterdir())
        # with it: the version is the tag's, a version the registry has is left alone, and only then the publish
        run = step["run"]
        assert run.index('test "v$version" = "$TAG"') < run.index("already has") < run.index(publish)
        assert run.rstrip().endswith(publish)
    assert _job("crates")[0]["permissions"] == {"contents": "read"}
    assert _job("npmjs")[0]["permissions"] == {"contents": "read", "id-token": "write"}      # id-token: npm's provenance
    assert "'//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}\\n'" in _job("npmjs")[1]["run"]
