"""The one evidence file about real money, and the two ways it lied already.

Both bugs were in the same twenty lines and pointed opposite ways.

The first read a hash out of the bot's reply by looking for a word starting
with `0x`. The hash arrives inside `https://basescan.org/tx/0x...`, so nothing
matched, and a real $0.001 payment was written down as `paid: false,
spent_usd: 0.0`.

The second fixed that with a regex and promptly over-reported: an answer served
out of the store quotes the note written when it was bought, and that note
contains the original basescan URL - so a *free* round came back carrying a
hash and was counted as a second payment that never happened.

A receipt file that gets money wrong in either direction is worse than no
receipt file. These tests are the guard on that, and they check the shape
rather than the values, because the values are supposed to change every run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "live_gate.py"
EVIDENCE = ROOT / "docs" / "evidence" / "live-gate.json"


def _got() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_the_total_is_the_sum_of_the_rounds() -> None:
    """The arithmetic that was wrong twice."""
    got = _got()
    rounds = got["rounds"]

    counted = sum(float(r.get("cost_usd", 0) or 0) for r in rounds)

    assert abs(got["spent_usd"] - counted) < 1e-9, (
        f"the file says ${got['spent_usd']} spent and its own rounds add up "
        f"to ${counted}"
    )


def test_only_a_round_that_paid_carries_a_hash() -> None:
    """A quoted hash is not a payment.

    The free round echoes the note written when the answer was bought, and
    that note has the original transaction in it.
    """
    for row in _got()["rounds"]:
        if not row.get("paid"):
            assert not row.get("tx"), (
                f"round {row['round']} did not pay but carries a hash: "
                "that is the earlier purchase being quoted back"
            )
            assert float(row.get("cost_usd", 0) or 0) == 0.0


def test_a_paid_round_carries_a_hash_and_a_link() -> None:
    paid = [r for r in _got()["rounds"] if r.get("paid")]

    assert paid, "no payment at all was recorded"
    for row in paid:
        assert re.fullmatch(r"0x[0-9a-f]{64}", row["tx"]), row.get("tx")
        assert row["receipt"].endswith(row["tx"])


def test_the_refusal_is_in_there_and_costs_nothing() -> None:
    """The measurement is the money that did not move."""
    refused = [r for r in _got()["rounds"] if r["verdict"] == "unproven"]

    assert refused, "no round was refused, so nothing was demonstrated"
    for row in refused:
        assert float(row.get("cost_usd", 0) or 0) == 0.0
        assert "closed 0" in row["why"], (
            "the refusal should quote the store's own reason"
        )


def test_only_the_record_changes_between_rounds() -> None:
    """Same endpoint, same price, same wallet. Otherwise it is not an ablation."""
    got = _got()

    assert "Only what the store knows" in got["what_changed_between_rounds"]
    assert len({r["store_says"] for r in got["rounds"]}) == len(got["rounds"]), (
        "two rounds describe the same state, so one of them proves nothing"
    )


def test_it_says_the_scale_it_is_not() -> None:
    said = _got()["what_this_is_not"].lower()

    assert "cents" in said or "tens of" in said
    assert "not how that number scales" in said


def test_the_spend_is_capped_in_the_script() -> None:
    """A loop that pays per iteration is how a wallet empties through a typo."""
    said = SCRIPT.read_text(encoding="utf-8")

    assert "CAP_USD" in said
    assert "cap" in said.lower()
    got = _got()
    assert got["spent_usd"] <= got["cap_usd"]


def test_no_hash_is_written_into_the_script() -> None:
    said = SCRIPT.read_text(encoding="utf-8")
    body = said[said.index("def main("):]

    assert not re.search(r"0x[0-9a-fA-F]{40,}", body), (
        "a transaction hash appears in the script rather than in the run"
    )
