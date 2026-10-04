"""Shared fixtures. Every test runs in its own throwaway home, with no network, no KNOS_* settings and none of the
coding agents of the machine running it, and the session fails if a test touched the real home's knos or agent
settings."""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

_REAL_HOME = Path.home()
_WATCHED = [
    _REAL_HOME / ".claude" / "settings.json",
    _REAL_HOME / ".claude.json",
    _REAL_HOME / ".codex" / "hooks.json",
    _REAL_HOME / ".sibyl-memory" / "memory.db",  # Knos remembers in Sibyl's own store: tests must never touch yours
]


def _digest(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return "absent"


@pytest.fixture(scope="session", autouse=True)
def _real_home_untouched():
    before = {p: _digest(p) for p in _WATCHED}
    yield
    changed = [str(p) for p in _WATCHED if _digest(p) != before[p]]
    assert not changed, f"a test changed the real home: {changed}"


_real_connect = socket.socket.connect


def _loopback_only(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and self.family in (
            socket.AF_INET, socket.AF_INET6):
        raise OSError(f"tests do not open the network (tried {host})")
    return _real_connect(self, address)


_AGENT_CLIS = ("claude", "codex")   # what `knos init` looks for on PATH to tell that an agent is installed (init.present)
_real_which = shutil.which


def _which_without_this_machines_agents(own: Path):
    """shutil.which, blind to the coding agents installed on the machine running the tests. `knos init` takes a
    `claude` or a `codex` on PATH as that agent being here, so a developer who has Codex would see other results than
    CI, which has neither. One a test itself puts on PATH (under pytest's own temporary directory `own`) is found."""
    def which(cmd, *args, **kwargs):
        found = _real_which(cmd, *args, **kwargs)
        if found and Path(str(cmd)).stem.lower() in _AGENT_CLIS:
            try:
                Path(found).resolve().relative_to(own)
            except ValueError:
                return None
        return found
    return which


@pytest.fixture(autouse=True)
def _isolated(tmp_path_factory, monkeypatch):
    fake = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(shutil, "which", _which_without_this_machines_agents(tmp_path_factory.getbasetemp().resolve()))
    for k in list(os.environ):
        if k.startswith("KNOS_"):
            monkeypatch.delenv(k, raising=False)
    # cargo and rustup find their toolchains under the real home: pinned before HOME moves (a test that runs cargo
    # would otherwise see no toolchain at all, as a machine with no Rust would)
    for var, folder in (("RUSTUP_HOME", ".rustup"), ("CARGO_HOME", ".cargo")):
        if not os.environ.get(var) and (_REAL_HOME / folder).is_dir():
            monkeypatch.setenv(var, str(_REAL_HOME / folder))
    # On GitHub's runners Typer forces a terminal (it reads GITHUB_ACTIONS when it is imported), so help printed there
    # is coloured: the tests read the help as a pipe gets it, on every machine
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", None, raising=False)
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    monkeypatch.setenv("APPDATA", str(fake / "AppData" / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake / ".config"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(fake / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(fake / ".codex"))
    monkeypatch.setenv("KNOS_HOME", str(fake / ".knos"))
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.setenv("SIBYL_MEMORY_DB", str(fake / ".sibyl-memory" / "memory.db"))
    monkeypatch.delenv("SIBYL_CREDENTIALS", raising=False)
    yield fake


@pytest.fixture()
def knos_home(_isolated):
    home = Path(os.environ["KNOS_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    return home


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A small real git repo, with one secret in it. Tests stand inside it, as a person or an agent would."""
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (r / ".env").write_text("STRIPE_KEY=sk_live_quokka_9931\n", encoding="utf-8")
    (r / "README.md").write_text("# demo\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(r), check=True, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "tess@example.com")
    git("config", "user.name", "Tess Marlow")
    git("add", "-A")
    git("commit", "-q", "-m", "Add login, and drop redis for sqlite\n\nRedis was one dependency for one counter.")
    monkeypatch.chdir(r)
    return r


def pytest_configure(config):
    """On Linux, put every test's throwaway home and repo on tmpfs (/dev/shm). SQLite fsyncs on commit and close; on a
    spinning disk each close costs ~0.1 s and the suite spends minutes on it. Set KNOS_TEST_TMPFS=0 to opt out.

    Only the root moves there: under it pytest makes each run a numbered directory of its own and keeps the last
    three. (One fixed directory, which pytest empties when a run starts, let a second run by the same user, in
    another checkout or another terminal, delete the first one's files while its tests were using them.)"""
    import sys
    if (sys.platform.startswith("linux") and os.path.isdir("/dev/shm") and not config.option.basetemp
            and os.environ.get("KNOS_TEST_TMPFS", "1") != "0" and not hasattr(config, "workerinput")):
        os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", "/dev/shm")


def pytest_collection_modifyitems(config, items):
    """KNOS_SHARD=i/n keeps one nth of the test files (CI splits the slow Windows runner in two)."""
    shard = os.environ.get("KNOS_SHARD")
    if not shard:
        return
    i, n = (int(x) for x in shard.split("/"))
    keep, drop = [], []
    for item in items:
        f = item.nodeid.split("::")[0]
        (keep if int(hashlib.sha256(f.encode()).hexdigest(), 16) % n == i - 1 else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep

# The tamper benchmark's sample repo and attacks are data for scripts/tamper_bench.py, not part of this suite.
collect_ignore = ["bench_tamper"]
