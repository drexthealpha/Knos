"""House rule: Sibyl is the only durable store. Delete memory.db and the product must die.

Found in the full read (memory.py:142): opening a repo whose store had been deleted silently created an empty one, so
every question answered "nothing is known". Now a store that was born here and is gone is refused in words. `knos point`
is incremental and never deletes or recreates anything; starting over is `knos reset --yes`, which keeps a backup.

Dropped in 0.2.0: `test_knos_point_starts_over_on_purpose` (point no longer starts over; `knos reset --yes` does, and is
tested here instead).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from knos import paths, refresh
from knos.cli import main
from knos.memory import TOPIC, Fact, Memory, StoreGone


def _born_then_deleted(repo):
    """A store that existed, with one note in it, whose file is then deleted out from under knos."""
    now = datetime.now(timezone.utc).isoformat()
    with Memory(repo) as mem:
        mem.record(Fact(text="we chose sqlite over redis", source="note", where="you said so", when=now,
                        about="storage"))
        mem.note_thing(TOPIC, "storage", {"note": "we chose sqlite over redis", "when": now[:10]})
    db = paths.store_for(repo)
    assert db.exists() and paths.born_for(repo).exists()
    db.unlink()
    for extra in ("-wal", "-shm"):
        db.with_name(db.name + extra).unlink(missing_ok=True)
    return db


def test_a_deleted_store_is_refused_not_recreated(knos_home, repo) -> None:
    db = _born_then_deleted(repo)

    with pytest.raises(StoreGone, match=r"knos reset --yes"):
        Memory(repo)
    assert not db.exists(), "nothing was created in its place"


def test_every_command_says_so_rather_than_answering_from_nothing(knos_home, repo, capsys) -> None:
    """The refusal reaches the person as one line, not a traceback and not an empty answer."""
    db = _born_then_deleted(repo)
    capsys.readouterr()

    assert main(["notes"]) == 1
    said = capsys.readouterr().out
    assert "is gone" in said and "knos reset --yes" in said, said
    assert "Traceback" not in said
    assert not db.exists()


def test_knos_point_never_starts_over_on_its_own(knos_home, repo, capsys) -> None:
    """`knos point` is incremental: it refuses a missing store instead of quietly beginning an empty one."""
    db = _born_then_deleted(repo)
    capsys.readouterr()

    assert main(["point", str(repo)]) == 1
    said = capsys.readouterr().out
    assert "knos reset --yes" in said, said
    assert not db.exists(), "point recreated a store it was told was gone"


def test_knos_point_keeps_what_it_was_told(knos_home, repo) -> None:
    """Reading again adds; it never throws away what exists nowhere else."""
    now = datetime.now(timezone.utc).isoformat()
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, "storage", {"note": "we chose sqlite over redis", "when": now[:10]})

    assert main(["point", str(repo)]) == 0
    assert main(["point", str(repo)]) == 0

    with Memory(repo) as mem:
        assert mem.remembered("storage")


def test_reset_without_yes_changes_nothing(knos_home, repo, capsys) -> None:
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, "storage", {"note": "we chose sqlite", "when": "2026-09-01"})
    capsys.readouterr()

    assert main(["reset"]) == 1
    assert "knos reset --yes" in capsys.readouterr().out
    with Memory(repo) as mem:
        assert mem.remembered("storage")
    assert not (knos_home / "backups").exists()


def test_reset_starts_over_on_purpose_and_keeps_a_backup(knos_home, repo, capsys) -> None:
    with Memory(repo) as mem:
        mem.record(Fact(text="we chose sqlite over redis", source="note", where="you said so",
                        when="2026-09-01T00:00:00+00:00", about="storage"))
        mem.note_thing(TOPIC, "storage", {"note": "we chose sqlite over redis", "when": "2026-09-01"})
    paths.store_for(repo)
    read_log = refresh.read_db(repo)
    capsys.readouterr()

    assert main(["reset", "--yes"]) == 0
    said = capsys.readouterr().out
    assert "Backup:" in said, said

    backups = list((knos_home / "backups").glob(f"{repo.name}-*.db"))
    assert len(backups) == 1, backups
    conn = sqlite3.connect(str(backups[0]))
    try:
        kept = [r[0] for r in conn.execute("SELECT evaluated FROM journal_events")]
    finally:
        conn.close()
    assert any("we chose sqlite over redis" in str(k) for k in kept), "the backup does not hold what the store held"

    # The store is shared by every repo (as tenants, where Sibyl's cap counts it): reset takes out this repo's
    # tenant, its birth marker and its read log.
    for gone in (paths.born_for(repo), read_log):
        assert not gone.exists(), gone

    # Started over: the next open is a new, empty store, and it is born again.
    with Memory(repo) as mem:
        assert not mem.remembered("storage")
        assert mem.journal() == []
    assert paths.born_for(repo).exists()


def test_reset_recovers_a_store_that_was_deleted_by_hand(knos_home, repo, capsys) -> None:
    """The fix the refusal names has to actually work, with nothing left to back up."""
    _born_then_deleted(repo)
    capsys.readouterr()

    assert main(["reset", "--yes"]) == 0
    assert "There was no store." in capsys.readouterr().out
    assert not paths.born_for(repo).exists()
    with Memory(repo) as mem:
        assert mem.notes() == []
