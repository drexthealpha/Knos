"""Shared fixtures. Every test runs against its own throwaway knos home."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def knos_home(tmp_path, monkeypatch):
    home = tmp_path / "knos-home"
    home.mkdir()
    monkeypatch.setenv("KNOS_HOME", str(home))
    return home


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A small real git repo, with one secret in it.

    Tests run standing inside it, because that is where a person runs knos
    and where an agent's client is launched. Reading now happens by itself
    for the repo you are in, so a test run from somewhere else would be
    testing a path nobody takes.
    """
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (r / ".env").write_text("STRIPE_KEY=sk_live_quokka_9931\n", encoding="utf-8")
    (r / "README.md").write_text("# demo\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(r),
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-q")
    git("config", "user.email", "tess@example.com")
    git("config", "user.name", "Tess Marlow")
    git("add", "-A")
    git(
        "commit",
        "-q",
        "-m",
        "Add login, and drop redis for sqlite\n\nRedis was one dependency for one counter.",
    )
    monkeypatch.chdir(r)
    return r
