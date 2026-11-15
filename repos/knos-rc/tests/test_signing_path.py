"""The signing path imports only the standard library and solders.

The jobs that sign install nothing else (requirements/sign.txt, installed by hash), so what they run must not need the
rest of knos's dependencies: typer, rich and click (the command line's), sibyl-memory-client (the memory engine) and
PyYAML. Each test starts a fresh interpreter in which those cannot be imported, whatever is installed: importing one
raises, as it would in a job that never installed it. The public worker is such a job (worker.yml), and what it runs
is `python -m knos relay`: 0.3.13 read that command with typer, so every run of the worker failed at once. The relay
is held to the list here twice: run with those packages unimportable, and read statically, import by import."""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "knos"
BLOCKED = ("typer", "rich", "click", "sibyl_memory_client", "yaml")
WORKFLOW_COMMANDS = ("command", "settle", "review", "check")

# Runs first in the subprocess: no module of these can be imported, and the proof that it cannot comes first.
REFUSE = f"""
import importlib.abc, sys
BLOCKED = {BLOCKED!r}


class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(name + " is not installed in a job that signs")


sys.meta_path.insert(0, Refuse())
for _name in BLOCKED:
    sys.modules[_name] = None            # `import typer` and `from rich.console import Console` both raise
    try:
        __import__(_name)
    except ImportError:
        pass
    else:
        raise SystemExit("the stub for " + _name + " does not raise")
"""


def _run(code: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-c", REFUSE + code], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120, check=False)


def _entry() -> tuple[str, str]:
    """The module and function of the `knos` console script, as pyproject.toml names them."""
    try:
        import tomllib
    except ModuleNotFoundError:   # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    module, _, function = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]["knos"].partition(":")
    return module, function


def _top_level_imports(path: Path) -> set[str]:
    """The packages a module imports when it is imported: not inside a function, which runs later, if at all."""
    found: set[str] = set()

    def walk(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
            elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for field in ("body", "orelse", "finalbody", "handlers"):
                    inner = getattr(node, field, [])
                    walk([n for h in inner for n in (h.body if isinstance(h, ast.ExceptHandler) else [h])] if field == "handlers" else inner)

    walk(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def test_what_the_four_commands_do_imports_only_the_standard_library_and_solders():
    """knos.flow (the four commands: command, settle, review, check) and everything it reaches: the judge, the claim
    parser, the history, the memory, the chain, the relay."""
    modules = ["knos.flow", "knos.judge", "knos.chain", "knos.terms", "knos.who", "knos.commands", "knos.closing", "knos.settle.v2.pay",
               "knos.settle.v2.relay", "knos.settle.v2.oidc", "knos.proof.ghrelay", "knos.proof.claims", "knos.proof.history",
               "knos.proof.memory", "knos.proof.checks", "knos.proof.engine", "knos.store"]
    got = _run(f"""
import importlib
for name in {modules!r}:
    importlib.import_module(name)
loaded = sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] in BLOCKED)
print("LOADED", loaded)
""")
    assert got.returncode == 0, got.stderr[-1500:]
    assert "LOADED []" in got.stdout


def test_only_the_command_line_shell_imports_the_packages_a_job_that_signs_does_not_install():
    """Which files import typer, rich, sibyl-memory-client or PyYAML when they are imported. Everything but the shell
    of the command line (knos/cli.py and knos/proof/cli.py) is clean; the memory engine is imported inside functions
    only (knos/store.py), so a command that never opens the store never loads it."""
    importers = {p.relative_to(SRC).as_posix(): sorted(_top_level_imports(p) & set(BLOCKED)) for p in sorted(SRC.rglob("*.py"))}
    importers = {name: found for name, found in importers.items() if found}
    assert set(importers) <= {"cli.py", "proof/cli.py"}, f"a module a command reaches imports what a signing job lacks: {importers}"


def test_the_four_workflow_commands_answer_help_with_typer_rich_sibyl_and_yaml_unimportable():
    module, function = _entry()
    got = _run(f"""
import contextlib, importlib, io
main = getattr(importlib.import_module({module!r}), {function!r})
for command in {WORKFLOW_COMMANDS!r}:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            rc = main([command, "--help"])
        except SystemExit as stop:
            rc = stop.code
    assert not rc, command + " --help ended " + repr(rc)
    assert "--event" in out.getvalue() and "--repo" in out.getvalue(), command + " --help does not say its options"
for command, option in (("attest", "--order"), ("canary", "--amount")):       # the two that take other options: the same entry
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main([command, "--help"])
    assert not rc and option in out.getvalue(), command + " --help does not say its options"
print("HELP", {WORKFLOW_COMMANDS!r})
loaded = sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] in BLOCKED)
assert not loaded, loaded
""")
    assert got.returncode == 0, got.stderr[-1500:]
    assert "HELP" in got.stdout


# ---- `knos relay`, which the public worker runs on the same install --------------------------------------------------------

def _module(args: list[str], tmp_path, **env) -> subprocess.CompletedProcess:
    """`python -m knos <args>` in a fresh interpreter that refuses the packages before anything of knos is imported
    (a sitecustomize, which Python runs at startup)."""
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(REFUSE, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(site), str(ROOT / "src")]), "PYTHONDONTWRITEBYTECODE": "1", "KNOS_HOME": str(tmp_path / "home"), **env}
    return subprocess.run([sys.executable, "-m", "knos", *args], cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120, check=False)


def test_python_m_knos_relay_help_works_with_typer_rich_and_click_unimportable(tmp_path):
    """The worker's first step after the install (worker.yml), as it runs it."""
    got = _module(["relay", "--help"], tmp_path)
    assert got.returncode == 0, got.stderr[-1500:]
    assert all(option in got.stdout for option in ("--serve", "--every", "--token-file", "--terms-file"))
    # the refusal is in force in that interpreter: a command the full command line reads fails there, loudly
    other = _module(["balance"], tmp_path)
    assert other.returncode != 0 and "import typer" in other.stderr and "ModuleNotFoundError" in other.stderr


def test_a_relay_pass_and_the_serve_loop_run_against_a_fake_github_with_typer_rich_and_click_unimportable(tmp_path):
    """`knos relay` and `knos relay --serve` from the entry the worker uses, with GitHub and the relays as
    tests/test_worker.py fakes them: a posted token is read, carried and logged, and the status is 0."""
    got = _run(f"""
import json, os, time
sys.path.insert(0, {str(ROOT / "tests")!r})
os.environ.update(KNOS_HOME={str(tmp_path / "home")!r}, GH_TOKEN="t", KNOS_RELAY_KEY=json.dumps(list(bytes(__import__("solders.keypair").keypair.Keypair()))))
os.environ.pop("KNOS_RELAY_REPOS", None)
import importlib
from test_worker import GitHub, Ledger, Relays, TERMS, fund_aud, jwt
from knos import chain
from knos.proof import ghrelay
main = getattr(importlib.import_module({_entry()[0]!r}), {_entry()[1]!r})
gh, relays = GitHub(), Relays()
gh.issues[ghrelay.HOME_REPO] = [{{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}}]
gh.search = ["octo/widgets"]
ghrelay._HUB, ghrelay.relay_one, chain.ledger = ghrelay.Hub(gh.open), relays, Ledger
gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", jwt(fund_aud(7)), TERMS))
assert main(["relay"]) == 0 and len(relays.calls) == 1, relays.calls
gh.comment("octo/widgets", 8, ghrelay.token_comment("fund", jwt(fund_aud(8), iat=1003), TERMS))
assert main(["relay", "--serve", "0.5", "--every", "0.1"]) == 0 and len(relays.calls) == 2, relays.calls
assert [ln.split()[:3] for ln in gh.log()] == [["knos-relay", "fund", "octo/widgets#7"], ["knos-relay", "fund", "octo/widgets#8"]], gh.log()
loaded = sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] in BLOCKED)
assert not loaded, loaded
print("RELAYED", len(relays.calls))
""")
    assert got.returncode == 0, got.stderr[-2500:]
    assert "RELAYED 2" in got.stdout and "knos-relay fund octo/widgets#7" in got.stdout


# -- read statically: every import the relay, and each word a workflow runs, can reach ----------------------------------------

def _installed() -> set[str]:
    """What a module may import in a job that installs requirements/sign.txt: the standard library, knos, and the
    packages that file names (each imported under its name with `-` as `_`). The standard library is Python 3.12's,
    the one those jobs make their venv with: tomllib is in it, though not in 3.10's, where this test runs too."""
    names = re.findall(r"^([A-Za-z0-9_.-]+)==", (ROOT / "requirements" / "sign.txt").read_text(encoding="utf-8"), re.MULTILINE)
    assert "solders" in names and not {"typer", "rich", "click"} & set(names)
    assert 'uv venv --no-config --python 3.12 "$RUNNER_TEMP/knos"' in (ROOT / ".github" / "workflows" / "prove.yml").read_text(encoding="utf-8")
    return {n.lower().replace("-", "_") for n in names} | set(sys.stdlib_module_names) | {"tomllib"} | {"knos"}


def _file(module: str) -> Path | None:
    base = ROOT / "src" / Path(*module.split("."))
    return base / "__init__.py" if base.is_dir() else base.with_suffix(".py") if base.with_suffix(".py").is_file() else None


def _missing(handler: ast.ExceptHandler) -> bool:
    names = {n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)} if handler.type is not None else set()
    return bool(names & {"ImportError", "ModuleNotFoundError"})


def _imports(module: str, inside: tuple[str, ...] | None = None) -> set[str]:
    """Every module `module` imports, at any depth: at import time and inside its functions (an import inside a
    function is reached when the function runs). `inside`: only the top level and these functions. Not counted: the
    fallback in `except ImportError:`, which runs only where the first choice is missing (tomli for tomllib on 3.10)."""
    path = _file(module)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ExceptHandler) and _missing(child):
                continue
            if inside is not None and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name not in inside:
                continue
            if isinstance(child, ast.Import):
                found.update(a.name for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                base = child.module or ""
                if child.level:
                    parts = package.split(".")
                    base = ".".join(parts[:len(parts) - child.level + 1] + ([child.module] if child.module else []))
                found.add(base)
                found.update(f"{base}.{a.name}" for a in child.names if base.split(".")[0] == "knos" and _file(f"{base}.{a.name}"))
            walk(child)

    walk(ast.parse(path.read_text(encoding="utf-8")))
    return found


def _reach(start: dict[str, tuple[str, ...] | None], skip: frozenset = frozenset()) -> tuple[set[str], dict[str, set[str]]]:
    """From the modules of `start` (each read whole, or only in the functions named), every knos module reached and,
    for every other package imported on the way, the knos modules that import it."""
    seen: set[str] = set()
    outside: dict[str, set[str]] = {}
    todo = list(start)
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        for name in _imports(module, start.get(module)):
            if name.split(".")[0] != "knos":
                outside.setdefault(name.split(".")[0], set()).add(module)
                continue
            while not _file(name):          # `from .proof.ghrelay import TOKEN`: the module is knos.proof.ghrelay
                name = name.rpartition(".")[0]
            if name not in skip:
                todo.append(name)
    return seen, outside


# What `python -m knos relay ...` runs in knos.flow: the entry, the parser, and the relay's own functions.
RELAY = ("takes", "_parser", "_dispatch", "main", "relay", "_relay_file", "_relay_serve", "_err", "_short")
# The memory engine, imported inside the two functions of knos/store.py that open it. A job that signs does not install
# it, and every caller in knos.flow goes on without it (`_memory`, `_gate`: "the engine is not installed in this job").
OPTIONAL = {"sibyl_memory_client": {"knos.store"}}


def test_every_import_the_relay_can_reach_is_the_standard_library_or_a_package_of_sign_txt():
    """From `python -m knos`, through knos.flow's relay entry, to everything the worker and the relays import, inside
    functions too. The one import left out is the full command line (knos.cli), which knos.__main__ loads only for a
    word knos.flow does not take: `relay`, with every option the worker gives it, is taken."""
    from knos import flow
    for line in (["relay"], ["relay", "--help"], ["relay", "--serve", "250"], ["relay", "--serve", "30", "--every", "3"],
                 ["relay", "--token-file", "t"], ["relay", "--token", "t", "--terms-file", "x"]):
        assert flow.takes(line), line
    assert all(hasattr(flow, name) for name in RELAY)
    seen, outside = _reach({"knos.__main__": None, "knos.flow": RELAY}, skip=frozenset({"knos.cli"}))
    assert {"knos.flow", "knos.proof.ghrelay", "knos.chain", "knos.paths", "knos.settle.relay", "knos.settle.v2.relay", "knos.settle.v2.pay"} <= seen
    extra = {name: sorted(by) for name, by in outside.items() if name not in _installed()}
    assert not extra, f"`knos relay` reaches a package the worker does not install (requirements/sign.txt): {extra}"
    assert "solders" in outside                                  # the walk does see what is imported
    # and it would have caught 0.3.13: the full command line, where `relay` was read then, imports typer
    assert "typer" in _reach({"knos.cli": None})[1]


def test_every_import_a_workflows_word_can_reach_is_the_standard_library_or_a_package_of_sign_txt():
    """The same walk for the words a repository's workflow runs on the same install (flow.WORDS, and attest, canary,
    relay): all of knos.flow, every function of it, and everything it reaches."""
    from knos import flow
    assert set(flow.WORDS) == set(WORKFLOW_COMMANDS) and {"attest", "canary", "relay"} <= set(flow.MORE)
    assert all(flow.takes([word, "--help"]) for word in (*flow.WORDS, *flow.MORE))
    seen, outside = _reach({"knos.__main__": None, "knos.flow": None}, skip=frozenset({"knos.cli"}))
    assert "knos.cli" not in seen and "knos.proof.cli" not in seen and {"knos.judge", "knos.proof.history", "knos.proof.memory", "knos.records"} <= seen
    extra = {name: by for name, by in outside.items() if name not in _installed() and by != OPTIONAL.get(name)}
    assert not extra, f"a word a workflow runs reaches a package its job does not install (requirements/sign.txt): {extra}"
