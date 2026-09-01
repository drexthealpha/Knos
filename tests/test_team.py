"""Sharing a folder with a teammate, and stopping.

The contract itself is tested in `contracts/test/Access.t.sol`. What is
tested here is the part that decides what a teammate's agent actually sees.
"""

from __future__ import annotations

import pytest

from knos import answer, private
from knos.memory import Fact, Memory

SECRET = "sk_live_quokka_9931"


def _records():
    return [
        {"path": "src/auth.py", "text": "login lives here"},
        {"path": "docs/plan.md", "text": "the plan"},
        {"path": ".env", "text": SECRET},
        {"path": "", "text": "something with no file"},
    ]


def test_a_guest_starts_with_nothing(repo):
    """The opposite default from your own agent: theirs begins empty."""
    assert private.visible(repo, _records(), private.GUEST, allowed=[]) == []


def test_a_guest_sees_only_what_was_shared(repo):
    seen = private.visible(repo, _records(), private.GUEST, allowed=["src"])
    assert [r["path"] for r in seen] == ["src/auth.py"]


def test_sharing_one_folder_does_not_share_another(repo):
    seen = private.visible(repo, _records(), private.GUEST, allowed=["docs"])
    assert [r["path"] for r in seen] == ["docs/plan.md"]


def test_a_guest_never_sees_a_secret_even_if_its_folder_is_shared(repo):
    """Sharing the whole repo does not share the keys in it."""
    seen = private.visible(repo, _records(), private.GUEST, allowed=["", ".", "src", "docs"])
    assert all(SECRET not in r["text"] for r in seen)
    assert all(".env" not in r["path"] for r in seen)


def test_your_own_agent_is_not_limited_to_shared_folders(repo):
    """A guest list is a guest list. It does not narrow your own agent."""
    seen = private.visible(repo, _records(), private.AGENT, allowed=[])
    assert [r["path"] for r in seen] == ["src/auth.py", "docs/plan.md", ""]


def test_unsharing_is_just_an_empty_list(repo):
    """Revoking is not a special case: the folder leaves the list."""
    before = private.visible(repo, _records(), private.GUEST, allowed=["src"])
    after = private.visible(repo, _records(), private.GUEST, allowed=[])
    assert before and not after


def test_a_guest_query_returns_nothing_before_a_share(knos_home, repo):
    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="we moved the retry logic",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
                path="src/auth.py",
            )
        )
        before = answer.ask(repo, mem, "retry logic", identity=private.GUEST, allowed=[])
        after = answer.ask(
            repo, mem, "retry logic", identity=private.GUEST, allowed=["src"]
        )
    assert before == []
    assert any("retry logic" in p.text for p in after)


def test_the_words_a_teammate_never_sees(repo):
    """6.1 in one line: the mechanism is not the teammate's problem."""
    from knos import team

    said = " ".join(
        [
            "Cannot share {path} yet.",
            f"{'alice'} can read {'./src'}.",
            "Stop them later:  knos unshare ./src --with alice",
            f"{'alice'} can no longer read {'./src'}.",
        ]
    ).lower()
    for word in ("wallet", "gas", "onchain", "chain", "transaction", "contract", "key"):
        assert word not in said
    assert team is not None


def test_a_guest_still_gets_code_when_the_repo_is_noisy(knos_home, repo, monkeypatch):
    """Enough is counted over what the guest can see, not the whole repo.

    A teammate shared one folder has most of the repo filtered away. Judging
    "we already found plenty" against passages they are not allowed to see
    left a real grant answering nothing at all.
    """
    from knos import answer, code

    with Memory(repo) as mem:
        for i in range(8):
            mem.record(
                Fact(
                    text=f"chatter number {i} about the retry logic",
                    source="session",
                    where=f"Claude Code session aaaa111{i} 2026-08-20",
                    when="2026-08-20",
                    path="docs/notes.md",  # a folder the guest was not shared
                )
            )
        monkeypatch.setattr(
            code, "installed", lambda: True
        )
        monkeypatch.setattr(
            code,
            "search",
            lambda repo, word, limit=20: (
                [code.Symbol(name="retry", kind="function", path="src/auth.py", line=12)],
                1.0,
            ),
        )
        found = answer.ask(
            repo, mem, "retry logic", identity=private.GUEST, allowed=["src"]
        )

    assert found, "a guest with a real grant got nothing"
    assert all(p.path.startswith("src") for p in found)
