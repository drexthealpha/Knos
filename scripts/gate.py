"""Delete the store and show what stops working.

    python scripts/gate.py

Sibyl is not a cache in front of something else. There is no second copy, no
fallback file, and nothing is re-derived on the fly. It writes into this repo's own
store, proves the two things that matter, deletes the SQLite file, and proves
both of them are gone. Refill afterwards with `knos point`.

What must die:
  1. the withhold path  - a claim cannot be held or read, so no agent is
     refused, so two of them edit the same thing
  2. the paid path      - the deliverable an ACP job or an x402 request
     would have sold comes out of the same store, so there is nothing to sell

What must survive, and is not memory: commits and files, because those were
never Knos's to begin with.

Exits non-zero if anything survives that should not.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    from knos import answer, paths
    from knos.memory import TOPIC, Fact, Memory

    repo = ROOT
    print(f"repo:  {repo}")

    with Memory(repo) as mem:
        db = Path(mem.db_path)

        # 1. What knos was told. Exists nowhere else.
        mem.record(
            Fact(
                text="the gate: deleting the store must break withholding and selling",
                source="note",
                where="scripts/gate.py",
                when=now(),
                about="the gate",
            )
        )
        mem.note_thing(TOPIC, "the gate", {"note": "written by scripts/gate.py"})

        # 2. Something the agent paid real money for. A brief bought over
        #    x402 cannot be re-derived from the repo, and neither can the
        #    receipt, so this is the half an ACP buyer is paying for.
        mem.record(
            Fact(
                text=(
                    "Bought over x402 on Base: a market brief."
                    " Receipt: written by scripts/gate.py."
                ),
                source="note",
                where="scripts/gate.py",
                when=now(),
                about="a paid brief",
            )
        )
        mem.note_thing(TOPIC, "a paid brief", {"note": "bought, not re-derivable"})

        # 3. A live claim, which is what the withhold path stands on.
        mem.working_on("the gate", "Claude Code", now())

        held = [c["topic"] for c in mem.claims()]
        sellable = len(answer.ask(repo, mem, "the gate"))
        paid = [p for p in answer.ask(repo, mem, "a paid brief") if "x402" in p.text]

    print(f"store: {db}")
    print("\nBEFORE")
    print(f"  claims held      : {held}")
    print(f"  passages to sell : {sellable}")
    print(f"  paid briefs held : {len(paid)}")
    assert "the gate" in held, "nothing was claimed, so there is no gate to test"
    assert sellable > 0, "nothing to sell, so the ACP path proves nothing"
    assert paid, "nothing paid for, so the x402 half proves nothing"

    print("\ndeleting the store")
    for path in (db, db.with_suffix(db.suffix + "-wal"), db.with_suffix(db.suffix + "-shm")):
        if path.exists():
            path.unlink()
            print(f"  rm {path.name}")
    paths.shared_root.cache_clear()
    paths.work_root.cache_clear()

    with Memory(repo) as mem:
        after_held = [c["topic"] for c in mem.claims()]
        after_found = answer.ask(repo, mem, "the gate")
        after_paid = [
            p for p in answer.ask(repo, mem, "a paid brief") if "x402" in p.text
        ]

    print("\nAFTER")
    print(f"  claims held      : {after_held}")
    print(f"  passages to sell : {len(after_found)}")
    print(f"  paid briefs held : {len(after_paid)}")

    assert after_held == [], f"a claim survived the store being deleted: {after_held}"
    assert not any(
        "gate.py" in p.where for p in after_found
    ), "what knos was told survived the store being deleted"
    assert not after_paid, (
        "a brief the agent PAID FOR survived the store being deleted - it"
        " exists nowhere else, so an ACP buyer should now get nothing"
    )

    print("\nOK - three things died with that one file:")
    print("     the claim (so nobody is withheld any more),")
    print("     what knos was told, and the brief it paid for.")
    print("     An ACP buyer now gets nothing: there is nothing left to sell.")
    print("     Commits and files are still there; they were never knos's.")
    print("     Re-fill with:  knos point")
    return 0


if __name__ == "__main__":
    sys.exit(main())
