"""What the command line costs before it does anything: `knos --version` answers without importing the command line at
all, one command loads its own module and no other, and loading modules one at a time changes nothing `knos --help` says.

Every check runs a fresh interpreter, because what is being measured is what a fresh interpreter imports. The one
timing is a ratio against `python -c pass` measured in the same test on the same machine, the least of five runs of
each: a slow runner slows both."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import knos

SRC = str(Path(knos.__file__).resolve().parents[1])
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(x for x in (SRC, os.environ.get("PYTHONPATH", "")) if x),
       "PYTHONIOENCODING": "utf-8", "COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"}
HEAVY = ("solders", "rich", "typer", "click", "httpx", "requests", "mcp", "cryptography")     # nothing a version number needs
COMMAND_MODULES = ("knos.judge", "knos.terms_templates", "knos.ledger", "knos.bundle", "knos.audit", "knos.agentkey", "knos.records",
                   "knos.controls", "knos.observe", "knos.reproduce")


def _python(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8", env=ENV, timeout=300)


def _modules_after(argv: list[str], entry: str = "knos.__main__") -> tuple[int, list[str]]:
    """Run `knos <argv>` in a fresh interpreter through `entry`.main and say what it had imported when it returned."""
    probe = ("import io, json, sys, contextlib, importlib\n"
             "said = io.StringIO()\n"
             "with contextlib.redirect_stdout(said):\n"
             f"    rc = importlib.import_module({entry!r}).main({argv!r})\n"
             "print(json.dumps([rc, sorted(sys.modules)]))\n")
    got = _python("-c", probe)
    assert got.returncode == 0, got.stderr
    rc, names = json.loads(got.stdout.strip().splitlines()[-1])
    return rc, names


def _has(names: list[str], package: str) -> bool:
    return any(n == package or n.startswith(package + ".") for n in names)


def test_version_imports_nothing_but_the_package():
    rc, names = _modules_after(["--version"])
    assert rc == 0
    assert [p for p in HEAVY if _has(names, p)] == []
    ours = sorted(n for n in names if _has([n], "knos"))
    assert ours == ["knos", "knos.__main__"], ours        # not the command line, not knos.flow, not one command's module


def test_version_says_the_same_through_the_fast_way_and_the_command_line():
    fast = _python("-m", "knos", "--version")
    full = _python("-c", "import sys; from knos import cli; sys.exit(cli.main(['--version']))")
    assert fast.returncode == full.returncode == 0
    assert fast.stdout == full.stdout and fast.stdout == f"knos {knos.version()}\n"


def test_the_words_asked_about_before_importing_the_flow_are_the_flows_own():
    from knos import flow
    from knos.__main__ import FLOW_FIRST
    assert FLOW_FIRST == (*flow.WORDS, *flow.MORE)


def test_one_command_loads_no_other_commands_module():
    rc, names = _modules_after(["bounty", "--help"])
    assert rc == 0
    assert [m for m in (*COMMAND_MODULES, "knos.flow") if m in names] == []
    assert not _has(names, "solders")           # `knos bounty --help` needs no key and no chain
    rc, names = _modules_after(["audit", "--help"])
    assert rc == 0 and "knos.audit" in names
    assert [m for m in ("knos.judge", "knos.bundle", "knos.agentkey", "knos.terms_templates", "knos.flow",
                              "knos.observe", "knos.reproduce") if m in names] == []     # knos.controls: the export's `authorised_by` reads it
    rc, names = _modules_after(["budget", "--help"])
    assert rc == 0 and "knos.controls" in names
    assert [m for m in ("knos.observe", "knos.reproduce", "knos.audit", "knos.judge", "knos.flow") if m in names] == []
    rc, names = _modules_after(["shadow", "--help"])
    assert rc == 0 and "knos.shadow" in names
    assert [m for m in (*(m for m in COMMAND_MODULES if m != "knos.shadow"), "knos.flow") if m in names] == [] and not _has(names, "solders")
    rc, names = _modules_after(["terms", "cite", "bugfix"])
    assert rc == 0 and "knos.terms_registry" in names and "knos.shadow" not in names and not _has(names, "solders")


def test_a_workflows_word_never_imports_the_command_line():
    rc, names = _modules_after(["canary", "--help"])
    assert not _has(names, "typer") and not _has(names, "rich") and "knos.cli" not in names


def test_the_help_is_the_same_whatever_was_loaded_first():
    whole = _python("-c", "import sys; from knos import cli; sys.exit(cli.main(['--help']))")
    after = _python("-c", "import contextlib, io, sys; from knos import cli\n"
                          "with contextlib.redirect_stdout(io.StringIO()):\n"
                          "    for first in (['audit', '--help'], ['work', '--help'], ['bounty', '--help'], ['meter', '--help'], ['receipt', '--help'],\n"
                          "                  ['reproduce', '--help'], ['observe', '--help'], ['budget', '--help']):\n"
                          "        cli.main(first)\n"
                          "sys.exit(cli.main(['--help']))")
    assert whole.returncode == after.returncode == 0 and whole.stdout == after.stdout
    for name in ("judge", "terms", "meter", "bundle", "receipt", "audit", "agent", "work", "budget", "observe", "reproduce", "shadow"):
        assert f" {name} " in whole.stdout, name
    for names in (("meter", "audit", "budget"), ("observe", "reproduce", "shadow")):    # groups, then commands: each in the order named
        order = [whole.stdout.index(f" {name} ") for name in names]
        assert order == sorted(order), names


def test_asking_for_the_whole_command_line_by_name_gives_every_command():
    got = _python("-c", "from typer.main import get_command; from knos import cli\n"
                        "print(' '.join(sorted(get_command(cli.app).commands)))")
    assert got.returncode == 0, got.stderr
    assert {"judge", "terms", "meter", "bundle", "receipt", "audit", "agent", "work", "bounty", "check", "budget", "observe", "reproduce", "shadow"} <= set(got.stdout.split())


def _first_byte(args: list[str]) -> float:
    """Seconds from starting the interpreter to its first byte of output (or to its end, for a command that prints nothing)."""
    began = time.perf_counter()
    with subprocess.Popen([sys.executable, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV) as p:
        assert p.stdout is not None
        p.stdout.read(1)
        took = time.perf_counter() - began
        p.stdout.read()
    assert p.returncode == 0
    return took


def test_version_answers_within_a_few_interpreter_starts():
    """Importing the command line for a version number cost about eighteen bare interpreter starts where this was
    measured; answering from the metadata costs about four. Ten is the line: far from both."""
    bare = min(_first_byte(["-c", "pass"]) for _ in range(5))
    ours = min(_first_byte(["-m", "knos", "--version"]) for _ in range(5))
    assert ours < 10 * bare, f"knos --version: {ours * 1000:.0f} ms, a bare interpreter: {bare * 1000:.0f} ms"
