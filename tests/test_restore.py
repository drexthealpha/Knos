"""The memory is portable, and the thing that carries it is reviewable.

The store is one file on one disk with no backup. That is the point, and it
is also the second question anybody asks. The answer is that the shareable
half is already committed to the repo: `knos export` writes
`.knos/decisions.md`, you commit it, and a fresh clone on a machine that has
never run knos carries the decisions with it.

What makes this different from a portable-state blob is that the thing being
carried is markdown a human reads in a pull request diff. Memory that restores
an agent but cannot be reviewed is memory nobody audits.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from knos import answer, paths, share
from knos.memory import TOPIC, Fact, Memory

WRITTEN = """# knos

## Decisions

- **storage** — we chose sqlite over redis for the store  _(recorded 2026-09-01)_
- **the risk guard** — refuses unknown assets  _(recorded 2026-09-02)_

## Being worked on right now

- `the parser` — held by **Claude Code** since 2026-09-06 10:00 UTC

---
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _commit_a_record(repo, text: str = WRITTEN):
    shared = repo / ".knos" / "decisions.md"
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text(text, encoding="utf-8")
    return shared


@pytest.mark.critical
def test_a_fresh_machine_gets_the_decisions_back(knos_home, repo) -> None:
    """The keepsake, and the whole reason a repo commits the file."""
    _commit_a_record(repo)
    paths.remember_pointed(repo)

    with Memory(repo) as mem:
        kept, skipped = share.restore(repo, mem)
    assert kept == 2
    assert skipped == 0

    with Memory(repo) as mem:
        found = [p.text for p in answer.ask(repo, mem, "storage sqlite")]
    assert any("sqlite over redis" in t for t in found)


def test_claims_are_not_restored(knos_home, repo) -> None:
    """A hold rebuilt on another machine would be a lie about a live collision.

    The file carries one, because CI needs to read it. Restoring it into a
    store hours later on a different machine would have knos assert that
    somebody is mid-change when nobody is, which is the one thing it must
    never say.
    """
    _commit_a_record(repo)
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        share.restore(repo, mem)
        assert mem.claims() == []


def test_restoring_twice_does_not_duplicate(knos_home, repo) -> None:
    _commit_a_record(repo)
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        first, _ = share.restore(repo, mem)
    with Memory(repo) as mem:
        second, skipped = share.restore(repo, mem)
    assert first == 2
    assert second == 0 and skipped == 2


def test_what_was_already_here_is_left_alone(knos_home, repo) -> None:
    """A restore must not overwrite a decision this machine has moved on from."""
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, "storage", {"note": "we moved to postgres", "when": "2026-09-05"})
    _commit_a_record(repo)

    with Memory(repo) as mem:
        kept, skipped = share.restore(repo, mem)
        still = mem.thing(TOPIC, "storage")
    assert skipped == 1
    assert "postgres" in str((still or {}).get("body", {}).get("note", ""))


def test_a_repo_with_no_record_restores_nothing_and_says_so(knos_home, repo) -> None:
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        assert share.restore(repo, mem) == (0, 0)


def test_a_mangled_line_is_skipped_not_fatal(knos_home, repo) -> None:
    """Nine of ten decisions back beats refusing over a stray character."""
    _commit_a_record(repo, WRITTEN.replace(
        "- **the risk guard** — refuses unknown assets  _(recorded 2026-09-02)_",
        "- **broken line with no separator",
    ))
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        kept, _ = share.restore(repo, mem)
    assert kept == 1


def test_the_round_trip_holds(knos_home, repo) -> None:
    """What export writes is what restore reads. Nothing in between."""
    paths.remember_pointed(repo)
    now = _now()
    with Memory(repo) as mem:
        mem.record(Fact(text="we pinned pnpm", source="note", where="you",
                        when=now, about="the lockfile"))
        mem.note_thing(TOPIC, "the lockfile", {"note": "we pinned pnpm", "when": now[:10]})
        share.write(repo, mem)

    # A different machine: same repo, empty store.
    paths.store_for(repo).unlink()
    with Memory(repo) as mem:
        kept, _ = share.restore(repo, mem)
        back = mem.thing(TOPIC, "the lockfile")

    assert kept >= 1
    assert "pinned pnpm" in str((back or {}).get("body", {}).get("note", ""))
