"""The gate asks who is buying, not only what is being bought.

Every other refusal in `gate.decide` is about the topic: somebody is mid-change
on it, a decision under it was reversed, the store already has it. This one is
about the agent, and it is the only question in knos whose answer costs real
money when it is wrong.

The rule is dull on purpose. An agent that has taken work here three times and
closed less than a third of it does not spend from a shared budget, because
money spent on work that gets abandoned is spent on nothing and it will happen
again in half an hour. Everyone else spends freely, including everyone new -
refusing on no evidence is the failure the whole record module is written
against.

It is not a security boundary and the docstring says so: an agent picks its own
name. It is the same trust model as every other claim here, applied where being
wrong is expensive.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from knos import gate, record
from knos.memory import TOPIC, Fact, Memory

PAID = ("Bought over x402 on Base: brief. Paid:"
        " https://basescan.org/tx/0xce109c28781fec2ea12b8e115d59b1bfea219434")


def _when(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _worked(mem, who: str, taken: int, closed: int) -> None:
    for n in range(taken):
        topic = f"job {who} {n}"
        record.note_taken(mem, topic, who, _when(300 - n))
        if n < closed:
            record.note_finished(mem, topic, who, _when(299 - n))


def test_a_new_agent_spends_freely(knos_home, repo) -> None:
    """Nobody is refused for having no record. That is the whole rule."""
    assert gate.decide(repo, "market brief: BTC", "btc", "a new agent")["verdict"] == "buy"


def test_one_bad_afternoon_is_not_a_record(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "Cursor", taken=2, closed=0)

    assert gate.decide(repo, "market brief: BTC", "btc", "Cursor")["verdict"] == "buy"


@pytest.mark.critical
def test_an_agent_that_abandons_its_work_stops_spending(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "a crashy runner", taken=6, closed=0)

    said = gate.decide(repo, "market brief: BTC", "btc", "a crashy runner")

    assert said["verdict"] == "unproven", said
    assert "closed 0" in said["answer"]
    assert "knos done" in said["answer"], "a refusal has to say how to undo it"


@pytest.mark.critical
def test_finishing_the_work_earns_the_money_back(knos_home, repo) -> None:
    """The refusal has to be recoverable by doing the thing it asks for."""
    with Memory(repo) as mem:
        _worked(mem, "Cursor", taken=6, closed=0)
    assert gate.decide(repo, "market brief: BTC", "btc", "Cursor")["verdict"] == "unproven"

    with Memory(repo) as mem:
        _worked(mem, "Cursor", taken=0, closed=0)
        for n in range(4):
            record.note_taken(mem, f"later {n}", "Cursor", _when(60 - n))
            record.note_finished(mem, f"later {n}", "Cursor", _when(59 - n))

    assert gate.decide(repo, "market brief: BTC", "btc", "Cursor")["verdict"] == "buy"


def test_a_reliable_agent_is_never_stopped(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "Claude Code", taken=9, closed=9)

    assert gate.decide(repo, "market brief: BTC", "btc", "Claude Code")["verdict"] == "buy"


def test_the_record_does_not_override_the_cheaper_answers(knos_home, repo) -> None:
    """An abandoner still gets what the store already paid for.

    The point is not to punish the agent, it is to stop money leaving. If the
    answer is already bought, handing it over costs nothing and refusing it
    would be spite rather than thrift.
    """
    with Memory(repo) as mem:
        _worked(mem, "a crashy runner", taken=6, closed=0)
        mem.record(Fact(text=PAID, source="note", where="you said so",
                        when=_when(), about="market brief: BTC"))
        mem.note_thing(TOPIC, "market brief: BTC", {"note": PAID, "when": "2026-09-08"})

    said = gate.decide(repo, "market brief: BTC", "btc", "a crashy runner")

    assert said["verdict"] == "have", said


@pytest.mark.critical
def test_it_dies_with_the_store(knos_home, repo) -> None:
    """Delete the memory and the shared card is handed to anybody again."""
    from knos import paths

    with Memory(repo) as mem:
        _worked(mem, "a crashy runner", taken=6, closed=0)
    assert gate.decide(repo, "market brief: BTC", "btc",
                       "a crashy runner")["verdict"] == "unproven"

    paths.store_for(repo).unlink()

    assert gate.decide(repo, "market brief: BTC", "btc",
                       "a crashy runner")["verdict"] == "buy"


def test_a_broken_record_still_fails_towards_buying(knos_home, repo, monkeypatch) -> None:
    """The gate's own rule: a gate that breaks must not become one that blocks.

    Everywhere else in this file the memory refuses. If reading the record
    throws, the honest thing is the behaviour that existed before it did.
    """
    def boom(*_a, **_k):
        raise RuntimeError("journal unreadable")

    monkeypatch.setattr(record, "may_spend", boom)

    said = gate.main(["knos.gate", "--topic", "x", "--ask", "x", "--repo", str(repo)])
    assert said == 0


def test_the_published_budget_numbers_are_the_ones_quoted() -> None:
    """The money figure a judge is pointed at, regenerated by a script."""
    import json
    from pathlib import Path

    where = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "budget.json"
    assert where.exists(), "run: python scripts/budget.py"
    got = json.loads(where.read_text(encoding="utf-8"))

    trusted = next(a for a in got["arms"] if a["arm"] == "trusted")
    learned = next(a for a in got["arms"] if a["arm"] == "learned")

    # The claim is not "less money moved" - it is that the money which moved
    # went to work somebody finished.
    assert trusted["spent_on_abandoned_work_usd"] > 0, (
        "the trusted arm has to waste money, or there is nothing to fix"
    )
    assert learned["spent_on_abandoned_work_usd"] == 0
    assert learned["refused"] > 0
    assert learned["spent_usd"] < trusted["spent_usd"]
    # And the reliable agents must not have been caught by it.
    assert learned["bought"] > 0, "the rule stopped everybody, which is not the rule"
