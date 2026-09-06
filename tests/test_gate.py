"""The memory decides whether money moves.

`knos remember` after a purchase was only ever half of "nobody here pays
twice". The other half is looking before you buy, and this is that half: the
store is asked, and its answer is what decides whether the agent spends.

Three verdicts, and only one of them costs anything.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from knos import answer, gate, paths
from knos.memory import TOPIC, Fact, Memory

TOPIC_NAME = "market brief: BTC"
BOUGHT = "Bought over x402 on Base: brief. Paid: https://basescan.org/tx/0xce109c"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remember_a_purchase(repo) -> None:
    """Exactly the pair of writes `knos remember` does after a purchase."""
    now = _now()
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        mem.record(
            Fact(text=BOUGHT, source="note", where="you said so", when=now, about=TOPIC_NAME)
        )
        mem.note_thing(TOPIC, TOPIC_NAME, {"note": BOUGHT, "when": now[:10]})


def test_an_empty_store_buys(knos_home, repo) -> None:
    paths.remember_pointed(repo)
    assert gate.decide(repo, TOPIC_NAME, TOPIC_NAME)["verdict"] == "buy"


@pytest.mark.critical
def test_the_second_identical_request_does_not_pay_again(knos_home, repo) -> None:
    """The claim in the README, as a test rather than a sentence."""
    _remember_a_purchase(repo)
    said = gate.decide(repo, TOPIC_NAME, TOPIC_NAME)
    assert said["verdict"] == "have"
    assert "Bought over x402" in said["answer"]
    assert said["where"], "a free answer must say where it came from"


@pytest.mark.critical
def test_a_standing_claim_refuses_to_spend(knos_home, repo) -> None:
    """Memory does not merely save money here, it stops it.

    Somebody mid-change on the topic means a bought answer is stale before it
    arrives, and the holder is the cheaper place to ask.
    """
    _remember_a_purchase(repo)
    with Memory(repo) as mem:
        mem.working_on(TOPIC_NAME, "Claude Code", _now())

    said = gate.decide(repo, TOPIC_NAME, TOPIC_NAME)
    assert said["verdict"] == "withheld"
    assert said["answer"].startswith("Withheld.")
    assert said["holder"] == "Claude Code"


def test_deleting_the_store_makes_it_pay_again(knos_home, repo) -> None:
    """The gate is only as durable as Sibyl. That is the point, not a caveat."""
    _remember_a_purchase(repo)
    assert gate.decide(repo, TOPIC_NAME, TOPIC_NAME)["verdict"] == "have"

    paths.store_for(repo).unlink()

    assert gate.decide(repo, TOPIC_NAME, TOPIC_NAME)["verdict"] == "buy"


def test_a_broken_gate_buys_rather_than_blocks(knos_home, repo, monkeypatch) -> None:
    """Fail towards what happened before the gate existed.

    A gate that crashes must not become a gate that spends, and must not
    become a gate that blocks the product either. `main` catches everything
    and answers "buy".
    """
    import json

    def explode(*_a, **_k):
        raise RuntimeError("store on fire")

    monkeypatch.setattr(gate, "decide", explode)
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **_k: printed.append(a[0]))

    assert gate.main(["knos.gate", "--topic", TOPIC_NAME, "--ask", TOPIC_NAME]) == 0
    said = json.loads(printed[-1])
    assert said["verdict"] == "buy"
    assert "store on fire" in said["why"]


def test_an_unrelated_topic_is_not_served_from_memory(knos_home, repo) -> None:
    """The gate must not hand back the wrong purchase to save a cent."""
    _remember_a_purchase(repo)
    assert gate.decide(repo, "news: ethereum", "news ethereum")["verdict"] == "buy"


@pytest.mark.critical
def test_a_near_neighbour_is_not_served_the_wrong_asset(knos_home, repo) -> None:
    """The bug this test exists for, because it was live and it was silent.

    The gate used to search rather than read the exact name, and search
    matches on shared stems - so a store holding "market brief: BTC" answered
    a request for "market brief: ETH" and handed the agent the wrong asset's
    numbers, for free, with a real receipt attached. Saving a cent by
    returning something true about a different subject is worse than paying.
    """
    _remember_a_purchase(repo)  # buys "market brief: BTC"

    said = gate.decide(repo, "market brief: ETH", "market brief: ETH")
    assert said["verdict"] == "buy", "the gate served BTC when asked for ETH"

    # And the one it does have is still free.
    assert gate.decide(repo, TOPIC_NAME, TOPIC_NAME)["verdict"] == "have"
