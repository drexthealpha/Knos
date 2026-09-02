"""Secrets are private on a fresh index, and invisible rather than redacted."""

from __future__ import annotations

import pytest

from knos import answer, private
from knos.memory import Fact, Memory

SECRET = "sk_live_quokka_9931"


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "./.env",
        "deploy/.env.production",
        "src/app/.env",
        "certs/server.pem",
        "keys/id_rsa",
        "home/.ssh/config",
        ".aws/credentials",
        ".npmrc",
    ],
)
def test_private_without_being_asked(repo, path):
    assert private.is_private(repo, path)


@pytest.mark.parametrize("path", ["src/auth.py", "README.md", "envfile", "documents/pem.md"])
def test_ordinary_files_are_not_private(repo, path):
    assert not private.is_private(repo, path)


def test_knos_private_adds_a_path(knos_home, repo):
    assert not private.is_private(repo, "notes/salary.md")
    private.add(repo, "notes/salary.md")
    assert private.is_private(repo, "notes/salary.md")


# ---- the counter-test -------------------------------------------------
#
# This calls the search layer directly with an agent identity, rather than
# going through the MCP server. An agent must get no hint that the content
# exists: not a redaction, not a count, not a placeholder.


def _seed(repo):
    mem = Memory(repo)
    mem.record(
        Fact(
            text=f"the stripe key is {SECRET}",
            source="session",
            where="Claude Code session aaaa1111 2026-08-20",
            when="2026-08-20",
            about="stripe",
            path=".env",
        )
    )
    mem.record(
        Fact(
            text="login lives in src/auth.py",
            source="session",
            where="Claude Code session aaaa1111 2026-08-20",
            when="2026-08-20",
            about="auth",
            path="src/auth.py",
        )
    )
    return mem


def test_an_agent_gets_no_hint_the_secret_exists(knos_home, repo):
    mem = _seed(repo)
    try:
        found = answer.ask(repo, mem, "stripe key", identity=private.AGENT)
        blob = " ".join(p.text + p.where for p in found).lower()
        assert SECRET not in blob
        assert ".env" not in blob
        for word in ("hidden", "redacted", "private", "withheld", "results"):
            assert word not in blob
    finally:
        mem.close()


def test_the_owner_can_still_search_it(knos_home, repo):
    mem = _seed(repo)
    try:
        found = answer.ask(repo, mem, "stripe key", identity=private.OWNER)
        assert any(SECRET in p.text for p in found)
    finally:
        mem.close()


def test_the_agent_still_sees_ordinary_things(knos_home, repo):
    """So the emptiness above is the rule working, not the search failing."""
    mem = _seed(repo)
    try:
        found = answer.ask(repo, mem, "login auth", identity=private.AGENT)
        assert any("src/auth.py" in p.text or "src/auth.py" in p.path for p in found)
    finally:
        mem.close()


def test_asking_about_the_same_repo_does_not_reread_the_rules_each_time(
    knos_home, repo, monkeypatch
):
    """Reading a repo asks this once per file in every commit.

    On the kernel that was 93,703 calls, each one opening the rules file and
    creating a directory to find it: 305 of the 317 seconds a read took.
    """
    from knos import private

    private.is_private(repo, "src/auth.py")

    reads = []
    real = private.added_patterns

    def counted(r):
        reads.append(r)
        return real(r)

    monkeypatch.setattr(private, "added_patterns", counted)
    for i in range(500):
        private.is_private(repo, f"src/file{i}.py")
    assert reads == [], f"re-read the rules {len(reads)} times"

    # And a new private path still takes effect on the very next question.
    private.add(repo, "notes/salary.md")
    assert private.is_private(repo, "notes/salary.md")


def test_a_secret_in_a_shouted_filename_is_still_a_secret(knos_home, repo):
    from knos import private

    assert private.is_private(repo, ".ENV")
    assert private.is_private(repo, "config/.Env")
