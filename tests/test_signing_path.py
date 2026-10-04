"""The signing path imports only the standard library and solders.

The jobs that sign install nothing else (requirements/sign.txt, installed by hash), so what they run must not need the
rest of knos's dependencies: typer and rich (the command line's), sibyl-memory-client (the memory engine) and PyYAML.
Each test starts a fresh interpreter in which those four cannot be imported, whatever is installed: importing one
raises, as it would in a job that never installed it."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "knos"
BLOCKED = ("typer", "rich", "sibyl_memory_client", "yaml")
WORKFLOW_COMMANDS = ("command", "settle", "review", "check")

# Runs first in the subprocess: no module of these four can be imported, and the proof that it cannot comes first.
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
