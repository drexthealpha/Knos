"""You cannot quietly edit the record of who overrode whom.

An override is the one thing in knos an agent does *against* somebody else's
work, and the only cost it carries is that it goes in the journal under its
own name. If that line can be edited or dropped afterwards the cost is zero,
and the override was never really a cost at all. Same for a stand-down: "who
yielded to whom" is worth nothing if either party can rewrite it later.

So each writer's entries are chained. These tamper with the SQLite file
directly - the way somebody covering their tracks would, rather than through
any knos API - and check that the break is found and named.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from knos import paths, seal
from knos.memory import Fact, Memory

TABLE = "journal_events"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wrote(mem: Memory, who: str, n: int) -> None:
    for i in range(n):
        mem.record(Fact(text=f"{who} said {i}", source="session",
                        where=who, when=_now(), about="the parser"))


def _rows(repo, like: str):
    con = sqlite3.connect(paths.store_for(repo))
    try:
        return con.execute(
            f"SELECT id, extra FROM {TABLE} WHERE extra LIKE ?", (f"%{like}%",)
        ).fetchall()
    finally:
        con.close()


def _write_row(repo, ident, extra) -> None:
    con = sqlite3.connect(paths.store_for(repo))
    try:
        con.execute(f"UPDATE {TABLE} SET extra=? WHERE id=?", (json.dumps(extra), ident))
        con.commit()
    finally:
        con.close()


def _delete_row(repo, ident) -> None:
    con = sqlite3.connect(paths.store_for(repo))
    try:
        con.execute(f"DELETE FROM {TABLE} WHERE id=?", (ident,))
        con.commit()
    finally:
        con.close()


@pytest.fixture()
def written(knos_home, repo):
    with Memory(repo) as mem:
        _wrote(mem, "Claude Code", 4)
        _wrote(mem, "Cursor", 3)
    return repo


def test_an_untouched_journal_adds_up(written) -> None:
    with Memory(written) as mem:
        assert seal.check(mem) == []
        assert seal.counted(mem) == {"sealed": 7, "writers": 2}


@pytest.mark.critical
def test_editing_one_entry_is_found_and_named(written) -> None:
    ident, extra = _rows(written, "Claude Code said 1")[0]
    body = json.loads(extra)
    body["text"] = "Claude Code said 1 (edited)"
    _write_row(written, ident, body)

    with Memory(written) as mem:
        broken = seal.check(mem)

    assert len(broken) == 1, broken
    assert broken[0]["who"] == "Claude Code"
    assert "edited" in broken[0]["text"]


@pytest.mark.critical
def test_removing_an_entry_is_found(written) -> None:
    """Deleting a line is the more likely way to cover a track."""
    ident, _ = _rows(written, "Claude Code said 1")[0]
    _delete_row(written, ident)

    with Memory(written) as mem:
        broken = seal.check(mem)

    assert broken, "an entry was removed and every chain still added up"
    assert broken[0]["who"] == "Claude Code"
    assert "missing" in broken[0]["found"]


def test_one_edit_does_not_redden_every_line_after_it(written) -> None:
    """A report where one change condemns twenty entries hides which one."""
    ident, extra = _rows(written, "Claude Code said 0")[0]
    body = json.loads(extra)
    body["about"] = "something else"
    _write_row(written, ident, body)

    with Memory(written) as mem:
        broken = seal.check(mem)

    assert len(broken) == 1, f"one edit reported as {len(broken)} breaks"


def test_one_writer_being_tampered_with_leaves_the_others_alone(written) -> None:
    ident, extra = _rows(written, "Cursor said 0")[0]
    body = json.loads(extra)
    body["text"] = "Cursor said 0 (edited)"
    _write_row(written, ident, body)

    with Memory(written) as mem:
        broken = seal.check(mem)

    assert {b["who"] for b in broken} == {"Cursor"}


def test_two_writers_in_the_same_instant_do_not_look_like_tampering(
    knos_home, repo
) -> None:
    """The reason the chain is per writer rather than one global chain.

    A single chain forks the moment two processes append together, and a fork
    is indistinguishable from an edit. An alarm that fires during ordinary
    work is worse than no alarm, because people learn to ignore it.
    """
    when = _now()
    with Memory(repo) as mem:
        for i in range(5):
            mem.record(Fact(text=f"a {i}", source="session", where="A",
                            when=when, about="t"))
            mem.record(Fact(text=f"b {i}", source="session", where="B",
                            when=when, about="t"))

        assert seal.check(mem) == [], "interleaved writers read as tampering"


@pytest.mark.critical
def test_the_proof_dies_with_the_store(written) -> None:
    paths.store_for(written).unlink()

    with Memory(written) as mem:
        assert seal.counted(mem) == {"sealed": 0, "writers": 0}
